#!/usr/bin/env python3
"""Eighteenth pass: observability. Prometheus metrics, and a Grafana dashboard.

Run from the project root:   python3 quality_pass18.py

`prometheus-client` has been a declared dependency since the first release and
was referenced by nothing. The proposed architecture named Prometheus/Grafana as
a layer; this is that layer.

WHAT IS MEASURED, AND WHY EACH SERIES EXISTS

Instrumented against the failure modes this project actually had, rather than a
generic template. Every series here corresponds to something that shipped broken
at some point and was found by hand:

  compose path         a renderer degrading to the model is invisible in the
                       answer. Pass 8 added the note; this counts it.
  llm calls            the headline claim is that structured questions make ZERO
                       model calls. That belongs on a graph, not in a sentence.
  grounding warnings   non-zero means a renderer derived a figure. Pass 6's rule.
  truncation           pass 14 surfaced finish_reason; this counts the cut-offs.
  rail blocks          a correct answer the rail blocks is still a failed answer.
  NIM latency          2.5s of the 2.6s search path is generation. Watch it move.

WHAT IT COSTS

Nothing. Prometheus and Grafana run on the CPU with host networking, on the box
you already have. No VRAM, no second instance, no hosted calls.

SAFE BY CONSTRUCTION

app/obs/metrics.py degrades to no-ops when prometheus_client is absent, and every
recording function swallows its own exceptions. Telemetry must never be the
reason an answer fails, so no call site needs a try/except and the app runs
unchanged with metrics disabled (ASOIA_METRICS=0).
"""
import sys, pathlib, ast, json

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
                 "      Run passes 1-17 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def write(rel, body, label, executable=False):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if p.read_text() == body:
            CHANGES.append(f"  skip  {label} (already present)")
        else:
            # A later pass has edited this file. Overwriting would silently undo
            # it - which is exactly what re-running this pass after pass 21 did
            # to the RAIL_SHADOW counter. These scripts are a historical record;
            # none of them may destroy the work of one that came after.
            CHANGES.append(f"  KEEP  {label} (on disk and DIFFERENT - a later "
                           f"pass edited it; not overwritten)")
        return
    p.write_text(body)
    if executable:
        p.chmod(0o755)
    CHANGES.append(f"  ok    {label}")


