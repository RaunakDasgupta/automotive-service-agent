#!/usr/bin/env python3
"""pass 52 - the toolkit workflow picked the right tool and never called it.

    .venv/bin/python patches/quality_pass52.py            apply
    .venv/bin/python patches/quality_pass52.py --check    verify, change nothing

Pass 51 recorded the workflow at six of six question classes. Running the same
six questions again shows what that grading actually measured:

    Workflow Result:
    ['{"name": "list_ros", "parameters": {"filter": "safety"}}']

That is the model's TEXT, handed back as the final answer. Every run carried
`tool_calls=[]`, no tool ever executed, and each exited 0 in three seconds -
which is why grading on "did it terminate with a result" called it a pass. The
honest reading is two numbers: six of six on tool SELECTION, nought of six on
EXECUTION.

The cause is the server, not the client. Asked directly with curl, with a
proper OpenAI `tools` array and tool_choice auto, the NIM replies with

    {"role": "assistant", "content": "{\"name\": \"get_ro_state\", ...}"}

and no `tool_calls` field, finish_reason "stop". vLLM's tool-call parsers ship
inside the container, but this NIM release exposes no way to turn one on, so
there is nothing to configure: the model writes its calls as prose.

So the fix is a shim at the model boundary, not a different agent. One LLM
provider - `asoia_nim_toolshim` - serves the same NIM over its OpenAI route and
lifts a prose tool call into `tool_calls` before LangChain sees the message.
The toolkit's own agent still does the orchestrating, which is the point of
having it; it just stops being lied to about what the model said.

Three details the model made necessary, each observed in a real reply:

  - the arguments arrive wrapped in the schema's own envelope
    ({"properties": {...}}), so a lone "properties" key is unwrapped
  - nulls stand for arguments the model declined to pass, so they are dropped
    rather than sent to a field whose type will not take None
  - the repair runs only when tools were actually bound, so an ordinary answer
    that happens to be JSON is never mistaken for a call

Two more faults only became visible once tools started running, which is the
real argument for fixing this rather than restating the claim:

  - langchain-openai 1.x sends `max_completion_tokens`; this NIM's OpenAI route
    rejects it with a 400, so the payload hook renames it back to `max_tokens`
  - a safety list is 30,000 characters of repair orders against an 8,192-token
    context, and two of the six classes died on it. `_fit` trims the longest
    list in a payload and records `truncated: {field, shown, of}`, so a partial
    list cannot be reported as the whole shop.

Streaming is disabled on the client: it would bypass the repair.
"""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = "--check" in sys.argv
NF = ROOT / "app/agent/nat_functions.py"
WF = ROOT / "app/agent/workflow.yml"

ANCHOR = "NAT_TYPES = {name: _register(name, fn, schema)"

RUN_OLD = """            async def _run(payload):
                return _fn(**payload.model_dump(exclude_none=True))
"""
DESC_OLD = "                description=(_fn.__doc__ or _name).strip())\n"
DESC_NEW = "                description=_describe(_name, _fn))\n"
RUN_NEW = """            seen: set[str] = set()

            async def _run(payload):
                args = payload.model_dump(exclude_none=True)
                return _once(seen, _name, args, _fn(**args))
"""

OLD_LLM = ("    _type: nim\n"
           "    model_name: nvidia/llama-3.1-nemotron-nano-8b-v1\n"
           "    base_url: http://localhost:8000/v1      "
           "# self-hosted NIM; omit to use build.nvidia.com\n"
           "    temperature: 0.2\n")      # the embedder is a nim too
NEW_LLM = """    # asoia_nim_toolshim, not nim. Asked with the OpenAI `tools` array this
    # NIM returns the call as assistant TEXT with no tool_calls field, so the
    # agent saw no call to make and handed the JSON back as its answer. The
    # provider registered in app/agent/nat_functions.py lifts it back out.
    _type: asoia_nim_toolshim
    model_name: nvidia/llama-3.1-nemotron-nano-8b-v1
    base_url: http://localhost:8000/v1      # self-hosted NIM
    # 0.0, not 0.2. Choosing between ten tools is a classification, and at 0.2
    # the safety question picked list_ros on one run and detect_anomalies on
    # the next - from an identical prompt.
    temperature: 0.0
"""

