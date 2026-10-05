#!/usr/bin/env python3
"""Thirty-eighth pass: traces of how each answer was produced.

Run from the project root:   .venv/bin/python quality_pass38.py

answer_log records WHAT was answered - 345 rows of question, answer,
route, grounded, citations. Nothing recorded HOW: which tool ran, what it
was given, what came back, what the model was handed. A loop meant to
learn from its own results cannot act on an outcome alone, because the
outcome does not say which step to change.

app/obs/trace.py emits ATOF 0.1 through NeMo Relay, wired in at the only
two places it needs to be: tools.call() dispatches every tool, and
client.chat() is every non-streaming model call.

WHAT WOULD HAVE LOOKED RIGHT AND CAPTURED NOTHING

Relay's advertised surface for this is intercepts:

    register_tool_execution(name, priority, fn)   # fn(context, next_call)

Middleware, where next_call continues RELAY's chain. This agent calls its
NIMs over httpx and dispatches tools through a Python dict, so those
intercepts would never once have fired. It would have imported cleanly,
logged nothing, and looked finished - pass 35's rails that had never
loaded, pass 34's ASR that had never served a request.

The manual span API does work outside the runtime, established by writing
a trace and reading it back before wiring anything. Three things only a
real attempt finds: the mode is an AtofExporterMode enum, not the string
its config field invites; deregister() wants the subscriber name back; and
llm.call wants LLMRequest(headers, content), not a dict.

Off unless ASOIA_TRACE=file. Any other value is also off. Every entry
point swallows every exception and the first failure disables tracing for
the process - tested by making the exporter raise.
"""
import sys, pathlib, ast

ROOT = pathlib.Path(".")
CHANGES = []


def edit(rel, old, new, label, skip_if=None):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run from the project root")
    s = p.read_text()
    if skip_if and skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    n = s.count(old)
    if n != 1:
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.\n"
                 "      NOTE: edits before this one HAVE been applied.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def write(rel, body, label, skip_if=None):
    p = ROOT / rel
    if skip_if and p.exists() and skip_if in p.read_text():
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    CHANGES.append(f"  ok    {label}")