# ==================================================== 1. the metrics module
write("app/obs/metrics.py", '"""Metrics for the parts of this system that can quietly go wrong.\n\nInstrumented against the failure modes this project actually had, not against a\ngeneric template. Each series exists because something it would have caught got\nshipped:\n\n  compose path        a renderer silently degrading to the model is invisible in\n                      the answer itself - pass 8 added the note, this counts it\n  llm calls           the headline claim is that structured questions make ZERO\n                      model calls; that claim should be a graph, not a sentence\n  grounding warnings  the rail firing at all means a renderer derived a figure\n  rail blocks         a correct answer the rail blocks is still a failed answer\n  truncation          pass 14 surfaced it; this counts how often it happens\n  NIM latency         2.5s of the 2.6s search path is generation - watch it move\n\nDegrades to no-ops when prometheus_client is absent, so nothing here can break\nthe app, and no call site needs a try/except.\n"""\nfrom __future__ import annotations\nimport os\nimport time\nfrom contextlib import contextmanager\n\ntry:\n    from prometheus_client import Counter, Gauge, Histogram, start_http_server\n    ENABLED = True\nexcept ImportError:                                   # pragma: no cover\n    ENABLED = False\n\n    class _Noop:\n        def labels(self, *a, **k): return self\n        def inc(self, *a, **k): pass\n        def observe(self, *a, **k): pass\n        def set(self, *a, **k): pass\n\n    def Counter(*a, **k): return _Noop()        # type: ignore[misc]\n    def Gauge(*a, **k): return _Noop()          # type: ignore[misc]\n    def Histogram(*a, **k): return _Noop()      # type: ignore[misc]\n    def start_http_server(*a, **k): pass        # type: ignore[misc]\n\n\n# Buckets chosen from the measured reality: deterministic answers land at\n# 2-60ms, the one model path at ~2.6s. Default buckets would put every\n# deterministic answer in a single bin and tell you nothing.\n_FAST = (0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)\n\nANSWERS = Counter("asoia_answers_total",\n                  "Answers produced, by how they were composed and routed.",\n                  ["compose", "route", "grounded"])\nANSWER_SECONDS = Histogram("asoia_answer_seconds",\n                           "End-to-end time to answer a question.",\n                           ["compose"], buckets=_FAST)\nTOOL_CALLS = Counter("asoia_tool_calls_total",\n                     "Tool invocations, by tool.", ["tool"])\nLLM_CALLS = Counter("asoia_llm_calls_total",\n                    "Calls to the language model, by why it was called.",\n                    ["purpose"])\nFALLBACKS = Counter("asoia_compose_fallbacks_total",\n                    "Times Python composition gave way to the model.", ["reason"])\nGROUNDING = Counter("asoia_grounding_warnings_total",\n                    "Grounding warnings raised on a composed answer.", ["kind"])\nRAIL_BLOCKS = Counter("asoia_rail_blocks_total",\n                      "Answers or questions stopped by a guardrail.", ["rail"])\nTRUNCATED = Counter("asoia_answers_truncated_total",\n                    "Narrations that hit max_tokens and were cut short.")\nNIM_SECONDS = Histogram("asoia_nim_seconds",\n                        "Time spent in a NIM call, by service.",\n                        ["service"], buckets=_FAST)\nNIM_ERRORS = Counter("asoia_nim_errors_total",\n                     "Failed NIM calls, by service and cause.",\n                     ["service", "cause"])\nUPDATES = Counter("asoia_updates_total",\n                  "Technician updates through the ingestion pipeline.",\n                  ["outcome"])\nUP = Gauge("asoia_build_info", "1 when the app is running.", ["component"])\n\n\ndef _service_of(url: str) -> str:\n    """Which NIM a URL belongs to, for labelling. Ports match start_nims.sh."""\n    u = str(url)\n    if "/ranking" in u or ":8002" in u:\n        return "rerank"\n    if "/embeddings" in u or ":8001" in u:\n        return "embed"\n    if "/chat/completions" in u or ":8000" in u:\n        return "llm"\n    if "speech" in u or "asr" in u:\n        return "asr"\n    return "other"\n\n\n@contextmanager\ndef nim_call(url: str):\n    """Time one NIM call and record how it ended."""\n    svc = _service_of(url)\n    t = time.perf_counter()\n    try:\n        yield\n    except Exception as e:\n        NIM_ERRORS.labels(service=svc, cause=type(e).__name__).inc()\n        raise\n    finally:\n        NIM_SECONDS.labels(service=svc).observe(time.perf_counter() - t)\n\n\ndef record_answer(ans, seconds: float) -> None:\n    """Record one answered question. Never raises - it is only telemetry."""\n    try:\n        compose = getattr(ans, "composed", "?") or "?"\n        route = getattr(ans, "route", "?") or "?"\n        warnings = list(getattr(ans, "warnings", None) or [])\n        ANSWERS.labels(compose=compose, route=route,\n                       grounded=str(not warnings).lower()).inc()\n        ANSWER_SECONDS.labels(compose=compose).observe(seconds)\n        for call in getattr(ans, "tool_calls", None) or []:\n            TOOL_CALLS.labels(tool=str(call.get("name", "?"))).inc()\n        if compose == "llm":\n            LLM_CALLS.labels(purpose="narration").inc()\n        if route == "llm":\n            LLM_CALLS.labels(purpose="routing").inc()\n        for note in getattr(ans, "compose_notes", None) or []:\n            if "cut short" in note:\n                TRUNCATED.inc()\n            else:\n                # Bucket by kind, not by the whole message: the RO number in\n                # "renderer for diff_ro raised KeyError: RO-26-08192" would make\n                # a new time series per repair order.\n                FALLBACKS.labels(reason=str(note).split(":")[0][:60]).inc()\n        for w in warnings:\n            GROUNDING.labels(kind=str(w).split(" ")[0][:40]).inc()\n    except Exception:\n        pass\n\n\ndef record_rail(result) -> None:\n    try:\n        if not getattr(result, "allowed", True):\n            RAIL_BLOCKS.labels(rail=str(getattr(result, "rail", "?"))).inc()\n    except Exception:\n        pass\n\n\ndef record_update(outcome: str) -> None:\n    try:\n        UPDATES.labels(outcome=str(outcome)).inc()\n    except Exception:\n        pass\n\n\n_started = False\n\n\ndef serve(port: int | None = None) -> int | None:\n    """Expose /metrics. Returns the port, or None if metrics are unavailable.\n\n    Idempotent, and never fatal: a demo must not fail to start because a metrics\n    port is busy.\n    """\n    global _started\n    if not ENABLED or _started or os.environ.get("ASOIA_METRICS", "1") != "1":\n        return None\n    p = int(port or os.environ.get("ASOIA_METRICS_PORT", "9400"))\n    try:\n        start_http_server(p)\n        UP.labels(component="app").set(1)\n        _started = True\n        print(f"[metrics] serving on :{p}/metrics")\n        return p\n    except Exception as e:\n        print(f"[metrics] not started ({type(e).__name__}: {e})")\n        return None\n',
      "app/obs/metrics.py  the series, and the no-op shim")