OLD_PROMPT = """    Call a tool when you need shop data. When the tools have answered the
    question, reply with the answer and stop.
"""
NEW_PROMPT = """    Call a tool when you need shop data. When the tools have answered the
    question, reply with the answer and stop.

    Write that answer as plain prose. Never wrap it in JSON, and never read the
    payload back field by field.

    If a tool result carries "truncated", it did not fit - say how many of how
    many you are describing, and never present the part as the whole.

    Call one tool, then answer. Never call the same tool twice with the same
    arguments: once it has returned, the answer is in what it returned, or it
    is not there at all and you should say so.

    A result of {"repeat_call": true} is not news and is never part of an
    answer. It means you already have what you asked for: write the answer now,
    from the earlier result.
"""

SHIM = r'''

# --- the NIM writes its tool calls as prose ---------------------------------
# Asked with the OpenAI `tools` array, this NIM replies
#
#   {"role": "assistant",
#    "content": "{\"name\": \"get_ro_state\", \"parameters\": {...}}"}
#
# with no `tool_calls` field and finish_reason "stop". That was proven against
# the endpoint with curl, so it is the server and not the client: LangChain sees
# an ordinary assistant message, the toolkit's agent sees no call to make, and
# it hands that JSON back as the final answer. Every one of the six question
# classes chose the right tool with the right arguments and then ran none of
# them - and because the run terminates cleanly, grading on "did it finish"
# called that six of six.
#
# This moves the call from the text to where the protocol says it goes. It is
# what this project's own router has always done with this model; the toolkit
# only needed telling.
if NAT_AVAILABLE:
    import json
    import uuid

    # An 8,192-token context, about 1,600 of which is the system prompt and the
    # ten tool schemas, with 700 reserved for the reply. list_ros(filter="safety")
    # returns 30,000 characters of repair orders, and the first run after the
    # tool calls started working died on exactly that: 9,250 message tokens
    # against a limit of 8,192. This never arose while no tool ran, and it never
    # arises on the project's own path, which renders a payload in Python. The
    # toolkit hands it to the model, so it has to fit.
    #
    # 6,000 characters is about 1,500 tokens, and the budget has to survive the
    # agent asking twice: at 12,000 a single payload fits and a second round
    # does not, which is how three of the six classes died even after the
    # trimming started working. Three rounds now come to roughly 6,800 tokens.
    _PAYLOAD_CHARS = 6000

    def _fit(result):
        """Keep a tool payload inside the context, and say when it did not fit."""
        if not isinstance(result, dict):
            return result
        size = lambda o: len(json.dumps(o, default=str))
        if size(result) <= _PAYLOAD_CHARS:
            return result
        out = json.loads(json.dumps(result, default=str))

        def every_list(node, path=()):
            """Every list in the payload, however deep. generate_handover keeps
            its 23,000 characters in a dict of groups, so trimming only the top
            level trimmed nothing at all."""
            if isinstance(node, dict):
                for k, v in node.items():
                    yield from every_list(v, path + (str(k),))
            elif isinstance(node, list):
                yield path, node
                for i, v in enumerate(node):
                    yield from every_list(v, path + (str(i),))

        full, state = {}, {}
        for _ in range(200):
            if size(out) <= _PAYLOAD_CHARS:
                break
            biggest = max(((size(n), p, n) for p, n in every_list(out) if n),
                          default=None)
            if biggest is None:
                break
            _, path, node = biggest
            key = ".".join(path) or "(root)"
            full.setdefault(key, len(node))
            for _ in range(max(1, len(node) // 4)):
                if node:
                    node.pop()
            state[key] = {"shown": len(node), "of": full[key]}
        if state:
            # Dropping rows silently would let the model report a part of the
            # shop as the whole of it. The real counts stay in the payload.
            out["truncated"] = state
        return out

    # The docstrings were written for people reading the code, and the toolkit's
    # planner reads them as its only guide to which tool answers what. At
    # temperature 0 the safety question chose detect_anomalies - "cross-repair-
    # order patterns" - and then called it thirteen times, because the answer it
    # wanted was never going to be in that payload. This project's own router
    # never had to choose: it routes on keywords. These lines are for the model.
    NAT_HINTS = {
        "list_ros":
            "Repair orders in a given state. filter='safety' answers which "
            "vehicles cannot be released on safety grounds; 'blocked' which are "
            "waiting on parts; 'at_risk' which will miss their promised time; "
            "'waiter' which customers are on site.",
        "detect_anomalies":
            "ONLY for 'anything unusual this week' and 'any patterns'. Never for "
            "safety, for one repair order, or for who worked a shift.",
        "search_updates":
            "ONLY for free text somebody wrote: 'has anyone seen this fault "
            "before'. Never for current state, which the other tools compute.",
        "generate_handover":
            "The shift handover, already prioritised. Use it whenever a handover "
            "or a shift summary is asked for.",
        "get_shift_activity":
            "Who worked, or which vehicles were worked on, for a day and shift.",
        "diff_ro": "What changed on ONE repair order inside a time window.",
        "get_ro_state": "Everything current about ONE repair order.",
        "get_ro_timeline": "The event history of ONE repair order.",
        "get_technician_activity": "What ONE member of staff has done.",
        "get_op_code_info": "What one labour operation code means.",
    }

    def _describe(name, fn):
        """The docstring, plus what this tool is for and what it is not."""
        doc = " ".join((fn.__doc__ or name).split())
        hint = NAT_HINTS.get(name)
        return f"{doc} {hint}" if hint else doc

    def _once(seen, name, args, result):
        """The same call twice is the agent forgetting that it already asked.

        At temperature 0 the safety question called list_ros three times and the
        search question called search_updates ten, with identical arguments every
        time, and each round put the whole payload back into an 8,192-token
        context until it burst. Shrinking the payload only bought a round. What
        stops it is not answering the same question twice: the data is already
        in the transcript, and saying so is both true and short.
        """
        key = json.dumps([name, args], sort_keys=True, default=str)
        if key in seen:
            # Measured both ways over the same six questions. A bare
            # {"repeat_call": true, "new_data": false} reads to this model as a
            # refusal - three of the six then apologised and answered nothing -
            # where a sentence telling it where the data is leaves three
            # answering from the payload. Neither is good. This one is better.
            return {"repeat_call": True, "tool": name,
                    "note": "This exact call already returned, higher up this "
                            "conversation. Answer from that result, or say the "
                            "answer is not in it."}
        seen.add(key)
        return _fit(result)

    def _text_tool_call(text):
        """The tool call a model wrote as prose, or None if it wrote none."""
        if not isinstance(text, str):
            return None
        s = text.strip()
        if s.startswith("```"):
            s = s.strip("`")
            if s[:4].lower() == "json":
                s = s[4:]
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            return None
        # Only a message that is NOTHING BUT the call is a call. "I need to call
        # generate_handover with shift AFTERNOON. Here's the function call:
        # {...}" is the model TALKING about a call, and converting that into a
        # real one is what sent three of the six questions round the loop until
        # the context burst.
        if s[:i].strip() or s[j + 1:].strip():
            return None
        try:
            obj = json.loads(s[i:j + 1])
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        name = obj.get("name")
        args = obj.get("parameters", obj.get("arguments", {}))
        if not isinstance(name, str) or not isinstance(args, dict):
            return None
        # The model often hands back the schema's own envelope rather than the
        # arguments the schema describes.
        if set(args) == {"properties"} and isinstance(args["properties"], dict):
            args = args["properties"]
        # A null for an optional argument is the model declining to pass it.
        return {"name": name,
                "args": {k: v for k, v in args.items() if v is not None}}

    def _bound_tool_names(kwargs):
        """The tools this particular call was given. Empty means plain chat."""
        names = set()
        for t in kwargs.get("tools") or []:
            fn = t.get("function", t) if isinstance(t, dict) else {}
            if isinstance(fn, dict) and isinstance(fn.get("name"), str):
                names.add(fn["name"])
        return names

    def _lift_tool_calls(result, known):
        """Put a prose tool call where the protocol says it goes."""
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        if not known:               # nothing was bound, so nothing is a call
            return result
        gens, changed = [], False
        for gen in result.generations:
            msg = getattr(gen, "message", None)
            call = (None if not isinstance(msg, AIMessage) or msg.tool_calls
                    else _text_tool_call(msg.content))
            if call is None or call["name"] not in known:
                gens.append(gen)
                continue
            changed = True
            gens.append(ChatGeneration(
                message=AIMessage(
                    content="",
                    tool_calls=[{"name": call["name"], "args": call["args"],
                                 "id": "call_" + uuid.uuid4().hex[:8],
                                 "type": "tool_call"}],
                    additional_kwargs=dict(msg.additional_kwargs),
                    response_metadata=dict(msg.response_metadata),
                    usage_metadata=msg.usage_metadata),
                generation_info=gen.generation_info))
        if not changed:
            return result
        return ChatResult(generations=gens, llm_output=result.llm_output)

    try:
        from langchain_openai import ChatOpenAI
        from pydantic import ConfigDict

        try:
            from nat.builder.framework_enum import LLMFrameworkEnum
            from nat.builder.llm import LLMProviderInfo
            from nat.cli.register_workflow import (register_llm_client,
                                                   register_llm_provider)
            from nat.data_models.llm import LLMBaseConfig
        except ImportError:
            from aiq.builder.framework_enum import LLMFrameworkEnum
            from aiq.builder.llm import LLMProviderInfo
            from aiq.cli.register_workflow import (register_llm_client,
                                                   register_llm_provider)
            from aiq.data_models.llm import LLMBaseConfig

        class _TextToolCallChat(ChatOpenAI):
            """A chat model that accepts a tool call written as text."""

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                return _lift_tool_calls(
                    super()._generate(messages, stop=stop,
                                      run_manager=run_manager, **kwargs),
                    _bound_tool_names(kwargs))

            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                return _lift_tool_calls(
                    await super()._agenerate(messages, stop=stop,
                                             run_manager=run_manager, **kwargs),
                    _bound_tool_names(kwargs))

            def _get_request_payload(self, input_, *, stop=None, **kwargs):
                payload = super()._get_request_payload(input_, stop=stop, **kwargs)
                # This NIM's OpenAI route predates max_completion_tokens and
                # rejects it outright: 400, extra_forbidden.
                if "max_completion_tokens" in payload:
                    payload["max_tokens"] = payload.pop("max_completion_tokens")
                return payload

        class NimTextToolCallConfig(LLMBaseConfig, name="asoia_nim_toolshim"):
            """A NIM reached over its OpenAI route, tool calls lifted out of the text."""

            model_config = ConfigDict(protected_namespaces=(), extra="allow")
            model_name: str = Field(description="The model this NIM serves")
            base_url: str = Field(default="http://localhost:8000/v1")
            temperature: float = Field(default=0.0)
            max_tokens: int = Field(default=700)

        @register_llm_provider(config_type=NimTextToolCallConfig)
        async def _asoia_nim_provider(llm_config, _builder):
            yield LLMProviderInfo(
                config=llm_config,
                description="A NIM that writes its tool calls as text.")

        @register_llm_client(config_type=NimTextToolCallConfig,
                             wrapper_type=LLMFrameworkEnum.LANGCHAIN)
        async def _asoia_nim_langchain(llm_config, _builder):
            yield _TextToolCallChat(
                model=llm_config.model_name,
                base_url=llm_config.base_url,
                # A local NIM authenticates nobody; the client insists on a key.
                api_key="local-nim",
                temperature=llm_config.temperature,
                max_tokens=llm_config.max_tokens,
                # Streaming would bypass _agenerate, and the repair with it.
                disable_streaming=True,
            )
    except ImportError:            # older toolkit, or langchain_openai missing
        pass
'''