def append(rel, body, label, skip_if):
    p = ROOT / rel
    s = p.read_text()
    if skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    p.write_text(s + body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. the tracer
write('app/obs/trace.py', '"""ATOF traces of every tool and model call, through NeMo Relay. Off by default.\n\nWHY THIS EXISTS\n\n`answer_log` records WHAT was answered and whether it was grounded. It does not\nrecord HOW the answer was produced: which tools ran, in what order, what each was\ngiven and what it returned, what the model was handed. A loop meant to learn from\nits own results needs the second thing, and nothing in this project captured it.\n\nWHY NOT RELAY\'S INTERCEPTS\n\n`nemo_relay.intercepts.register_tool_execution` and its siblings are middleware\naround calls RELAY drives - `fn(context, next_call)`, where `next_call` continues\nRelay\'s own chain. This agent calls its NIMs over httpx and dispatches tools\nthrough a dict in Python, so a registered intercept would never once fire.\nRegistering them anyway would have produced a plausible-looking integration that\ncaptured nothing - which is exactly the class of fault this project keeps finding\nin its own work, so it is worth naming rather than quietly avoiding.\n\nThe manual span API does work outside Relay\'s runtime. Verified by writing a trace\nand reading it back before any of this was wired in:\n\n    nemo_relay.tools.call / call_end   ->  {"category": "tool", ...}\n    nemo_relay.llm.call   / call_end   ->  {"category": "llm",  ...}\n\nwith an `AtofExporter` writing ATOF 0.1, one JSON object per line.\n\nIT MUST NEVER BREAK AN ANSWER\n\nThis is observability. Every entry point swallows every exception, and the first\nfailure disables tracing for the rest of the process rather than raising into an\nanswer. `ASOIA_TRACE` is "off" by default, and then nemo_relay is never imported.\n"""\nfrom __future__ import annotations\nimport atexit\nimport os\nimport pathlib\nfrom contextlib import contextmanager\n\nDEFAULT_DIR = "run/traces"\n\n_state: dict = {"exporter": None, "name": None, "off": False,\n                "path": None, "why": None}\n\n\ndef mode() -> str:\n    """-> "off" | "file". Anything unrecognised is off, deliberately."""\n    m = (os.environ.get("ASOIA_TRACE") or "off").strip().lower()\n    return m if m in ("off", "file") else "off"\n\n\ndef enabled() -> bool:\n    return mode() != "off" and not _state["off"]\n\n\ndef path() -> str | None:\n    """Where this process is writing, once it has started."""\n    return _state["path"]\n\n\ndef why_off() -> str | None:\n    return _state["why"]\n\n\ndef _disable(why: str) -> None:\n    """One failure is enough. Keep the reason, stop trying."""\n    _state["off"] = True\n    _state["why"] = why\n\n\ndef _exporter():\n    """The process-wide exporter, registered once and flushed at exit."""\n    if _state["exporter"] is not None or _state["off"]:\n        return _state["exporter"]\n    try:\n        import nemo_relay as R\n        d = os.environ.get("ASOIA_TRACE_DIR") or DEFAULT_DIR\n        pathlib.Path(d).mkdir(parents=True, exist_ok=True)\n        cfg = R.AtofExporterConfig()\n        cfg.output_directory = d\n        cfg.filename = "atof-" + str(os.getpid()) + ".jsonl"\n        # One process, one file, appended. Overwrite would truncate the file under\n        # a reader that is tailing it, and the UI and the API are long-lived.\n        cfg.mode = R.AtofExporterMode.Append\n        exp = R.AtofExporter(cfg)\n        name = "asoia-" + str(os.getpid())\n        exp.register(name)\n        _state.update(exporter=exp, name=name,\n                      path=str(pathlib.Path(d) / cfg.filename))\n        atexit.register(shutdown)\n    except Exception as e:\n        _disable(type(e).__name__ + ": " + str(e)[:120])\n    return _state["exporter"]\n\n\ndef shutdown() -> None:\n    """Flush and release. Idempotent - atexit and a test may both call it."""\n    exp, name = _state["exporter"], _state["name"]\n    if exp is None:\n        return\n    _state["exporter"] = None\n    for step in (lambda: exp.force_flush(),\n                 lambda: exp.deregister(name),\n                 lambda: exp.shutdown()):\n        try:\n            step()\n        except Exception:\n            pass\n\n\ndef flush() -> None:\n    """Make what has been recorded readable without ending the process."""\n    exp = _state["exporter"]\n    if exp is not None:\n        try:\n            exp.force_flush()\n        except Exception:\n            pass\n\n\ndef _plain(v):\n    """Make a value JSON-safe for the Rust side, which will not coerce for us.\n\n    Anything unrepresentable becomes a string rather than an exception. A trace\n    that loses the shape of one field is worth having; a trace that raises inside\n    an answer is not.\n    """\n    if v is None or isinstance(v, (bool, int, float, str)):\n        return v\n    if isinstance(v, dict):\n        return {str(k): _plain(x) for k, x in v.items()}\n    if isinstance(v, (list, tuple)):\n        return [_plain(x) for x in v]\n    return str(v)\n\n\n@contextmanager\ndef tool_span(name: str, args: dict):\n    """Record one tool call. Yields a box; set box["result"] before leaving.\n\n    The result goes on the END event, so a tool that fails still produces a start\n    and an end - the end carries whatever the caller put in the box, which in this\n    project is the error dict the tool layer substitutes for an exception.\n    """\n    box: dict = {"result": None}\n    handle = None\n    # enabled() and _exporter() are INSIDE the try on purpose. They were in the\n    # `if` condition, which left two calls outside the guard, and a check that\n    # made _exporter() raise proved a tracer failure could reach the caller -\n    # the one thing this module promises cannot happen.\n    try:\n        if enabled():\n            exp = _exporter()\n            if exp is not None:\n                import nemo_relay.tools as T\n                # A ContextVar owns the scope stack per asyncio task and native\n                # code keeps a thread-local fallback, so this is re-synchronised\n                # before every span: the API is served by uvicorn, and without it\n                # spans from concurrent requests attach to the wrong parent.\n                T.ensure_scope_stack()\n                handle = T.call(name, _plain(args))\n    except Exception as e:\n        _disable(type(e).__name__ + ": " + str(e)[:120])\n        handle = None\n    try:\n        yield box\n    finally:\n        if handle is not None:\n            try:\n                import nemo_relay as R\n                import nemo_relay.tools as T\n                T.call_end(handle, R.ToolExecutionResult(_plain(box["result"])))\n            except Exception as e:\n                _disable(type(e).__name__ + ": " + str(e)[:120])\n\n\n@contextmanager\ndef llm_span(name: str, request: dict, model: str | None = None):\n    """Record one model call. Yields a box; set box["result"] before leaving."""\n    box: dict = {"result": None}\n    handle = None\n    try:\n        if enabled():\n            exp = _exporter()\n            if exp is not None:\n                import nemo_relay as R\n                import nemo_relay.llm as L\n                L.ensure_scope_stack()\n                handle = L.call(name, R.LLMRequest({}, _plain(request)),\n                                model_name=model)\n    except Exception as e:\n        _disable(type(e).__name__ + ": " + str(e)[:120])\n        handle = None\n    try:\n        yield box\n    finally:\n        if handle is not None:\n            try:\n                import nemo_relay.llm as L\n                L.call_end(handle, _plain(box["result"]))\n            except Exception as e:\n                _disable(type(e).__name__ + ": " + str(e)[:120])\n',
      'app/obs/trace.py  ATOF spans through Relay, off by default',
      skip_if='exp = _exporter()')

# ==================== 2. the only two places it belongs
edit('app/agent/tools.py',
     'def call(name: str, **kwargs) -> dict:\n    fn = TOOLS.get(name)\n    if not fn:\n        return {"error": f"unknown tool {name}", "available": list(TOOLS)}\n    try:\n        return fn(**kwargs)\n    except TypeError as e:\n        return {"error": f"bad arguments for {name}: {e}"}\n    except Exception as e:\n        return {"error": f"{name} failed: {type(e).__name__}: {str(e)[:200]}"}\n',
     'def call(name: str, **kwargs) -> dict:\n    fn = TOOLS.get(name)\n    if not fn:\n        return {"error": f"unknown tool {name}", "available": list(TOOLS)}\n    # Every tool the agent runs is dispatched here, so this is the one place a\n    # trace has to be taken. The error shapes below are untouched: callers and\n    # tests already match on them.\n    from app.obs import trace as _trace\n    with _trace.tool_span(name, kwargs) as _span:\n        try:\n            out = fn(**kwargs)\n        except TypeError as e:\n            out = {"error": f"bad arguments for {name}: {e}"}\n        except Exception as e:\n            out = {"error": f"{name} failed: {type(e).__name__}: {str(e)[:200]}"}\n        _span["result"] = out\n        return out\n',
     'tools.py  every tool dispatch is a span',
     skip_if='_trace.tool_span(')

edit('app/nim/client.py',
     'def chat(messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024,\n         json_mode: bool = False, stop: list[str] | None = None,\n         meta: dict | None = None) -> str:\n',
     'def chat(messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024,\n         json_mode: bool = False, stop: list[str] | None = None,\n         meta: dict | None = None) -> str:\n    """Complete a chat turn, and record it as a span. The work is in _chat_inner.\n\n    Split in two so that the span wraps the whole call including its retries, and\n    so that _chat_inner stays exactly what it was. `meta` is read AFTER the inner\n    call because that is when it has been filled in - finish_reason is the field\n    that says whether the text stops mid-sentence.\n    """\n    from app.obs import trace as _trace\n    _base, _model, _mode = resolve("llm")\n    with _trace.llm_span("chat", {"model": _model, "mode": _mode,\n                                  "messages": messages,\n                                  "temperature": temperature,\n                                  "max_tokens": max_tokens}, _model) as _span:\n        out = _chat_inner(messages, temperature, max_tokens, json_mode, stop, meta)\n        _span["result"] = {"content": out, "meta": _trace._plain(meta or {})}\n        return out\n\n\ndef _chat_inner(messages: list[dict], temperature: float = 0.0,\n                max_tokens: int = 1024, json_mode: bool = False,\n                stop: list[str] | None = None, meta: dict | None = None) -> str:\n',
     'client.py  every chat() is a span, body moved to _chat_inner',
     skip_if='def _chat_inner(')

# ==================== 3. declare what we now depend on, drop what is dead
edit('pyproject.toml',
     'nvidia = ["nemoguardrails>=0.11", "aiqtoolkit>=1.1",\n          "langchain-nvidia-ai-endpoints>=1.4"]\n',
     '# aiqtoolkit is a deprecated transitional shim whose own PyPI summary says it will\n# be removed; nvidia-nat is the package it forwards to, and it was ALREADY\n# installed here as aiqtoolkit\'s dependency. So this rename costs nothing to apply\n# and stops the project pinning a dead name.\nnvidia = ["nemoguardrails>=0.11", "nvidia-nat>=1.4",\n          "langchain-nvidia-ai-endpoints>=1.4"]\n# The flywheel. Relay records HOW each answer was produced (app/obs/trace.py);\n# Evaluator makes a run comparable with the run before it. Separate from `nvidia`\n# because the agent answers perfectly well without either.\nflywheel = ["nemo-relay>=0.9", "nemo-evaluator>=0.2"]\n',
     'pyproject.toml  nvidia-nat replaces deprecated aiqtoolkit; flywheel extra',
     skip_if='flywheel = [')

# ==================== 4. prove the trace describes the real execution
write('scripts/test_trace.py', '#!/usr/bin/env python3\n"""Does a real answer leave a usable trace?\n\n    .venv/bin/python scripts/test_trace.py\n\nAsserts what a flywheel needs, and one thing it must NOT do:\n\n  a deterministic question  -> TOOL spans, and no LLM span at all\n  a narrated question       -> both\n  every start has an end    -> counts and names agree per category\n  the traced tool names     -> are the tools the answer actually recorded using\n  ASOIA_TRACE unset         -> nothing is written, in a separate process\n\nThat last one matters as much as the rest. Tracing that cannot be turned off is a\nliability, and a default that writes to disk on every answer is one too.\n\nThe deterministic case is the interesting half. Five of this project\'s six question\nclasses make no model call, so a trace that shows an LLM span there would mean the\nagent had quietly started asking a model to do arithmetic Python was doing.\n"""\nfrom __future__ import annotations\nimport json\nimport os\nimport pathlib\nimport subprocess\nimport sys\nimport tempfile\n\nsys.path.insert(0, ".")\nimport _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py\n\nDETERMINISTIC = "which repair orders are blocked"\nNARRATED = "has anyone seen a whistling noise on a Passat"\n\nbad = 0\n\n\ndef chk(name, ok, detail=""):\n    global bad\n    bad += (not ok)\n    print(f"  {\'ok     \' if ok else \'FAILED \'} {name}" + (f"  ({detail})" if detail else ""))\n\n\ndef read(p: str) -> list[dict]:\n    out = []\n    f = pathlib.Path(p)\n    if not f.exists():\n        return out\n    for line in f.read_text().splitlines():\n        line = line.strip()\n        if line:\n            try:\n                out.append(json.loads(line))\n            except Exception:\n                pass\n    return out\n\n\ndef spans(recs, category):\n    starts = [r for r in recs if r.get("category") == category\n              and r.get("scope_category") == "start"]\n    ends = [r for r in recs if r.get("category") == category\n            and r.get("scope_category") == "end"]\n    return starts, ends\n\n\ndef main() -> int:\n    d = tempfile.mkdtemp(prefix="asoia-trace-")\n    os.environ["ASOIA_TRACE"] = "file"\n    os.environ["ASOIA_TRACE_DIR"] = d\n\n    from app.obs import trace\n    from app.agent.agent import ask\n\n    print("tracing:", trace.mode(), "->", d)\n\n    print("\\na deterministic question (no model call expected):")\n    a1 = ask(DETERMINISTIC)\n    trace.flush()\n    p = trace.path()\n    chk("a trace file was created", bool(p) and pathlib.Path(p).exists(), str(p))\n    if not p or not pathlib.Path(p).exists():\n        print("\\nnothing to check against. Is nemo-relay installed?",\n              trace.why_off() or "")\n        return 1\n    recs = read(p)\n    ts, te = spans(recs, "tool")\n    ls, le = spans(recs, "llm")\n    chk("tool spans were recorded", len(ts) > 0, f"{len(ts)} start(s)")\n    chk("every tool start has an end", len(ts) == len(te), f"{len(ts)} vs {len(te)}")\n    chk("no model was called on this path", len(ls) == 0,\n        f"{len(ls)} llm span(s); composed={getattr(a1, \'composed\', \'?\')}")\n    # The trace must agree with what the answer itself says it did. If these drift,\n    # the trace is describing a different execution from the one that answered.\n    traced = sorted({r.get("name") for r in ts})\n    claimed = sorted({c.get("name") for c in (a1.tool_calls or []) if c.get("name")})\n    chk("traced tools match the answer\'s own tool_calls",\n        traced == claimed, f"traced={traced} claimed={claimed}")\n\n    print("\\na narrated question (the model composes):")\n    before = len(recs)\n    a2 = ask(NARRATED)\n    trace.flush()\n    recs2 = read(p)\n    chk("more spans were appended", len(recs2) > before, f"{before} -> {len(recs2)}")\n    ls2, le2 = spans(recs2, "llm")\n    if getattr(a2, "composed", "") == "python":\n        print("         note: this answer fell back to Python composition, so no")\n        print("         LLM span is expected. The NIMs are probably down.")\n    else:\n        chk("an llm span was recorded", len(ls2) > 0, f"{len(ls2)}")\n        chk("every llm start has an end", len(ls2) == len(le2), f"{len(ls2)} vs {len(le2)}")\n        models = sorted({r.get("name") for r in ls2})\n        chk("the llm span is named", all(models), str(models))\n\n    print("\\nthe payload is actually in there, not just the shape:")\n    any_args = [r for r in ts if r.get("data")]\n    chk("tool starts carry their arguments", len(any_args) > 0,\n        str(any_args[0].get("data"))[:70] if any_args else "none")\n    any_res = [r for r in te if r.get("data") is not None]\n    chk("tool ends carry a result", len(any_res) > 0,\n        str(any_res[0].get("data"))[:70] if any_res else "none")\n    chk("records are ATOF", all(r.get("atof_version") for r in recs2))\n\n    print("\\nand with ASOIA_TRACE unset, in a clean process:")\n    d2 = tempfile.mkdtemp(prefix="asoia-notrace-")\n    env = {k: v for k, v in os.environ.items() if k != "ASOIA_TRACE"}\n    env["ASOIA_TRACE_DIR"] = d2\n    r = subprocess.run(\n        [sys.executable, "-c",\n         "import sys; sys.path.insert(0, \'.\');"\n         "from app.agent.agent import ask;"\n         "a = ask(\'which repair orders are blocked\');"\n         "print(\'answered\', bool(a.text))"],\n        capture_output=True, text=True, timeout=600, env=env)\n    wrote = sorted(x.name for x in pathlib.Path(d2).iterdir())\n    chk("the answer still worked", r.returncode == 0,\n        (r.stdout or r.stderr or "")[-120:].replace("\\n", " "))\n    chk("nothing was written", wrote == [], str(wrote))\n\n    print()\n    if bad:\n        print(f"{bad} assertion(s) FAILED.")\n    else:\n        print("The trace describes the execution that produced the answer.")\n    print("\\n  trace: " + str(p))\n    return 1 if bad else 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
      'scripts/test_trace.py  the trace must agree with the answer',
      skip_if='traced tools match')

# ==================== 5. the record
_p37 = [l for l in (ROOT / 'patches/README.md').read_text().splitlines(True)
        if l.startswith('| `quality_pass37.py` |')]
if _p37:
    edit('patches/README.md', _p37[0], _p37[0] + '| `quality_pass38.py` | the agent recorded what it answered and never how; ATOF traces of every tool and model call, and the Relay API that looks right for this and would have captured nothing |\n',
         'patches/README.md  pass 38 row', skip_if='| `quality_pass38.py` |')

append('ENGINEERING.md', '\n\n## 27. Recording how an answer was produced, not just what it was\n\n`answer_log` has 345 rows: question, answer, route, composed, grounded, tools,\ncitations, seconds. It is a record of *outcomes*. Nothing recorded the *execution* -\nwhich tool ran first, what it was given, what it returned, what the model was\nhanded - and a loop that is supposed to improve from its own results needs that,\nbecause the outcome alone does not say which step to change.\n\n`app/obs/trace.py` emits ATOF 0.1 through NeMo Relay: one JSON object per line, a\nstart and an end event per span, with parent and propagation uuids so a nested call\nkeeps its place.\n\n```json\n{"atof_version":"0.1","category":"tool","name":"get_ro_state",\n "scope_category":"start","data":{"ro_number":"RO-26-08165"},...}\n{"atof_version":"0.1","category":"tool","name":"get_ro_state",\n "scope_category":"end","data":{"status":"blocked",...},...}\n```\n\n### The obvious integration would have captured nothing\n\nRelay\'s documented surface for this is `intercepts`:\n\n```python\nregister_tool_execution(name, priority, fn)   # fn(context, next_call)\nregister_llm_request(name, priority, break_chain, fn)\n```\n\nMiddleware. `next_call` continues **Relay\'s** chain, which means these fire for\ncalls Relay drives. This agent calls its NIMs over httpx and dispatches tools\nthrough a dict in Python. Registering those intercepts would have produced an\nintegration that imported cleanly, logged nothing, and looked finished - the exact\nshape of pass 35\'s rails that had never loaded and pass 34\'s ASR that had never\nserved a request.\n\nThe manual span API does work outside Relay\'s runtime, and that was established by\nwriting a trace and reading it back *before* anything was wired in:\n`nemo_relay.tools.call/call_end`, `nemo_relay.llm.call/call_end`, around an\n`AtofExporter`. Three API facts only a real attempt would have found: the mode is\nan `AtofExporterMode` enum and not the string the config field suggests,\n`deregister()` wants the subscriber name back, and `llm.call` wants a real\n`LLMRequest(headers, content)` rather than a dict.\n\n### Two places, because there are only two\n\n`tools.call()` dispatches every tool the agent runs. `client.chat()` is every\nnon-streaming model call. So the whole integration is two spans, and the error\nshapes in the tool layer are byte-for-byte what they were, because tests and\ncallers match on them.\n\n`chat_stream()` is deliberately not traced: it is a generator whose span would have\nto stay open across the consumer\'s iteration, and a half-written span on an\nabandoned stream is worse than no span.\n\n### Off by default, and a failure disables it\n\n`ASOIA_TRACE` is `off` unless set to `file`, and anything else - `on`, `yes`, `1` -\nis also off, because a tracing flag that guesses is a tracing flag that surprises.\nWhen off, `nemo_relay` is never imported.\n\nEvery entry point swallows every exception and the first failure turns tracing off\nfor the rest of the process. That is tested by making the exporter raise and\nasserting the caller sees nothing. An answer must never fail because its\nobservability did, and the only way to know that is to break the observability on\npurpose.\n\nThe test also asserts the trace agrees with the answer: the tool names in the\nspans must equal `Answer.tool_calls`. If those drift, the trace is describing a\ndifferent execution from the one that answered, which is worse than no trace.\n\nAnd the deterministic case asserts **no LLM span at all**. Five of the six question\nclasses make no model call, so an llm span appearing there would mean the agent had\nstarted asking a model to do arithmetic that Python was already doing.\n',
       'ENGINEERING.md  section 27',
       skip_if='## 27. Recording how an answer was produced')

# ==================== verify
print("Quality pass 38:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}"
          + (f"  ({detail})" if detail else ""))


import os, subprocess, tempfile, importlib

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import _env  # noqa: E402,F401

print("\nthe files:")
tr_src = (ROOT / "app/obs/trace.py").read_text()
to_src = (ROOT / "app/agent/tools.py").read_text()
cl_src = (ROOT / "app/nim/client.py").read_text()
tt_src = (ROOT / "scripts/test_trace.py").read_text()
tr_t, to_t, cl_t, tt_t = (ast.parse(s) for s in (tr_src, to_src, cl_src, tt_src))
chk("all four parse", True)

from app.obs import trace

print("\noff is the default, and off means off:")
for val, want in ((None, "off"), ("", "off"), ("file", "file"),
                  ("FILE", "file"), ("yes", "off"), ("on", "off")):
    if val is None:
        os.environ.pop("ASOIA_TRACE", None)
    else:
        os.environ["ASOIA_TRACE"] = val
    got = trace.mode()
    chk(f"ASOIA_TRACE={val!r} -> {got}", got == want, f"wanted {want}")
os.environ.pop("ASOIA_TRACE", None)
chk("enabled() is False when off", trace.enabled() is False)

print("\nwhen off, nothing is created at all:")
_d = tempfile.mkdtemp(prefix="asoia-off-")
os.environ["ASOIA_TRACE_DIR"] = _d
with trace.tool_span("probe", {"a": 1}) as _b:
    _b["result"] = {"ok": True}
chk("no exporter was built", trace._state["exporter"] is None)
chk("no file was written", sorted(os.listdir(_d)) == [], str(os.listdir(_d)))

print("\na failure in the tracer must not reach the caller:")
_saved = dict(trace._state)
_real = trace._exporter
try:
    os.environ["ASOIA_TRACE"] = "file"

    def _boom():
        raise RuntimeError("exporter is broken")

    trace._exporter = _boom
    _raised = None
    try:
        with trace.tool_span("probe", {"a": 1}) as _b:
            _b["result"] = {"ok": True}
    except Exception as e:
        _raised = e
    chk("tool_span swallowed it", _raised is None,
        type(_raised).__name__ if _raised else "")
    chk("and tracing turned itself off", trace._state["off"] is True,
        str(trace.why_off())[:50])
finally:
    trace._exporter = _real
    trace._state.clear()
    trace._state.update(_saved)
    os.environ.pop("ASOIA_TRACE", None)

print("\n_plain() makes values safe rather than raising:")


class _Odd:
    def __repr__(self):
        return "<odd>"


_p = trace._plain({"n": 1, "s": "x", "l": [1, _Odd()], "o": _Odd(), "none": None})
chk("scalars survive", _p["n"] == 1 and _p["s"] == "x" and _p["none"] is None)
chk("nesting survives", isinstance(_p["l"], list) and _p["l"][0] == 1)
chk("the unrepresentable becomes a string", _p["o"] == "<odd>" and _p["l"][1] == "<odd>")
import json as _json
_json.dumps(_p)
chk("the result is JSON-serialisable", True)

print("\nthe wiring, by syntax and not by comment:")
_fns = {n.name: n for n in ast.walk(to_t) if isinstance(n, ast.FunctionDef)}
_call = _fns.get("call")
chk("tools.call exists", _call is not None)
_withs = [n for n in ast.walk(_call) if isinstance(n, ast.With)] if _call else []
chk("tools.call takes a span",
    any(isinstance(it.context_expr, ast.Call)
        and getattr(it.context_expr.func, "attr", "") == "tool_span"
        for w in _withs for it in w.items))
_cfns = {n.name: n for n in ast.walk(cl_t) if isinstance(n, ast.FunctionDef)}
chk("the original chat body is now _chat_inner", "_chat_inner" in _cfns)
_chat = _cfns.get("chat")
chk("chat() calls _chat_inner",
    _chat is not None and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_chat_inner"
                              for n in ast.walk(_chat)))
