"""Route each model call through a NeMo Switchyard proxy. Off by default.

WHAT THIS IS FOR

The project has capture (app/obs/trace.py) and a yardstick (scripts/eval_standard.py).
Neither changes what the agent does. Switchyard is the part whose behaviour can
change in response to a score: a policy that decides, per request, which model
serves it - and whose best decision here is usually that no model is needed at all,
because five of six question classes are composed in Python from tool results.

HOW IT ATTACHES

`switchyard_rust.server.Server(config, port)` is a loopback OpenAI-compatible
proxy. With it running, `resolve("llm")` hands back the proxy's base url and the
ROUTE id in place of a model id, so `chat()` is unchanged and every model call goes
through the router. The route then picks a target and proxies on.

The library path - `switchyard.libsy.algorithms.stage_router` driven by
`run_stream` - was tried first and abandoned for a specific reason worth recording:
`run_stream` raises `target "..." was not found` because targets live in a
deployment config that only the server reads. There is no target registry in the
Python API. The proxy is not the lazy option, it is the supported one.

WHEN IT FAILS, THE AGENT STILL ANSWERS

Every path here returns None rather than raising, and the first failure disables
routing for the rest of the process. `resolve("llm")` then falls through to the
direct NIM exactly as before. A router that can take the agent down with it is
worse than no router.
"""
from __future__ import annotations
import atexit
import os
import pathlib

CONFIG = "configs/switchyard.toml"
DEFAULT_ROUTE = "asoia"

_state: dict = {"server": None, "base": None, "off": False, "why": None}


def mode() -> str:
    """-> "off" | "on". Anything unrecognised is off, as with ASOIA_TRACE."""
    m = (os.environ.get("ASOIA_SWITCHYARD") or "off").strip().lower()
    return m if m in ("off", "on") else "off"


def route() -> str:
    return (os.environ.get("ASOIA_SWITCHYARD_ROUTE") or DEFAULT_ROUTE).strip()


def config_path() -> str:
    return os.environ.get("ASOIA_SWITCHYARD_CONFIG") or CONFIG


def enabled() -> bool:
    return mode() == "on" and not _state["off"]


def why_off() -> str | None:
    return _state["why"]


def _disable(why: str) -> None:
    _state["off"] = True
    _state["why"] = why


def base_url() -> str | None:
    """Start the proxy if needed and return its base url, or None."""
    if _state["base"] is not None or _state["off"]:
        return _state["base"]
    if not enabled():
        return None
    try:
        from switchyard_rust.server import Server
        cfg = config_path()
        if not pathlib.Path(cfg).exists():
            _disable(f"config not found: {cfg}")
            return None
        # Port 0: the OS picks one. The API and the UI are separate processes and
        # each gets its own proxy, which is fine - a router is stateless.
        srv = Server(cfg, 0)
        _state["server"] = srv
        _state["base"] = srv.base_url.rstrip("/")
        atexit.register(shutdown)
    except Exception as e:
        _disable(type(e).__name__ + ": " + str(e)[:200])
        return None
    return _state["base"]


def endpoint() -> tuple[str, str] | None:
    """-> (base_url_with_v1, route_id) for resolve(), or None to use the NIM direct."""
    b = base_url()
    if not b:
        return None
    return (b + "/v1", route())


def shutdown() -> None:
    """Drain and stop. Idempotent - atexit and a test may both call it."""
    srv = _state["server"]
    if srv is None:
        return
    _state["server"] = None
    _state["base"] = None
    try:
        srv.close()
    except Exception:
        pass


def status() -> dict:
    """For scripts/stack.sh and the eval provenance."""
    return {"mode": mode(), "route": route(), "config": config_path(),
            "base_url": _state["base"], "off": _state["off"],
            "why": _state["why"]}
