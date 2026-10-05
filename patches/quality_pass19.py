#!/usr/bin/env python3
"""Nineteenth pass: an HTTP API - and the concurrency bug it immediately found.

Run from the project root:   python3 quality_pass19.py

`fastapi` and `uvicorn` have been declared dependencies since the first release
and were referenced by nothing. Gradio is a demo surface; a dealer group already
runs a DMS, and the way this reaches production is as a service the DMS calls.

app/api/server.py exposes the agent, the ingestion pipeline and the analytics
queries over HTTP. Two rules it exists to keep: the guardrails are not optional
(/ask runs check_input before any tool and check_output before returning,
exactly as the UI does), and nothing new is computed there - every endpoint is a
thin wrapper over a function that is already tested.

WHAT THE API FOUND ON ITS FIRST RUN

Putting a threadpool in front of the code exposed two defects that the
single-threaded demo had been hiding.

1. `tools.con()` CACHED ONE CONNECTION IN A MODULE GLOBAL.

       _CON = None
       def con():
           global _CON
           if _CON is None:
               _CON = dbm.connect()
           return _CON

   `dbm.connect()` is carefully thread-local - its own comment says "Gradio runs
   handlers in a worker pool" - and this threw that away. SQLite refuses a
   connection used from a thread other than the one that created it, so whichever
   thread arrived first worked and the rest raised ProgrammingError *inside a
   tool*, where call() turned it into `{"error": ...}` and the pipeline carried on.

   Intermittent, invisible, and present in the Gradio app all along: Gradio uses
   a worker pool too. It only surfaced here because an API makes concurrency the
   normal case instead of the rare one.

2. A FAILED TOOL PRODUCED AN ANSWER THE RAIL ALLOWED.

   The first symptom was a safety question coming back `allowed: true`,
   `grounded: true`, with ZERO citations and an answer built on an error dict.
   `_empty_by_construction` (pass 11) exempted any payload carrying `error` from
   the citation requirement - written for "there is no NIGHT shift", but it also
   waved through "the tool crashed". A tool failure is not an empty result.

   Now: `found is False` is still exempt, a bare `error` blocks, and `_summarise`
   records the failure as a compose note so it is visible and counted rather than
   composed over.

After the fixes: 404s are correct, that same question returns 18 citations, and
24 concurrent requests across 8 threads all succeed.
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
                 "      Run passes 1-18 first. Stopping without changes.")
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


# ============================ 1. the connection bug the API exposed
edit("app/agent/tools.py",
     '_CON = None\n\n\ndef con():\n    global _CON\n    if _CON is None:\n        _CON = dbm.connect()\n    return _CON',
     'def con():\n    """The connection for THIS thread.\n\n    This used to cache one connection in a module global, which defeated the\n    whole point of dbm.connect() being thread-local - and SQLite refuses a\n    connection used from a thread other than the one that made it. Gradio and\n    uvicorn both run handlers in a worker pool, so the failure was intermittent:\n    whichever thread got there first worked, and the rest raised ProgrammingError\n    inside a tool, where call() turned it into a result dict and the answer came\n    back looking fine. dbm.connect() already caches per thread.\n    """\n    return dbm.connect()',
     "tools.py  one connection per thread, not one per process",
     skip_if="The connection for THIS thread")


# ============================ 2. a failed tool is not an empty result
edit("app/guardrails/rails.py",
     '        if res.get("found") is False or res.get("error"):\n            continue',
     '        if res.get("found") is False:\n            continue        # a domain-level "nothing there", which is an answer\n        if res.get("error"):\n            return False    # a tool FAILED. That is never an empty result, and\n                            # it must not be waved through for lack of citations.',
     "rails.py  a tool failure blocks, a missing thing does not",
     skip_if="a tool FAILED")

edit("app/agent/agent.py",
     '        res = r.get("result")\n        if not isinstance(res, dict):\n            note(f"{tool} returned {type(res).__name__}, expected dict")\n            return None',
     '        res = r.get("result")\n        if not isinstance(res, dict):\n            note(f"{tool} returned {type(res).__name__}, expected dict")\n            return None\n        # call() turns an exception inside a tool into {"error": ...}. Without\n        # this the renderer composes over the wreckage and the answer looks fine.\n        if res.get("error") and res.get("found") is not False:\n            note(f"{tool} failed: {str(res[\'error\'])[:120]}")\n            return None',
     "agent.py  a tool failure is recorded, not composed over",
     skip_if="composes over the wreckage")


# ============================ 3. the service
write("app/api/server.py", '"""HTTP API over the same functions the Gradio app calls.\n\nGradio is a demo surface. A dealer group already runs a DMS, and the way this\nreaches production is as a service that the DMS calls - so the agent, the\ningestion pipeline and the analytics queries are exposed here directly.\n\nTwo rules this file exists to keep:\n\n  The guardrails are not optional. /ask runs check_input before any tool and\n  check_output before returning, exactly as the UI does. An API that skipped them\n  would be a way around the safety properties the rest of the project is built\n  on, and it would be the obvious thing to skip.\n\n  Nothing new is computed here. Every endpoint is a thin wrapper over a function\n  that already exists and is already tested. This layer translates HTTP to\n  Python and back; if it ever needs a calculation, the calculation belongs\n  downstream in app/analytics.\n\n    .venv/bin/python -m app.api.server              # or scripts/start_api.sh\n    curl localhost:8080/health\n    curl -X POST localhost:8080/ask -H \'content-type: application/json\' \\\n         -d \'{"question":"Which vehicles cannot be released on safety grounds?"}\'\n"""\nfrom __future__ import annotations\nimport os\nfrom typing import Any, Literal\n\nfrom fastapi import Body, FastAPI, HTTPException, Query\nfrom pydantic import BaseModel, Field\n\nfrom app.agent.tools import TOOLS, call\nfrom app.state import db as dbm\n\napp = FastAPI(\n    title="Automotive Service Operations Intelligence Agent",\n    version="1.0.0",\n    description="Grounded answers, voice-update ingestion and analytics over an "\n                "append-only repair-order event log.",\n)\n\n\n# --------------------------------------------------------------- models\nclass AskRequest(BaseModel):\n    question: str = Field(..., min_length=1, max_length=2000)\n\n\nclass AskResponse(BaseModel):\n    question: str\n    answer: str\n    allowed: bool = Field(..., description="False when a guardrail stopped it.")\n    rail: str | None = Field(None, description="Which rail, when blocked.")\n    composed: str = Field(..., description=\'"python" (computed) or "llm" (narrated).\')\n    route: str\n    tools: list[str]\n    citations: list[str]\n    grounded: bool\n    warnings: list[str]\n    notes: list[str] = Field(default_factory=list,\n                             description="Degradations worth knowing about.")\n\n\nclass UpdateRequest(BaseModel):\n    text: str = Field(..., min_length=1, max_length=8000,\n                      description="A technician update, as dictated or typed.")\n    staff_id: str = Field("EMP001", max_length=16)\n    ro_number: str | None = Field(None, description="Overrides the one in the text.")\n    accept_conflicts: bool = Field(\n        False, description="Apply even if a blocking conflict is detected.")\n\n\nclass UpdateResponse(BaseModel):\n    applied: bool\n    ro_number: str | None\n    stage: str\n    diff_card: str\n    events: list[dict]\n    conflicts: list[dict]\n    questions: list[str] = Field(\n        default_factory=list, description="Clarifications, when it would not guess.")\n    extraction: dict | None = None\n    error: str | None = None\n\n\n# --------------------------------------------------------------- endpoints\n@app.get("/health", tags=["ops"])\ndef health() -> dict[str, Any]:\n    """Database and model endpoints. Does not require the NIMs to be up."""\n    out: dict[str, Any] = {"status": "ok", "database": "unknown", "nims": {}}\n    try:\n        n = len(dbm.all_ro_numbers(dbm.connect()))\n        out["database"] = "ok"\n        out["repair_orders"] = n\n    except Exception as e:\n        out["status"] = "degraded"\n        out["database"] = f"{type(e).__name__}: {e}"\n    try:\n        from app.nim.client import health as nim_health\n        out["nims"] = nim_health()\n    except Exception as e:\n        out["status"] = "degraded"\n        out["nims"] = {"error": f"{type(e).__name__}: {e}"}\n    return out\n\n\n@app.post("/ask", response_model=AskResponse, tags=["agent"])\ndef ask_endpoint(req: AskRequest) -> AskResponse:\n    """Answer a question. Both guardrails apply, exactly as they do in the UI."""\n    from app.agent.agent import ask\n    from app.guardrails.rails import check_input, check_output\n\n    gate = check_input(req.question)\n    if not gate.allowed:\n        return AskResponse(\n            question=req.question, answer=gate.text or "Refused.", allowed=False,\n            rail=gate.rail, composed="none", route="none", tools=[], citations=[],\n            grounded=True, warnings=list(gate.reasons or []))\n    try:\n        a = ask(req.question)\n    except Exception as e:                      # a NIM being down is a 503, not a 500\n        raise HTTPException(status_code=503,\n                            detail=f"{type(e).__name__}: {str(e)[:300]}") from e\n\n    out = check_output(a)\n    return AskResponse(\n        question=req.question,\n        answer=(a.text if out.allowed else (out.text or "Refused.")),\n        allowed=out.allowed, rail=out.rail,\n        composed=getattr(a, "composed", "?"), route=getattr(a, "route", "?"),\n        tools=[c["name"] for c in a.tool_calls], citations=list(a.citations),\n        grounded=bool(a.grounded), warnings=list(a.warnings or []),\n        notes=list(getattr(a, "compose_notes", None) or []))\n\n\n@app.post("/updates", response_model=UpdateResponse, tags=["ingestion"])\ndef post_update(req: UpdateRequest) -> UpdateResponse:\n    """Put a technician update through extraction, resolution and reconciliation.\n\n    Writes to the event log when it resolves. When it cannot identify the repair\n    order or an operation, it returns questions rather than guessing - the same\n    behaviour as the UI, and the reason `applied` can be false without an error.\n    """\n    from app.pipeline.run import run\n    from app.obs import metrics as M\n    try:\n        from app.nim.client import embed as embed_fn\n    except Exception:\n        embed_fn = None\n    now = (__import__("datetime").datetime.fromisoformat(os.environ["ASOIA_NOW"])\n           if os.environ.get("ASOIA_NOW") else None)\n    try:\n        res = run(dbm.connect(), text=req.text, actor_id=req.staff_id,\n                  ro_number=req.ro_number, at=now, embed_fn=embed_fn,\n                  accept_conflicts=req.accept_conflicts)\n    except Exception as e:\n        raise HTTPException(status_code=503,\n                            detail=f"{type(e).__name__}: {str(e)[:300]}") from e\n\n    rec = res.reconciliation\n    M.record_update("applied" if res.applied else (res.stage or "not_applied"))\n    e = res.extraction\n    return UpdateResponse(\n        applied=res.applied,\n        ro_number=(rec.ro_number if rec else req.ro_number),\n        stage=res.stage, diff_card=res.diff_card,\n        events=[{"type": ev.type.value, "at": str(ev.at), "payload": ev.payload}\n                for ev in (rec.events if rec else [])],\n        conflicts=list(rec.conflicts if rec else []),\n        questions=list(res.questions),\n        extraction=({"concern": e.concern, "cause": e.cause,\n                     "completed": e.completed, "pending": e.pending,\n                     "recommended": e.correction, "parts": e.parts,\n                     "measurements": e.measurements, "dtc_codes": e.dtc_codes,\n                     "severity": e.severity, "state_signal": e.state_signal,\n                     "confidence": e.confidence} if e else None),\n        error=res.error)\n\n\n@app.get("/ros", tags=["analytics"])\ndef get_ros(filter: Literal["active", "blocked", "at_risk", "safety",\n                            "waiter", "all"] = "active",\n            limit: int = Query(25, ge=1, le=200)) -> dict:\n    """Filter the shop floor."""\n    return call("list_ros", filter=filter, limit=limit)\n\n\n@app.get("/ros/{ro_number}", tags=["analytics"])\ndef get_ro(ro_number: str) -> dict:\n    """Derived state of one repair order."""\n    res = call("get_ro_state", ro_number=ro_number)\n    if res.get("found") is False:\n        raise HTTPException(status_code=404, detail=res.get("error", "not found"))\n    return res\n\n\n@app.get("/ros/{ro_number}/timeline", tags=["analytics"])\ndef get_timeline(ro_number: str, limit: int = Query(20, ge=1, le=200)) -> dict:\n    """Technician updates for one repair order, as written."""\n    return call("get_ro_timeline", ro_number=ro_number, limit=limit)\n\n\n@app.get("/ros/{ro_number}/diff", tags=["analytics"])\ndef get_diff(ro_number: str, since_hours: int = Query(12, ge=1, le=720)) -> dict:\n    """What changed on a repair order within a window."""\n    return call("diff_ro", ro_number=ro_number, since_hours=since_hours)\n\n\n@app.get("/handover", tags=["analytics"])\ndef get_handover(shift: Literal["MORNING", "AFTERNOON"] = "AFTERNOON") -> dict:\n    """The prioritised shift handover."""\n    return call("generate_handover", shift=shift)\n\n\n@app.get("/anomalies", tags=["analytics"])\ndef get_anomalies(days: int = Query(7, ge=1, le=90)) -> dict:\n    """Cross-repair-order patterns: shared part holds, stalled work, comebacks."""\n    return call("detect_anomalies", days=days)\n\n\n@app.get("/shift", tags=["analytics"])\ndef get_shift(day_offset: int = Query(0, ge=-30, le=0),\n              shift: Literal["", "MORNING", "AFTERNOON"] = "",\n              view: Literal["people", "vehicles"] = "people") -> dict:\n    """What happened on a day. day_offset 0 is today, -1 yesterday."""\n    return call("get_shift_activity", day_offset=day_offset, shift=shift, view=view)\n\n\n@app.get("/staff/{staff_id}", tags=["analytics"])\ndef get_staff(staff_id: str, days: int = Query(7, ge=1, le=90)) -> dict:\n    """What one technician completed over a window."""\n    res = call("get_technician_activity", staff_id=staff_id, days=days)\n    if res.get("found") is False:\n        raise HTTPException(status_code=404, detail=res.get("error", "not found"))\n    return res\n\n\n@app.get("/tools", tags=["ops"])\ndef list_tools() -> dict:\n    """The tools the agent can call, and what each is for."""\n    return {"tools": [{"name": n, "description": (f.__doc__ or "").strip()}\n                      for n, f in sorted(TOOLS.items())]}\n\n\ndef main() -> None:\n    import uvicorn\n    from app.obs import metrics as M\n    M.serve()\n    uvicorn.run(app, host=os.environ.get("API_HOST", "0.0.0.0"),\n                port=int(os.environ.get("API_PORT", "8080")), log_level="info")\n\n\nif __name__ == "__main__":\n    main()\n',
      "app/api/server.py  agent, ingestion and analytics over HTTP")