chk("chat() takes a span",
    _chat is not None and any(isinstance(it.context_expr, ast.Call)
                              and getattr(it.context_expr.func, "attr", "") == "llm_span"
                              for n in ast.walk(_chat) if isinstance(n, ast.With)
                              for it in n.items))

print("\nthe tool layer's contract is unchanged:")
from app.agent import tools as TL
_u = TL.call("no_such_tool")
chk("an unknown tool still reports itself", "unknown tool" in _u.get("error", ""))
chk("and still lists what is available", isinstance(_u.get("available"), list))
_b2 = TL.call("get_ro_state", not_a_real_argument=1)
chk("bad arguments still report themselves", "bad arguments" in _b2.get("error", ""))

print("\nthe deprecated dependency is gone:")
# Parsed, not grepped. `"aiqtoolkit" not in pyproject.toml` failed on the comment
# that EXPLAINS the removal - the seventh time in this project that a check has
# asserted the prose beside the code instead of the code (29, 30, 31, 33, 34, 35,
# here). The rule keeps earning itself: match syntax, never vocabulary.
import tomllib
_opt = (tomllib.loads((ROOT / "pyproject.toml").read_text())
        .get("project", {}).get("optional-dependencies", {}))
_nv = _opt.get("nvidia", [])


def _names(deps):
    import re as _re
    return {_re.split(r"[<>=!~\[]", d, 1)[0].strip() for d in deps}


