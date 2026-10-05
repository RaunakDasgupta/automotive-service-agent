"""Metrics for the parts of this system that can quietly go wrong.

Instrumented against the failure modes this project actually had, not against a
generic template. Each series exists because something it would have caught got
shipped:

  compose path        a renderer silently degrading to the model is invisible in
                      the answer itself - pass 8 added the note, this counts it
  llm calls           the headline claim is that structured questions make ZERO
                      model calls; that claim should be a graph, not a sentence
  grounding warnings  the rail firing at all means a renderer derived a figure
  rail blocks         a correct answer the rail blocks is still a failed answer
  truncation          pass 14 surfaced it; this counts how often it happens
  NIM latency         2.5s of the 2.6s search path is generation - watch it move

Degrades to no-ops when prometheus_client is absent, so nothing here can break
the app, and no call site needs a try/except.
"""
from __future__ import annotations
import os
import time
from contextlib import contextmanager

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    ENABLED = True
except ImportError:                                   # pragma: no cover
    ENABLED = False

    class _Noop:
        def labels(self, *a, **k): return self
        def inc(self, *a, **k): pass
        def observe(self, *a, **k): pass
        def set(self, *a, **k): pass

    def Counter(*a, **k): return _Noop()        # type: ignore[misc]
    def Gauge(*a, **k): return _Noop()          # type: ignore[misc]
    def Histogram(*a, **k): return _Noop()      # type: ignore[misc]
    def start_http_server(*a, **k): pass        # type: ignore[misc]


# Buckets chosen from the measured reality: deterministic answers land at
# 2-60ms, the one model path at ~2.6s. Default buckets would put every
# deterministic answer in a single bin and tell you nothing.
_FAST = (0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

ANSWERS = Counter("asoia_answers_total",
                  "Answers produced, by how they were composed and routed.",
                  ["compose", "route", "grounded"])
ANSWER_SECONDS = Histogram("asoia_answer_seconds",
                           "End-to-end time to answer a question.",
                           ["compose"], buckets=_FAST)
TOOL_CALLS = Counter("asoia_tool_calls_total",
                     "Tool invocations, by tool.", ["tool"])
LLM_CALLS = Counter("asoia_llm_calls_total",
                    "Calls to the language model, by why it was called.",
                    ["purpose"])
FALLBACKS = Counter("asoia_compose_fallbacks_total",
                    "Times Python composition gave way to the model.", ["reason"])
GROUNDING = Counter("asoia_grounding_warnings_total",
                    "Grounding warnings raised on a composed answer.", ["kind"])
RAIL_BLOCKS = Counter("asoia_rail_blocks_total",
                      "Answers or questions stopped by a guardrail.", ["rail"])
TRUNCATED = Counter("asoia_answers_truncated_total",
                    "Narrations that hit max_tokens and were cut short.")
NIM_SECONDS = Histogram("asoia_nim_seconds",
                        "Time spent in a NIM call, by service.",
                        ["service"], buckets=_FAST)
NIM_ERRORS = Counter("asoia_nim_errors_total",
                     "Failed NIM calls, by service and cause.",
                     ["service", "cause"])
RAIL_SHADOW = Counter("asoia_rail_shadow_total",
                      "Shadow comparison between the colang rails and the "
                      "hand-written patterns. `nemo_only_block` is the "
                      "interesting one: a case the patterns let through.",
                      ["agreement"])
UPDATES = Counter("asoia_updates_total",
                  "Technician updates through the ingestion pipeline.",
                  ["outcome"])
UP = Gauge("asoia_build_info", "1 when the app is running.", ["component"])


def _service_of(url: str) -> str:
    """Which NIM a URL belongs to, for labelling. Ports match start_nims.sh."""
    u = str(url)
    if "/ranking" in u or ":8002" in u:
        return "rerank"
    if "/embeddings" in u or ":8001" in u:
        return "embed"
    if "/chat/completions" in u or ":8000" in u:
        return "llm"
    if "speech" in u or "asr" in u:
        return "asr"
    return "other"


@contextmanager
def nim_call(url: str):
    """Time one NIM call and record how it ended."""
    svc = _service_of(url)
    t = time.perf_counter()
    try:
        yield
    except Exception as e:
        NIM_ERRORS.labels(service=svc, cause=type(e).__name__).inc()
        raise
    finally:
        NIM_SECONDS.labels(service=svc).observe(time.perf_counter() - t)


def record_answer(ans, seconds: float) -> None:
    """Record one answered question. Never raises - it is only telemetry."""
    try:
        compose = getattr(ans, "composed", "?") or "?"
        route = getattr(ans, "route", "?") or "?"
        warnings = list(getattr(ans, "warnings", None) or [])
        ANSWERS.labels(compose=compose, route=route,
                       grounded=str(not warnings).lower()).inc()
        ANSWER_SECONDS.labels(compose=compose).observe(seconds)
        for call in getattr(ans, "tool_calls", None) or []:
            TOOL_CALLS.labels(tool=str(call.get("name", "?"))).inc()
        if compose == "llm":
            LLM_CALLS.labels(purpose="narration").inc()
        if route == "llm":
            LLM_CALLS.labels(purpose="routing").inc()
        for note in getattr(ans, "compose_notes", None) or []:
            if "cut short" in note:
                TRUNCATED.inc()
            else:
                # Bucket by kind, not by the whole message: the RO number in
                # "renderer for diff_ro raised KeyError: RO-26-08192" would make
                # a new time series per repair order.
                FALLBACKS.labels(reason=str(note).split(":")[0][:60]).inc()
        for w in warnings:
            GROUNDING.labels(kind=str(w).split(" ")[0][:40]).inc()
    except Exception:
        pass


def record_rail(result) -> None:
    try:
        if not getattr(result, "allowed", True):
            RAIL_BLOCKS.labels(rail=str(getattr(result, "rail", "?"))).inc()
    except Exception:
        pass


def record_update(outcome: str) -> None:
    try:
        UPDATES.labels(outcome=str(outcome)).inc()
    except Exception:
        pass


_started = False


def serve(port: int | None = None) -> int | None:
    """Expose /metrics. Returns the port, or None if metrics are unavailable.

    Idempotent, and never fatal: a demo must not fail to start because a metrics
    port is busy.
    """
    global _started
    if not ENABLED or _started or os.environ.get("ASOIA_METRICS", "1") != "1":
        return None
    p = int(port or os.environ.get("ASOIA_METRICS_PORT", "9400"))
    try:
        start_http_server(p)
        UP.labels(component="app").set(1)
        _started = True
        print(f"[metrics] serving on :{p}/metrics")
        return p
    except Exception as e:
        print(f"[metrics] not started ({type(e).__name__}: {e})")
        return None