write("app/api/__init__.py", "", "app/api/__init__.py")
write("scripts/start_api.sh", '#!/usr/bin/env bash\n# The HTTP API. Same functions the UI calls, same guardrails.\n#\n#   bash scripts/start_api.sh            # foreground on :8080\n#   bash scripts/start_api.sh --detach   # background, logs to /tmp/asoia-api.log\nset -uo pipefail\ncd "$(dirname "${BASH_SOURCE[0]}")/.."\n[ -f .env ] && { set -a; . ./.env; set +a; }\n: "${API_PORT:=8080}"\n: "${ASOIA_NOW:=}"\n\nPY=.venv/bin/python\n[ -x "$PY" ] || { echo "no .venv - see README"; exit 1; }\n"$PY" -c "import fastapi, uvicorn" 2>/dev/null || {\n  echo "fastapi/uvicorn missing. Install with:"\n  echo "  $PY -m pip install \'fastapi>=0.115\' \'uvicorn>=0.30\'"; exit 1; }\n\nif [ "${1:-}" = "--detach" ]; then\n  setsid nohup "$PY" -m app.api.server >/tmp/asoia-api.log 2>&1 </dev/null &\n  sleep 3\n  printf \'health -> \'\n  curl -s -o /dev/null -w \'%{http_code}\\n\' --max-time 5 "http://localhost:$API_PORT/health"\n  echo "logs: tail -f /tmp/asoia-api.log"\n  echo "docs: http://localhost:$API_PORT/docs"\nelse\n  echo "==> http://localhost:$API_PORT/docs   (Ctrl-C to stop)"\n  exec "$PY" -m app.api.server\nfi\n',
      "scripts/start_api.sh  foreground or --detach", executable=True)