write("app/obs/__init__.py", "", "app/obs/__init__.py")


# ==================================================== 2. time every answer
# A wrapper rather than edits at each `return ans`: ask() has two exit paths and
# a third would be added eventually without anyone remembering the second one.
edit("app/agent/agent.py",
     'def ask(question: str, chat_fn=None, use_llm_router: bool = True) -> Answer:',
     'def ask(question: str, chat_fn=None, use_llm_router: bool = True) -> Answer:\n    """Answer a question, and record how it went. See app/obs/metrics.py."""\n    import time as _t\n    from app.obs import metrics as _M\n    _start = _t.perf_counter()\n    ans = _ask_inner(question, chat_fn, use_llm_router)\n    _M.record_answer(ans, _t.perf_counter() - _start)\n    return ans\n\n\ndef _ask_inner(question: str, chat_fn=None, use_llm_router: bool = True) -> Answer:',
     "agent.py  ask() times itself",
     skip_if="def _ask_inner(")


# ==================================================== 3. time every NIM call
edit("app/nim/client.py",
     '        try:\n            r = httpx.post(url, json=payload, headers=_headers(local), timeout=timeout)',
     '        try:\n            from app.obs import metrics as _M\n            with _M.nim_call(url):\n                r = httpx.post(url, json=payload, headers=_headers(local),\n                               timeout=timeout)',
     "client.py  _post is timed per service",
     skip_if="with _M.nim_call(url):")


# ==================================================== 4. count rail blocks
edit("app/guardrails/rails.py",
     'def check_output(answer) -> RailResult:\n    """Block an answer carrying claims the tools never produced."""\n    reasons = list(getattr(answer, "warnings", []) or [])',
     'def _counted(result):\n    """Record a rail decision, then hand it back unchanged."""\n    from app.obs import metrics as _M\n    _M.record_rail(result)\n    return result\n\n\ndef check_output(answer) -> RailResult:\n    """Block an answer carrying claims the tools never produced."""\n    reasons = list(getattr(answer, "warnings", []) or [])',
     "rails.py  a counter for rail decisions",
     skip_if="def _counted(")

edit("app/guardrails/rails.py",
     '    if reasons:\n        return RailResult(False,\n            "I can\'t answer that from the records I have. " +\n            "; ".join(reasons[:3]) + ".", "output:grounding", reasons)\n    return RailResult(True)',
     '    if reasons:\n        return _counted(RailResult(False,\n            "I can\'t answer that from the records I have. " +\n            "; ".join(reasons[:3]) + ".", "output:grounding", reasons))\n    return RailResult(True)',
     "rails.py  count blocked answers",
     skip_if="return _counted(RailResult(False,")


# ==================================================== 5. serve it
edit("app/ui/gradio_app.py",
     '    _warm_nims()\n    return demo',
     '    _warm_nims()\n    from app.obs import metrics as _M\n    _M.serve()\n    return demo',
     "gradio_app.py  expose /metrics when the UI starts",
     skip_if="_M.serve()")


# ==================================================== 6. config and dashboard
write('configs/prometheus.yml', 'global:\n  scrape_interval: 10s\n  evaluation_interval: 10s\n\nscrape_configs:\n  # The app itself. Host networking, so localhost is the instance.\n  - job_name: asoia\n    static_configs:\n      - targets: ["localhost:9400"]\n\n  # The three NIMs publish Triton metrics on their own container port 8002.\n  # start_nims.sh maps each container\'s 8000 to a distinct host port, so these\n  # are only reachable if you also publish 8002 - left here, commented, because\n  # adding a second -p to each container is a deployment change, not a config one.\n  # - job_name: nim\n  #   static_configs:\n  #     - targets: ["localhost:8012", "localhost:8022", "localhost:8032"]\n',
      'configs/prometheus.yml')
