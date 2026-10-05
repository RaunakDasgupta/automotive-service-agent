"""End-to-end ingestion: audio or text in, applied state change and diff card out.

Stages, in order:
    capture -> transcribe -> extract (3 C's) -> resolve -> validate -> reconcile
Each stage is inspectable, which is what notebook 03 walks through.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.state import db as dbm
from app.pipeline.asr import transcribe, Transcript
from app.pipeline.extract import extract, Extraction
from app.pipeline.reconcile import reconcile, Reconciliation
from app.pipeline.diffcard import render as render_diff


@dataclass
class PipelineResult:
    text: str = ""
    transcript: Transcript | None = None
    extraction: Extraction | None = None
    reconciliation: Reconciliation | None = None
    diff_card: str = ""
    questions: list[str] = field(default_factory=list)
    stage: str = "start"
    error: str | None = None

    @property
    def applied(self) -> bool:
        return bool(self.reconciliation and self.reconciliation.accepted)


def run(con, *, text: str | None = None, audio_path: str | None = None,
        actor_id: str = "EMP001", ro_number: str | None = None,
        at: datetime | None = None, chat_fn=None, embed_fn=None,
        accept_conflicts: bool = False) -> PipelineResult:
    """Run one update through the whole pipeline."""
    res = PipelineResult()
    at = at or datetime.now()

    # 1. capture / transcribe
    if audio_path:
        res.stage = "transcribe"
        res.transcript = transcribe(audio_path)
        if not res.transcript.ok:
            res.error = res.transcript.error or "empty transcript"
            return res
        res.text = res.transcript.text
    elif text:
        res.text = text
    else:
        res.error = "nothing to process - provide text or audio_path"
        return res

    # 2. extract + resolve + validate
    res.stage = "extract"
    known = dbm.all_ro_numbers(con)
    try:
        res.extraction = extract(res.text, known, chat_fn=chat_fn, embed_fn=embed_fn)
    except Exception as e:
        res.error = f"extraction failed: {type(e).__name__}: {str(e)[:200]}"
        return res

    e = res.extraction
    target = ro_number or (e.ro_resolution.value if e.ro_resolution else None)
    if not target:
        res.stage = "clarify"
        res.questions = e.clarifying_questions()
        return res
    if e.unresolved:
        res.questions = e.clarifying_questions()   # proceed with what did resolve

    # 3. reconcile into the event log
    res.stage = "reconcile"
    uid = f"UPD-LIVE-{at.strftime('%Y%m%d%H%M%S')}"
    res.reconciliation = reconcile(con, target, e.to_ground_truth(res.text), actor_id,
                                   at=at, update_id=uid,
                                   accept_conflicts=accept_conflicts)
    ro = dbm.get_ro(con, target)
    res.diff_card = render_diff(res.reconciliation, ro, now=at)
    res.stage = "done"
    return res
