"""HTTP API over the same functions the Gradio app calls.

Gradio is a demo surface. A dealer group already runs a DMS, and the way this
reaches production is as a service that the DMS calls - so the agent, the
ingestion pipeline and the analytics queries are exposed here directly.

Two rules this file exists to keep:

  The guardrails are not optional. /ask runs check_input before any tool and
  check_output before returning, exactly as the UI does. An API that skipped them
  would be a way around the safety properties the rest of the project is built
  on, and it would be the obvious thing to skip.

  Nothing new is computed here. Every endpoint is a thin wrapper over a function
  that already exists and is already tested. This layer translates HTTP to
  Python and back; if it ever needs a calculation, the calculation belongs
  downstream in app/analytics.

    .venv/bin/python -m app.api.server              # or scripts/start_api.sh
    curl localhost:8080/health
    curl -X POST localhost:8080/ask -H 'content-type: application/json' \
         -d '{"question":"Which vehicles cannot be released on safety grounds?"}'
"""
from __future__ import annotations
import os
from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.agent.tools import TOOLS, call
from app.state import db as dbm

app = FastAPI(
    title="Automotive Service Operations Intelligence Agent",
    version="1.0.0",
    description="Grounded answers, voice-update ingestion and analytics over an "
                "append-only repair-order event log.",
)


# --------------------------------------------------------------- models
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class AskResponse(BaseModel):
    question: str
    answer: str
    allowed: bool = Field(..., description="False when a guardrail stopped it.")
    rail: str | None = Field(None, description="Which rail, when blocked.")
    composed: str = Field(..., description='"python" (computed) or "llm" (narrated).')
    route: str
    tools: list[str]
    citations: list[str]
    grounded: bool
    warnings: list[str]
    notes: list[str] = Field(default_factory=list,
                             description="Degradations worth knowing about.")


class UpdateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000,
                      description="A technician update, as dictated or typed.")
    staff_id: str = Field("EMP001", max_length=16)
    ro_number: str | None = Field(None, description="Overrides the one in the text.")
    accept_conflicts: bool = Field(
        False, description="Apply even if a blocking conflict is detected.")


class UpdateResponse(BaseModel):
    applied: bool
    ro_number: str | None
    stage: str
    diff_card: str
    events: list[dict]
    conflicts: list[dict]
    questions: list[str] = Field(
        default_factory=list, description="Clarifications, when it would not guess.")
    extraction: dict | None = None
    error: str | None = None


# --------------------------------------------------------------- endpoints
@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    """Database and model endpoints. Does not require the NIMs to be up."""
    out: dict[str, Any] = {"status": "ok", "database": "unknown", "nims": {}}
    try:
        n = len(dbm.all_ro_numbers(dbm.connect()))
        out["database"] = "ok"
        out["repair_orders"] = n
    except Exception as e:
        out["status"] = "degraded"
        out["database"] = f"{type(e).__name__}: {e}"
    try:
        from app.nim.client import health as nim_health
        out["nims"] = nim_health()
    except Exception as e:
        out["status"] = "degraded"
        out["nims"] = {"error": f"{type(e).__name__}: {e}"}
    # "Why does it think today is the 21st" is a question someone will ask during
    # a demo. The answer belongs in /health, not in a code read.
    try:
        from app.state.clock import source as clock_source
        out["clock"] = clock_source()
    except Exception as e:
        out["clock"] = {"error": f"{type(e).__name__}: {e}"}
    # A stale index yields confident, grounded-looking answers citing records that
    # are not there. It degrades nothing else, so nothing else would report it.
    try:
        from app.review.store import index_staleness
        st = index_staleness()
        out["index"] = st
        if st.get("ok") is False:
            out["status"] = "degraded"
    except Exception as e:
        out["index"] = {"ok": None, "reasons": [f"{type(e).__name__}: {e}"]}
    return out


@app.post("/ask", response_model=AskResponse, tags=["agent"])
def ask_endpoint(req: AskRequest) -> AskResponse:
    """Answer a question. Both guardrails apply, exactly as they do in the UI."""
    from app.agent.agent import ask
    from app.guardrails.rails import check_input, check_output

    gate = check_input(req.question)
    if not gate.allowed:
        return AskResponse(
            question=req.question, answer=gate.text or "Refused.", allowed=False,
            rail=gate.rail, composed="none", route="none", tools=[], citations=[],
            grounded=True, warnings=list(gate.reasons or []))
    try:
        a = ask(req.question)
    except Exception as e:                      # a NIM being down is a 503, not a 500
        raise HTTPException(status_code=503,
                            detail=f"{type(e).__name__}: {str(e)[:300]}") from e

    out = check_output(a)
    return AskResponse(
        question=req.question,
        answer=(a.text if out.allowed else (out.text or "Refused.")),
        allowed=out.allowed, rail=out.rail,
        composed=getattr(a, "composed", "?"), route=getattr(a, "route", "?"),
        tools=[c["name"] for c in a.tool_calls], citations=list(a.citations),
        grounded=bool(a.grounded), warnings=list(a.warnings or []),
        notes=list(getattr(a, "compose_notes", None) or []))


