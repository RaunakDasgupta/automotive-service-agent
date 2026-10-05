"""ATOF traces of every tool and model call, through NeMo Relay. Off by default.

WHY THIS EXISTS

`answer_log` records WHAT was answered and whether it was grounded. It does not
record HOW the answer was produced: which tools ran, in what order, what each was
given and what it returned, what the model was handed. A loop meant to learn from
its own results needs the second thing, and nothing in this project captured it.

WHY NOT RELAY'S INTERCEPTS

`nemo_relay.intercepts.register_tool_execution` and its siblings are middleware
around calls RELAY drives - `fn(context, next_call)`, where `next_call` continues
Relay's own chain. This agent calls its NIMs over httpx and dispatches tools
through a dict in Python, so a registered intercept would never once fire.
Registering them anyway would have produced a plausible-looking integration that
captured nothing - which is exactly the class of fault this project keeps finding
in its own work, so it is worth naming rather than quietly avoiding.

The manual span API does work outside Relay's runtime. Verified by writing a trace
and reading it back before any of this was wired in:

    nemo_relay.tools.call / call_end   ->  {"category": "tool", ...}
    nemo_relay.llm.call   / call_end   ->  {"category": "llm",  ...}

with an `AtofExporter` writing ATOF 0.1, one JSON object per line.

IT MUST NEVER BREAK AN ANSWER

This is observability. Every entry point swallows every exception, and the first
failure disables tracing for the rest of the process rather than raising into an
answer. `ASOIA_TRACE` is "off" by default, and then nemo_relay is never imported.
"""
from __future__ import annotations
import atexit
import os
import pathlib
from contextlib import contextmanager

DEFAULT_DIR = "run/traces"

_state: dict = {"exporter": None, "name": None, "off": False,
                "path": None, "why": None}


def mode() -> str:
    """-> "off" | "file". Anything unrecognised is off, deliberately."""
    m = (os.environ.get("ASOIA_TRACE") or "off").strip().lower()
    return m if m in ("off", "file") else "off"


def enabled() -> bool:
    return mode() != "off" and not _state["off"]


def path() -> str | None:
    """Where this process is writing, once it has started."""
    return _state["path"]


def why_off() -> str | None:
    return _state["why"]


def _disable(why: str) -> None:
    """One failure is enough. Keep the reason, stop trying."""
    _state["off"] = True
    _state["why"] = why


def _exporter():
    """The process-wide exporter, registered once and flushed at exit."""
    if _state["exporter"] is not None or _state["off"]:
        return _state["exporter"]
    try:
        import nemo_relay as R
        d = os.environ.get("ASOIA_TRACE_DIR") or DEFAULT_DIR
        pathlib.Path(d).mkdir(parents=True, exist_ok=True)
        cfg = R.AtofExporterConfig()
        cfg.output_directory = d
        cfg.filename = "atof-" + str(os.getpid()) + ".jsonl"
        # One process, one file, appended. Overwrite would truncate the file under
        # a reader that is tailing it, and the UI and the API are long-lived.
        cfg.mode = R.AtofExporterMode.Append
        exp = R.AtofExporter(cfg)
        name = "asoia-" + str(os.getpid())
        exp.register(name)
        _state.update(exporter=exp, name=name,
                      path=str(pathlib.Path(d) / cfg.filename))
        atexit.register(shutdown)
    except Exception as e:
        _disable(type(e).__name__ + ": " + str(e)[:120])
    return _state["exporter"]


def shutdown() -> None:
    """Flush and release. Idempotent - atexit and a test may both call it."""
    exp, name = _state["exporter"], _state["name"]
    if exp is None:
        return
    _state["exporter"] = None
    for step in (lambda: exp.force_flush(),
                 lambda: exp.deregister(name),
                 lambda: exp.shutdown()):
        try:
            step()
        except Exception:
            pass


def flush() -> None:
    """Make what has been recorded readable without ending the process."""
    exp = _state["exporter"]
    if exp is not None:
        try:
            exp.force_flush()
        except Exception:
            pass


def _plain(v):
    """Make a value JSON-safe for the Rust side, which will not coerce for us.

    Anything unrepresentable becomes a string rather than an exception. A trace
    that loses the shape of one field is worth having; a trace that raises inside
    an answer is not.
    """
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return str(v)


@contextmanager
def tool_span(name: str, args: dict):
    """Record one tool call. Yields a box; set box["result"] before leaving.

    The result goes on the END event, so a tool that fails still produces a start
    and an end - the end carries whatever the caller put in the box, which in this
    project is the error dict the tool layer substitutes for an exception.
    """
    box: dict = {"result": None}
    handle = None
    # enabled() and _exporter() are INSIDE the try on purpose. They were in the
    # `if` condition, which left two calls outside the guard, and a check that
    # made _exporter() raise proved a tracer failure could reach the caller -
    # the one thing this module promises cannot happen.
    try:
        if enabled():
            exp = _exporter()
            if exp is not None:
                import nemo_relay.tools as T
                # A ContextVar owns the scope stack per asyncio task and native
                # code keeps a thread-local fallback, so this is re-synchronised
                # before every span: the API is served by uvicorn, and without it
                # spans from concurrent requests attach to the wrong parent.
                T.ensure_scope_stack()
                handle = T.call(name, _plain(args))
    except Exception as e:
        _disable(type(e).__name__ + ": " + str(e)[:120])
        handle = None
    try:
        yield box
    finally:
        if handle is not None:
            try:
                import nemo_relay as R
                import nemo_relay.tools as T
                T.call_end(handle, R.ToolExecutionResult(_plain(box["result"])))
            except Exception as e:
                _disable(type(e).__name__ + ": " + str(e)[:120])


@contextmanager
def llm_span(name: str, request: dict, model: str | None = None):
    """Record one model call. Yields a box; set box["result"] before leaving."""
    box: dict = {"result": None}
    handle = None
    try:
        if enabled():
            exp = _exporter()
            if exp is not None:
                import nemo_relay as R
                import nemo_relay.llm as L
                L.ensure_scope_stack()
                handle = L.call(name, R.LLMRequest({}, _plain(request)),
                                model_name=model)
    except Exception as e:
        _disable(type(e).__name__ + ": " + str(e)[:120])
        handle = None
    try:
        yield box
    finally:
        if handle is not None:
            try:
                import nemo_relay.llm as L
                L.call_end(handle, _plain(box["result"]))
            except Exception as e:
                _disable(type(e).__name__ + ": " + str(e)[:120])