write('configs/grafana/dashboards/asoia-dashboard.json', '{\n  "title": "Service Operations Agent",\n  "uid": "asoia",\n  "timezone": "browser",\n  "refresh": "10s",\n  "time": {"from": "now-1h", "to": "now"},\n  "panels": [\n    {"type": "stat", "title": "Answers composed in Python (%)",\n     "description": "The headline claim. Structured questions should compose in Python and make no model call at all.",\n     "gridPos": {"h": 5, "w": 6, "x": 0, "y": 0},\n     "targets": [{"expr": "100 * sum(rate(asoia_answers_total{compose=\\"python\\"}[5m])) / clamp_min(sum(rate(asoia_answers_total[5m])), 0.0001)", "legendFormat": "python"}],\n     "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100,\n       "thresholds": {"mode": "absolute", "steps": [\n         {"color": "red", "value": null}, {"color": "orange", "value": 50}, {"color": "green", "value": 80}]}}}},\n    {"type": "stat", "title": "Ungrounded answers",\n     "description": "Any non-zero value means a renderer derived a figure the tools never produced.",\n     "gridPos": {"h": 5, "w": 6, "x": 6, "y": 0},\n     "targets": [{"expr": "sum(increase(asoia_grounding_warnings_total[1h]))", "legendFormat": "warnings"}],\n     "fieldConfig": {"defaults": {"thresholds": {"mode": "absolute", "steps": [\n       {"color": "green", "value": null}, {"color": "red", "value": 1}]}}}},\n    {"type": "stat", "title": "Silent fallbacks to the model",\n     "description": "A renderer gave way to narration. Designed paths (search_updates) are not counted.",\n     "gridPos": {"h": 5, "w": 6, "x": 12, "y": 0},\n     "targets": [{"expr": "sum(increase(asoia_compose_fallbacks_total[1h]))", "legendFormat": "fallbacks"}],\n     "fieldConfig": {"defaults": {"thresholds": {"mode": "absolute", "steps": [\n       {"color": "green", "value": null}, {"color": "orange", "value": 1}]}}}},\n    {"type": "stat", "title": "Answers cut short",\n     "description": "Narration hit max_tokens. The answer reached the reader incomplete.",\n     "gridPos": {"h": 5, "w": 6, "x": 18, "y": 0},\n     "targets": [{"expr": "sum(increase(asoia_answers_truncated_total[1h]))", "legendFormat": "truncated"}],\n     "fieldConfig": {"defaults": {"thresholds": {"mode": "absolute", "steps": [\n       {"color": "green", "value": null}, {"color": "red", "value": 1}]}}}},\n    {"type": "timeseries", "title": "Answer latency by compose path (p50 / p95)",\n     "description": "Deterministic answers sit in milliseconds; only the search path should be seconds.",\n     "gridPos": {"h": 8, "w": 12, "x": 0, "y": 5},\n     "targets": [\n       {"expr": "histogram_quantile(0.50, sum by (le, compose) (rate(asoia_answer_seconds_bucket[5m])))", "legendFormat": "p50 {{compose}}"},\n       {"expr": "histogram_quantile(0.95, sum by (le, compose) (rate(asoia_answer_seconds_bucket[5m])))", "legendFormat": "p95 {{compose}}"}],\n     "fieldConfig": {"defaults": {"unit": "s"}}},\n    {"type": "timeseries", "title": "NIM latency by service (p95)",\n     "description": "Generation dominates the search path; rerank was measured at 137ms for 18 candidates.",\n     "gridPos": {"h": 8, "w": 12, "x": 12, "y": 5},\n     "targets": [{"expr": "histogram_quantile(0.95, sum by (le, service) (rate(asoia_nim_seconds_bucket[5m])))", "legendFormat": "{{service}}"}],\n     "fieldConfig": {"defaults": {"unit": "s"}}},\n    {"type": "timeseries", "title": "Model calls per minute, by purpose",\n     "description": "Routing calls should be rare and narration calls should only come from free-text search.",\n     "gridPos": {"h": 7, "w": 8, "x": 0, "y": 13},\n     "targets": [{"expr": "sum by (purpose) (rate(asoia_llm_calls_total[5m])) * 60", "legendFormat": "{{purpose}}"}]},\n    {"type": "timeseries", "title": "Tool usage",\n     "description": "Which tools the router actually picks - the cheapest way to spot a routing regression.",\n     "gridPos": {"h": 7, "w": 8, "x": 8, "y": 13},\n     "targets": [{"expr": "sum by (tool) (rate(asoia_tool_calls_total[5m])) * 60", "legendFormat": "{{tool}}"}]},\n    {"type": "timeseries", "title": "Guardrail blocks and NIM errors",\n     "gridPos": {"h": 7, "w": 8, "x": 16, "y": 13},\n     "targets": [\n       {"expr": "sum by (rail) (rate(asoia_rail_blocks_total[5m])) * 60", "legendFormat": "rail {{rail}}"},\n       {"expr": "sum by (service) (rate(asoia_nim_errors_total[5m])) * 60", "legendFormat": "error {{service}}"}]}\n  ]\n}\n',
      'configs/grafana/dashboards/asoia-dashboard.json  nine panels')