@app.post("/updates", response_model=UpdateResponse, tags=["ingestion"])
def post_update(req: UpdateRequest) -> UpdateResponse:
    """Put a technician update through extraction, resolution and reconciliation.

    Writes to the event log when it resolves. When it cannot identify the repair
    order or an operation, it returns questions rather than guessing - the same
    behaviour as the UI, and the reason `applied` can be false without an error.
    """
    from app.pipeline.run import run
    from app.obs import metrics as M
    try:
        from app.nim.client import embed as embed_fn
    except Exception:
        embed_fn = None
    # One second past the newest event, so a posted update lands inside "today"
    # as the application sees it rather than in the future. See app/state/clock.py.
    from app.state.clock import event_time
    now = event_time()
    try:
        res = run(dbm.connect(), text=req.text, actor_id=req.staff_id,
                  ro_number=req.ro_number, at=now, embed_fn=embed_fn,
                  accept_conflicts=req.accept_conflicts)
    except Exception as e:
        raise HTTPException(status_code=503,
                            detail=f"{type(e).__name__}: {str(e)[:300]}") from e

    rec = res.reconciliation
    M.record_update("applied" if res.applied else (res.stage or "not_applied"))
    e = res.extraction
    return UpdateResponse(
        applied=res.applied,
        ro_number=(rec.ro_number if rec else req.ro_number),
        stage=res.stage, diff_card=res.diff_card,
        events=[{"type": ev.type.value, "at": str(ev.at), "payload": ev.payload}
                for ev in (rec.events if rec else [])],
        conflicts=list(rec.conflicts if rec else []),
        questions=list(res.questions),
        extraction=({"concern": e.concern, "cause": e.cause,
                     "completed": e.completed, "pending": e.pending,
                     "recommended": e.correction, "parts": e.parts,
                     "measurements": e.measurements, "dtc_codes": e.dtc_codes,
                     "severity": e.severity, "state_signal": e.state_signal,
                     "confidence": e.confidence} if e else None),
        error=res.error)


@app.get("/ros", tags=["analytics"])
def get_ros(filter: Literal["active", "blocked", "at_risk", "safety",
                            "waiter", "all"] = "active",
            limit: int = Query(25, ge=1, le=200)) -> dict:
    """Filter the shop floor."""
    return call("list_ros", filter=filter, limit=limit)


@app.get("/ros/{ro_number}", tags=["analytics"])
def get_ro(ro_number: str) -> dict:
    """Derived state of one repair order."""
    res = call("get_ro_state", ro_number=ro_number)
    if res.get("found") is False:
        raise HTTPException(status_code=404, detail=res.get("error", "not found"))
    return res


@app.get("/ros/{ro_number}/timeline", tags=["analytics"])
def get_timeline(ro_number: str, limit: int = Query(20, ge=1, le=200)) -> dict:
    """Technician updates for one repair order, as written."""
    return call("get_ro_timeline", ro_number=ro_number, limit=limit)


@app.get("/ros/{ro_number}/diff", tags=["analytics"])
def get_diff(ro_number: str, since_hours: int = Query(12, ge=1, le=720)) -> dict:
    """What changed on a repair order within a window."""
    return call("diff_ro", ro_number=ro_number, since_hours=since_hours)


@app.get("/handover", tags=["analytics"])
def get_handover(shift: Literal["MORNING", "AFTERNOON"] = "AFTERNOON") -> dict:
    """The prioritised shift handover."""
    return call("generate_handover", shift=shift)


@app.get("/anomalies", tags=["analytics"])
def get_anomalies(days: int = Query(7, ge=1, le=90)) -> dict:
    """Cross-repair-order patterns: shared part holds, stalled work, comebacks."""
    return call("detect_anomalies", days=days)