chk("aiqtoolkit is not a dependency", "aiqtoolkit" not in _names(_nv), str(_nv))
chk("nvidia-nat is", "nvidia-nat" in _names(_nv))
chk("the flywheel extra declares both",
    {"nemo-relay", "nemo-evaluator"} <= _names(_opt.get("flywheel", [])),
    str(_opt.get("flywheel")))

print("\nend to end:")
_r = subprocess.run([sys.executable, "scripts/test_trace.py"],
                    capture_output=True, text=True, timeout=1200)
chk("scripts/test_trace.py passes", _r.returncode == 0,
    f"rc={_r.returncode}: " + (_r.stdout or "")[-300:].replace("\n", " | "))

print("\nthe regression suite:")
_t = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                    capture_output=True, text=True, timeout=1800)
chk("unit tests pass", _t.returncode == 0,
    (_t.stdout or "").strip().splitlines()[-1] if (_t.stdout or "").strip() else "")
_v = subprocess.run([sys.executable, "scripts/verify_answers.py"],
                    capture_output=True, text=True, timeout=1800)
chk("the answer checks pass", _v.returncode == 0,
    (_v.stdout or "").strip().splitlines()[-1] if (_v.stdout or "").strip() else "")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    ASOIA_TRACE=file bash scripts/stack.sh restart    <- trace the live stack
    .venv/bin/python scripts/test_trace.py
""")
sys.exit(1 if bad else 0)