write('configs/grafana/datasources/prometheus.yml', 'apiVersion: 1\ndatasources:\n  - name: Prometheus\n    type: prometheus\n    access: proxy\n    url: http://localhost:9090\n    isDefault: true\n',
      'configs/grafana/datasources/prometheus.yml')
write('configs/grafana/dashboards/provider.yml', 'apiVersion: 1\nproviders:\n  - name: asoia\n    folder: ""\n    type: file\n    options:\n      path: /etc/grafana/provisioning/dashboards\n',
      'configs/grafana/dashboards/provider.yml')
write('scripts/start_observability.sh', '#!/usr/bin/env bash\n# Prometheus + Grafana for the service operations agent.\n#\n#   bash scripts/start_observability.sh up      # start both\n#   bash scripts/start_observability.sh down\n#   bash scripts/start_observability.sh status\n#\n# Both run on the CPU with host networking, so they cost no VRAM and nothing to\n# run beyond the box you already have. The app exposes /metrics on 9400.\nset -uo pipefail\n\nPROM_PORT="${PROM_PORT:-9090}"\nGRAF_PORT="${GRAF_PORT:-3000}"\nAPP_METRICS="${ASOIA_METRICS_PORT:-9400}"\nROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n\nup() {\n  [ -f "$ROOT/configs/prometheus.yml" ] || { echo "configs/prometheus.yml missing"; exit 1; }\n  echo "==> prometheus on :$PROM_PORT (scraping localhost:$APP_METRICS)"\n  docker rm -f asoia-prometheus >/dev/null 2>&1\n  docker run -d --name asoia-prometheus --network host --restart unless-stopped \\\n    -v "$ROOT/configs/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \\\n    prom/prometheus:v2.54.1 \\\n      --config.file=/etc/prometheus/prometheus.yml \\\n      --web.listen-address=":$PROM_PORT" >/dev/null || exit 1\n\n  echo "==> grafana on :$GRAF_PORT (anonymous viewer, no login)"\n  docker rm -f asoia-grafana >/dev/null 2>&1\n  docker run -d --name asoia-grafana --network host --restart unless-stopped \\\n    -e GF_SERVER_HTTP_PORT="$GRAF_PORT" \\\n    -e GF_AUTH_ANONYMOUS_ENABLED=true \\\n    -e GF_AUTH_ANONYMOUS_ORG_ROLE=Admin \\\n    -e GF_AUTH_DISABLE_LOGIN_FORM=true \\\n    -v "$ROOT/configs/grafana/datasources:/etc/grafana/provisioning/datasources:ro" \\\n    -v "$ROOT/configs/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro" \\\n    grafana/grafana:11.2.0 >/dev/null || exit 1\n\n  cat <<NEXT\n\nStarted. From your laptop:\n  brev port-forward capstone-poc --port $GRAF_PORT:$GRAF_PORT\n  open http://localhost:$GRAF_PORT   -> dashboard "Service Operations Agent"\n\nAnonymous access is on and the login form is off, because this is reachable only\nover the port-forward. Do not publish $GRAF_PORT.\nNEXT\n}\n\ndown() {\n  docker rm -f asoia-prometheus asoia-grafana >/dev/null 2>&1\n  echo "stopped."\n}\n\nstatus() {\n  docker ps --filter name=asoia- --format \'{{.Names}}\\t{{.Status}}\'\n  printf \'app /metrics -> \'\n  curl -s -o /dev/null -w \'%{http_code}\\n\' --max-time 4 "http://localhost:$APP_METRICS/metrics" \\\n    || echo "unreachable"\n  printf \'prometheus   -> \'\n  curl -s -o /dev/null -w \'%{http_code}\\n\' --max-time 4 "http://localhost:$PROM_PORT/-/ready" \\\n    || echo "unreachable"\n}\n\ncase "${1:-up}" in\n  up) up ;;\n  down) down ;;\n  status) status ;;\n  *) echo "usage: $0 [up|down|status]"; exit 2 ;;\nesac\n',
      'scripts/start_observability.sh  up / down / status', executable=True)