@app.get("/shift", tags=["analytics"])
def get_shift(day_offset: int = Query(0, ge=-30, le=0),
              shift: Literal["", "MORNING", "AFTERNOON"] = "",
              view: Literal["people", "vehicles"] = "people") -> dict:
    """What happened on a day. day_offset 0 is today, -1 yesterday."""
    return call("get_shift_activity", day_offset=day_offset, shift=shift, view=view)


@app.get("/staff/{staff_id}", tags=["analytics"])
def get_staff(staff_id: str, days: int = Query(7, ge=1, le=90)) -> dict:
    """What one technician completed over a window."""
    res = call("get_technician_activity", staff_id=staff_id, days=days)
    if res.get("found") is False:
        raise HTTPException(status_code=404, detail=res.get("error", "not found"))
    return res


@app.get("/tools", tags=["ops"])
def list_tools() -> dict:
    """The tools the agent can call, and what each is for."""
    return {"tools": [{"name": n, "description": (f.__doc__ or "").strip()}
                      for n, f in sorted(TOOLS.items())]}




# --------------------------------------------------------------------- review
# The same functions the Data & Retrieval tab calls. Two readers, one source of
# truth: a reviewer with curl and a reviewer with a browser see the same numbers.

@app.get("/review/overview", tags=["review"])
def review_overview() -> dict:
    """Counts for everything the answers are built from, and the index state."""
    from app.review import store as RS
    return RS.overview()


@app.get("/review/events", tags=["review"])
def review_events(ro_number: str | None = None, event_type: str | None = None,
                  actor_id: str | None = None,
                  since_hours: int | None = Query(None, ge=1, le=8760),
                  text: str | None = None,
                  limit: int = Query(200, ge=1, le=2000),
                  offset: int = Query(0, ge=0)) -> dict:
    """The append-only log, filtered. Newest first."""
    from app.review import store as RS
    return RS.events(ro_number=ro_number, event_type=event_type, actor_id=actor_id,
                     since_hours=since_hours, text=text, limit=limit, offset=offset)


@app.get("/review/event-types", tags=["review"])
def review_event_types() -> dict:
    from app.review import store as RS
    return {"types": RS.event_types()}


@app.get("/review/ros/{ro_number}/fold", tags=["review"])
def review_fold(ro_number: str) -> dict:
    """A repair order's derived state next to the events it was derived from."""
    from app.review import store as RS
    r = RS.ro_review(ro_number)
    if r.get("error"):
        raise HTTPException(404, r["error"])
    return r


@app.get("/review/updates", tags=["review"])
def review_updates(ro_number: str | None = None, staff_id: str | None = None,
                   text: str | None = None,
                   limit: int = Query(200, ge=1, le=2000),
                   offset: int = Query(0, ge=0)) -> dict:
    from app.review import store as RS
    return RS.updates(ro_number=ro_number, staff_id=staff_id, text=text,
                      limit=limit, offset=offset)


@app.get("/review/index", tags=["review"])
def review_index(health_sample: int = Query(64, ge=0, le=1000)) -> dict:
    """Vector index stats, and a sampled check that the vectors are real."""
    from app.review import store as RS
    out = RS.index_stats()
    if out.get("exists") and health_sample:
        out["health"] = RS.index_health(sample=health_sample)
    return out


@app.get("/review/chunks", tags=["review"])
def review_chunks(ro_number: str | None = None, text: str | None = None,
                  limit: int = Query(100, ge=1, le=1000),
                  offset: int = Query(0, ge=0)) -> dict:
    """What is in the vector store. Vectors are not returned - see /review/chunks/{id}."""
    from app.review import store as RS
    return RS.chunks(ro_number=ro_number, text=text, limit=limit, offset=offset)


@app.get("/review/chunks/{update_id}", tags=["review"])
def review_chunk(update_id: str, preview_dims: int = Query(12, ge=0, le=128)) -> dict:
    from app.review import store as RS
    c = RS.chunk(update_id, preview_dims=preview_dims)
    if c.get("error"):
        raise HTTPException(404, c["error"])
    c["cited_by"] = RS.cited_by(update_id)
    return c


@app.get("/review/retrieval", tags=["review"])
def review_retrieval(q: str, retrieve_n: int = Query(18, ge=1, le=200),
                     rerank_n: int = Query(6, ge=0, le=50),
                     ro_number: str | None = None) -> dict:
    """Both stages of a real search, with each passage's movement between them."""
    from app.review import store as RS
    t = RS.retrieval_trace(q, retrieve_n=retrieve_n, rerank_n=rerank_n,
                           ro_number=ro_number)
    if t.get("error"):
        raise HTTPException(503, t["error"])
    return t


