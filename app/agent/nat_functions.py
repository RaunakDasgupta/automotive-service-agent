"""NeMo Agent Toolkit registration for the service-operations tools.

The tools in app/agent/tools.py are plain typed Python functions so they stay
testable and reusable. This module wraps them for NeMo Agent Toolkit (aiqtoolkit)
without changing them. If the toolkit is not installed, importing this module
does nothing and the agent runs on its own router - so the demo never depends on
the wrapper being present.
"""
from __future__ import annotations
from pydantic import BaseModel, Field

from app.agent import tools as T

try:
    # nvidia-nat is the package; `aiq` is a deprecated shim over it that warns
    # on every import. Prefer the real namespace, fall back for older installs.
    try:
        from nat.builder.builder import Builder
        from nat.builder.function_info import FunctionInfo
        from nat.cli.register_workflow import register_function
        from nat.data_models.function import FunctionBaseConfig
    except ImportError:
        from aiq.builder.builder import Builder
        from aiq.builder.function_info import FunctionInfo
        from aiq.cli.register_workflow import register_function
        from aiq.data_models.function import FunctionBaseConfig
    NAT_AVAILABLE = True
except ImportError:                                    # toolkit not installed
    NAT_AVAILABLE = False


# --- argument schemas -------------------------------------------------------
class RoInput(BaseModel):
    ro_number: str = Field(description="Repair order number, e.g. RO-26-08165")


class RoWindowInput(BaseModel):
    ro_number: str = Field(description="Repair order number")
    since_hours: int = Field(default=12, description="Look-back window in hours")


class ListInput(BaseModel):
    filter: str = Field(default="active",
                        description="active|blocked|at_risk|safety|waiter|all, "
                                    "or a lifecycle state such as PARTS_HOLD")
    limit: int = Field(default=25)


class StaffInput(BaseModel):
    staff_id: str = Field(description="Staff id, e.g. EMP014")
    days: int = Field(default=7)


class ShiftInput(BaseModel):
    shift: str = Field(default="AFTERNOON", description="MORNING or AFTERNOON")


class DaysInput(BaseModel):
    days: int = Field(default=7)


class SearchInput(BaseModel):
    query: str = Field(description="Natural-language search over technician updates")
    k: int = Field(default=4)
    ro_number: str | None = Field(default=None)


class OpInput(BaseModel):
    op_code: str = Field(description="Labour operation code, e.g. BRK-FR-PAD")


class IntakeInput(BaseModel):
    days: int = Field(default=7,
                      description="Window ending now: 1 today, 7 this week, "
                                  "30 this month")


class ShiftActivityInput(BaseModel):
    day_offset: int = Field(default=0,
                            description="0 today, -1 yesterday, -2 the day before")
    shift: str = Field(default="", description="MORNING, AFTERNOON, or empty for both")
    view: str = Field(default="people",
                      description="people = who worked; vehicles = which cars")


# Every tool, its schema, and a one-line description for the planner.
REGISTRY = [
    ("get_ro_state",            T.get_ro_state,            RoInput),
    ("get_ro_timeline",         T.get_ro_timeline,         RoInput),
    ("list_ros",                T.list_ros,                ListInput),
    ("get_technician_activity", T.get_technician_activity, StaffInput),
    ("generate_handover",       T.generate_handover,       ShiftInput),
    ("detect_anomalies",        T.detect_anomalies,        DaysInput),
    ("diff_ro",                 T.diff_ro,                 RoWindowInput),
    ("search_updates",          T.search_updates,          SearchInput),
    ("get_op_code_info",        T.get_op_code_info,        OpInput),
    ("get_shift_activity",      T.get_shift_activity,      ShiftActivityInput),
    ("get_intake",               T.get_intake,              IntakeInput),
]


if NAT_AVAILABLE:
    import os
    import types

    def _register(tool_name, fn, schema):
        """One NAT function type per tool.

        The previous shape - one registered type yielding ten FunctionInfo -
        exposed exactly one of them. `register_function` wraps an ASYNC
        GENERATOR whose single yield is the context-manager boundary: what
        comes before it is setup, what comes after is teardown, and the yielded
        value is THE function. Yielding ten does not register ten; it registers
        the first and drops the rest, and the agent is then told to call a tool
        name that resolves to nothing.

        The config class is built with types.new_class because
        FunctionBaseConfig takes its registered name as a class keyword, which
        the three-argument form of type() cannot pass.
        """
        cfg_cls = types.new_class(
            f"{tool_name.title().replace('_', '')}Config",
            (FunctionBaseConfig,),
            {"name": f"asoia_{tool_name}"},
            lambda ns: ns.update({
                "__doc__": f"Configuration for the {tool_name} tool.",
                "__annotations__": {"db_path": str},
                "db_path": Field(
                    default="data/generated/service.sqlite",
                    description="SQLite database produced by notebook 01"),
            }),
        )

        async def _build(config, builder: "Builder", _fn=fn, _schema=schema,
                         _name=tool_name):
            os.environ.setdefault("ASOIA_DB", config.db_path)

            seen: set[str] = set()

            async def _run(payload):
                args = payload.model_dump(exclude_none=True)
                return _once(seen, _name, args, _fn(**args))

            _run.__annotations__ = {"payload": _schema, "return": dict}

            yield FunctionInfo.from_fn(
                _run, input_schema=_schema,
                description=_describe(_name, _fn))

        register_function(config_type=cfg_cls)(_build)
        return cfg_cls

    NAT_TYPES = {name: _register(name, fn, schema)
                 for name, fn, schema in REGISTRY}


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
        "get_intake":
            "How many vehicles came INTO the shop over a window, and what "
            "became of them. Use for 'how many cars came in this week' and "
            "'how busy were we'. Not which cars were worked on.",
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