# ============================ verify
print("Quality pass 19:")
for c in CHANGES:
    print(c)
for f in ("app/api/server.py", "app/agent/tools.py", "app/guardrails/rails.py",
          "app/agent/agent.py"):
    ast.parse((ROOT / f).read_text())
print("\nserver.py, tools.py, rails.py and agent.py parse cleanly.")

import subprocess, shutil
if shutil.which("bash"):
    r = subprocess.run(["bash", "-n", "scripts/start_api.sh"],
                       capture_output=True, text=True)
    print("start_api.sh parses." if r.returncode == 0
          else f"SCRIPT ERROR: {r.stderr.strip()}")

sys.path.insert(0, ".")
bad = 0

# the connection must differ per thread, and each must be usable there
import threading
from app.agent.tools import con
seen, errs = {}, []
def _probe(i):
    try:
        c = con()
        c.execute("SELECT 1").fetchone()
        seen[threading.get_ident()] = id(c)
    except Exception as e:
        errs.append(f"{type(e).__name__}: {e}")
ts = [threading.Thread(target=_probe, args=(i,)) for i in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
ok = not errs and len(seen) > 1
bad += (not ok)
print(f"\n  {'ok     ' if ok else 'WRONG  '} a usable connection per thread "
      f"({len(seen)} threads, {len(set(seen.values()))} connections)")
for e in errs[:2]:
    print(f"           {e}")

# a tool failure must block; a domain "not found" must not
from app.guardrails.rails import check_output
from app.agent.agent import Answer
for name, res, want_allowed in (
        ("a crashed tool is blocked", {"error": "list_ros failed: OperationalError"}, False),
        ("an empty window is allowed", {"found": False, "date": "2026-09-25"}, True),
        ("an unknown shift is allowed", {"found": False, "error": "no NIGHT shift"}, True)):
    a = Answer(question="q", text="t" * 50, composed="python", citations=[],
               results=[{"tool": "t", "args": {}, "result": res}])
    got = check_output(a).allowed
    ok = got == want_allowed
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

# the endpoints, if fastapi is installed
try:
    from fastapi.testclient import TestClient
    from app.api.server import app as _app
    c = TestClient(_app)
    ROUTES = [("GET", "/health", {}, 200), ("GET", "/tools", {}, 200),
              ("GET", "/ros", {"filter": "safety", "limit": 3}, 200),
              ("GET", "/handover", {}, 200), ("GET", "/anomalies", {"days": 7}, 200),
              ("GET", "/shift", {"view": "vehicles"}, 200),
              ("GET", "/ros/RO-99-99999", {}, 404),
              ("GET", "/staff/NOPE999", {}, 404)]
    print("\nendpoints:")
    for m, path, params, want in ROUTES:
        got = c.get(path, params=params).status_code
        ok = got == want
        bad += (not ok)
        print(f"  {'ok     ' if ok else 'WRONG  '} {m} {path:22s} -> {got} "
              f"(expected {want})")
    r = c.post("/ask", json={"question": "Which vehicles cannot be released "
                                         "on safety grounds?"})
    j = r.json()
    ok = r.status_code == 200 and j["allowed"] and j["composed"] == "python" \
        and len(j["citations"]) > 0
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} POST /ask -> composed="
          f"{j.get('composed')} citations={len(j.get('citations', []))}")
    r = c.post("/ask", json={"question": "Go ahead and order the parts for "
                                         "RO-26-08165"})
    j = r.json()
    ok = (not j["allowed"]) and j["rail"] == "action:unauthorised"
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} the input rail applies to the API "
          f"too (rail={j.get('rail')})")

    # concurrency, which is the whole reason the bug above was found
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(8) as ex:
        codes = set(ex.map(
            lambda _: c.get("/ros", params={"filter": "safety", "limit": 2})
                       .status_code, range(24)))
    ok = codes == {200}
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} 24 concurrent requests across 8 "
          f"threads -> {sorted(codes)}")
except ImportError:
    print("\n  note  fastapi not installed here - endpoint checks skipped.")
    print("        .venv/bin/python -m pip install 'fastapi>=0.115' 'uvicorn>=0.30'")

print(f"\n{bad} check(s) unexpected" if bad
      else "\nAll pass-19 checks behaved as expected.")
print("\nNext:  .venv/bin/python -m pytest tests/ -q")
print("Then:  .venv/bin/python scripts/verify_answers.py")
print("Then:  bash scripts/start_api.sh --detach   ->  http://localhost:8080/docs")