@app.get("/review/answers", tags=["review"])
def review_answers(grounded: bool | None = None,
                   limit: int = Query(100, ge=1, le=1000),
                   offset: int = Query(0, ge=0)) -> dict:
    """What has been asked, what it cited, and whether grounding passed."""
    from app.review import store as RS
    return RS.answers(limit=limit, offset=offset, grounded=grounded)


# ------------------------------------------------------- editing the store
# Parity with the Data & Retrieval tab, over HTTP. Same functions, same rules:
# every write goes to the UPDATE and re-embeds the chunk, because a chunk that
# disagrees with the record it cites produces confident, well-formed, fully
# "grounded" answers quoting text that is not in the database.
#
# These are the only administrative writes on this API. /updates is ingestion -
# the product doing its job - whereas correcting or hiding a technician's note
# is an operator action, so it has its own switch:
#
#     ASOIA_REVIEW_WRITES=0     the four endpoints below return 403
#
# It defaults to ON, so the API and the UI can do the same things. Worth knowing
# that this server binds 0.0.0.0 and has no authentication of its own: if you
# expose port 8080 beyond the box, turn these off or put something in front.

class EditRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000,
                      description="The corrected wording of the update.")
    actor_id: str = Field("API", max_length=32)


class ExcludeRequest(BaseModel):
    reason: str = Field("", max_length=500)
    actor_id: str = Field("API", max_length=32)


def _writes_allowed() -> None:
    if (os.environ.get("ASOIA_REVIEW_WRITES") or "1") == "0":
        raise HTTPException(
            403, "review writes are disabled (ASOIA_REVIEW_WRITES=0)")


def _edited(r: dict) -> dict:
    if not r.get("ok"):
        raise HTTPException(404 if "no update" in str(r.get("error", ""))
                            else 409, r.get("error", "the edit did not apply"))
    return r


@app.patch("/review/chunks/{update_id}", tags=["review"])
def review_edit(update_id: str, req: EditRequest) -> dict:
    """Correct an update's wording and re-embed its chunk.

    Writes to the record, not to the index: the two cannot drift apart this way.
    The previous wording is kept in `index_audit` and returned as `before`.
    """
    _writes_allowed()
    from app.retrieval import edit as E
    return _edited(E.edit_text(update_id, req.text, actor_id=req.actor_id))


@app.post("/review/chunks/{update_id}/reindex", tags=["review"])
def review_reindex(update_id: str) -> dict:
    """Re-embed a chunk from the record as it stands. No text change."""
    _writes_allowed()
    from app.retrieval import edit as E
    return _edited(E.reindex_one(update_id))


@app.post("/review/chunks/{update_id}/exclude", tags=["review"])
def review_exclude(update_id: str, req: ExcludeRequest) -> dict:
    """Take a chunk out of the index. The update itself stays on file."""
    _writes_allowed()
    from app.retrieval import edit as E
    return _edited(E.exclude(update_id, reason=req.reason, actor_id=req.actor_id))


@app.post("/review/chunks/{update_id}/restore", tags=["review"])
def review_restore(update_id: str, req: ExcludeRequest | None = None) -> dict:
    """Put an excluded chunk back and re-embed it."""
    _writes_allowed()
    from app.retrieval import edit as E
    return _edited(E.restore(update_id,
                             actor_id=(req.actor_id if req else "API")))


@app.get("/review/chunks/{update_id}/history", tags=["review"])
def review_chunk_history(update_id: str) -> dict:
    """Every correction, exclusion and restore recorded against one update."""
    from app.retrieval import edit as E
    return {"update_id": update_id, "history": E.history(update_id)}


@app.get("/review/edits", tags=["review"])
def review_edits(limit: int = Query(100, ge=1, le=1000)) -> dict:
    """The whole edit audit trail, newest first.

    Separate from /review/events on purpose: a data correction is not something
    that happened in the workshop. Putting these in the lifecycle log is what
    broke seven of the fourteen answer checks in pass 27.
    """
    from app.retrieval import edit as E
    return {"edits": E.recent_edits(limit),
            "excluded": E.exclusions()}


def main() -> None:
    import uvicorn
    from app.obs import metrics as M
    from app.state.bootstrap import ensure_dataset
    ensure_dataset()
    M.serve()
    uvicorn.run(app, host=os.environ.get("API_HOST", "0.0.0.0"),
                port=int(os.environ.get("API_PORT", "8080")), log_level="info")


if __name__ == "__main__":
    main()