nf = NF.read_text()
wf = WF.read_text()

if "asoia_nim_toolshim" in nf and "asoia_nim_toolshim" in wf:
    print("  already   app/agent/nat_functions.py, app/agent/workflow.yml")
    sys.exit(0)

for path, text, anchor, what in ((NF, nf, ANCHOR, "the registration loop"),
                                 (NF, nf, RUN_OLD, "the tool call"),
                                 (NF, nf, DESC_OLD, "the tool description"),
                                 (WF, wf, OLD_LLM, "the llm block"),
                                 (WF, wf, OLD_PROMPT, "the prompt tail")):
    if text.count(anchor) != 1:
        print(f"FAIL: {path.name}  {what}: anchor found {text.count(anchor)} "
              "times, expected 1.")
        print("      Run passes 1-51 first. Stopping without changes.")
        sys.exit(1)

if not CHECK:
    nf2 = nf.replace(RUN_OLD, RUN_NEW, 1).replace(DESC_OLD, DESC_NEW, 1)
    NF.write_text(nf2.rstrip("\n") + "\n" + SHIM)
    WF.write_text(wf.replace(OLD_LLM, NEW_LLM, 1).replace(OLD_PROMPT, NEW_PROMPT, 1))
verb = "would patch" if CHECK else "patched  "
print(f"  {verb} app/agent/nat_functions.py (asoia_nim_toolshim provider and "
      f"the payload fitter, +{SHIM.count(chr(10))} lines)")
print(f"  {verb} app/agent/workflow.yml     (nim -> asoia_nim_toolshim, "
      "prose and truncation rules)")