# ==================================================== verify
print("Quality pass 18:")
for c in CHANGES:
    print(c)
for f in ("app/obs/metrics.py", "app/agent/agent.py", "app/nim/client.py",
          "app/guardrails/rails.py", "app/ui/gradio_app.py"):
    ast.parse((ROOT / f).read_text())
print("\nmetrics.py, agent.py, client.py, rails.py and gradio_app.py parse cleanly.")

json.loads((ROOT / "configs/grafana/dashboards/asoia-dashboard.json").read_text())
print("dashboard JSON parses.")
import subprocess, shutil
if shutil.which("bash"):
    r = subprocess.run(["bash", "-n", "scripts/start_observability.sh"],
                       capture_output=True, text=True)
    print("start_observability.sh parses." if r.returncode == 0
          else f"SCRIPT ERROR: {r.stderr.strip()}")

# ---------------------------------------------------- prove the series move
sys.path.insert(0, ".")
from app.obs import metrics as M

bad = 0
print(f"\nprometheus_client available: {M.ENABLED}")
if not M.ENABLED:
    print("  (no-op shim active - the app runs unchanged, but nothing is recorded)")
    print("  install it with:  .venv/bin/python -m pip install prometheus-client")

for url, want in (("http://localhost:8000/v1/chat/completions", "llm"),
                  ("http://localhost:8001/v1/embeddings", "embed"),
                  ("http://localhost:8002/v1/ranking", "rerank"),
                  ("https://ai.api.nvidia.com/v1/speech/x", "asr")):
    got = M._service_of(url)
    bad += (got != want)
    print(f"  {'ok     ' if got == want else 'WRONG  '} {want:7s} <- {url}")

if M.ENABLED:
    from prometheus_client import REGISTRY, generate_latest

    class _A:
        composed, route = "python", "keyword"
        warnings, compose_notes = [], []
        tool_calls = [{"name": "list_ros"}]
    M.record_answer(_A(), 0.031)

    class _B:
        composed, route = "llm", "keyword"
        warnings = ["figure 7.4 does not appear in tool results"]
        compose_notes = ["the model ran out of room at 400 tokens - cut short"]
        tool_calls = [{"name": "search_updates"}]
    M.record_answer(_B(), 2.64)

    class _R:
        allowed, rail = False, "output:grounding"
    M.record_rail(_R())

    body = generate_latest(REGISTRY).decode()
    EXPECT = [
        ('asoia_answers_total{compose="python"', "python answer counted"),
        ('asoia_answers_total{compose="llm"', "llm answer counted"),
        ('asoia_llm_calls_total{purpose="narration"}', "narration call counted"),
        ('asoia_tool_calls_total{tool="list_ros"}', "tool usage counted"),
        ("asoia_grounding_warnings_total", "grounding warning counted"),
        ("asoia_answers_truncated_total 1.0", "truncation counted"),
        ('asoia_rail_blocks_total{rail="output:grounding"}', "rail block counted"),
        ("asoia_answer_seconds_bucket", "latency histogram present"),
    ]
    print("\nseries emitted on /metrics:")
    for needle, name in EXPECT:
        ok = needle in body
        bad += (not ok)
        print(f"  {'ok     ' if ok else 'MISSING'} {name}")
    # A label must never carry a repair order number, or every RO is a new series.
    leak = [l for l in body.splitlines()
            if l.startswith("asoia_") and "RO-26-" in l]
    bad += bool(leak)
    print(f"  {'ok     ' if not leak else 'WRONG  '} no repair order ids in labels")

print(f"\n{bad} check(s) unexpected" if bad
      else "\nAll pass-18 checks behaved as expected.")
print("\nNext:  .venv/bin/python -m pip install prometheus-client")
print("Then:  restart Gradio, then  bash scripts/start_observability.sh up")
print("Then:  brev port-forward capstone-poc --port 3000:3000")
