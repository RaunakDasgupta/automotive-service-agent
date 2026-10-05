"""Apply a structured update to the event log, detecting conflicts first.

Never overwrites. Produces events, plus a diff describing exactly what changed -
which is what the technician sees back, and what makes the app feel intelligent
rather than like a form.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.state import db as dbm
from app.state.events import Event, EventType as E
from app.state.engine import fold, ROSnapshot
from app.state.transitions import ROState, is_legal, reason_illegal
from app.data.catalog import OP_BY_CODE


@dataclass
class Reconciliation:
    ro_number: str
    accepted: bool
    events: list[Event] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    clarifications: list[str] = field(default_factory=list)
    before: ROSnapshot | None = None
    after: ROSnapshot | None = None


def _detect_conflicts(snap: ROSnapshot, gt: dict) -> list[dict]:
    """Contradictions between the new update and what the log already says."""
    out = []
    # Work reported complete that the log already has complete -> rework/comeback.
    for o in gt.get("completed") or []:
        prior = snap.ops.get(o["op_code"])
        if prior and prior.status == "COMPLETED":
            out.append({"kind": "REPEAT_OP",
                        "detail": f"{o['op_code']} already recorded complete by "
                                  f"{prior.by} - is this rework or a comeback?",
                        "evidence": [prior.event_id]})
    # Repair reported while the customer has not authorised the work.
    if (gt.get("completed") and snap.state == ROState.AWAITING_AUTHORISATION
            and not snap.authorised):
        out.append({"kind": "AUTH_CONFLICT",
                    "detail": "Work reported complete but this RO is still awaiting "
                              "customer authorisation.",
                    "evidence": snap.event_ids[-3:]})
    # Parts fitted that the log says are not here.
    for o in gt.get("completed") or []:
        for part, d in snap.parts.items():
            if d.get("op_code") == o["op_code"] and d.get("availability") in ("BACKORDER", "NLA", "NEXT_DAY"):
                out.append({"kind": "PARTS_CONFLICT",
                            "detail": f"{o['op_code']} reported complete but part {part} "
                                      f"is showing {d['availability']}.",
                            "evidence": [d.get("event_id")]})
    # Proposed state change that the lifecycle forbids.
    sig = gt.get("state_signal")
    if sig:
        try:
            nxt = ROState(sig)
            if nxt != snap.state and not is_legal(snap.state, nxt):
                out.append({"kind": "ILLEGAL_TRANSITION",
                            "detail": reason_illegal(snap.state, nxt),
                            "evidence": snap.event_ids[-2:]})
        except ValueError:
            pass
    return out


def reconcile(con, ro_number: str, gt: dict, actor_id: str,
              at: datetime | None = None, update_id: str | None = None,
              accept_conflicts: bool = False) -> Reconciliation:
    """Fold current state, detect conflicts, then emit events for the update."""
    at = at or datetime.now()
    ro = dbm.get_ro(con, ro_number)
    if not ro:
        return Reconciliation(ro_number, False,
                              clarifications=[f"No repair order {ro_number} on file."])
    evs = dbm.events_for_ro(con, ro_number)
    before = fold(evs, promised_time=datetime.fromisoformat(ro["promised_time"])) if evs else None
    if before is None:
        return Reconciliation(ro_number, False, clarifications=["No history for this RO."])

    conflicts = _detect_conflicts(before, gt)
    blocking = [c for c in conflicts if c["kind"] in ("AUTH_CONFLICT", "ILLEGAL_TRANSITION")]
    if blocking and not accept_conflicts:
        return Reconciliation(ro_number, False, conflicts=conflicts, before=before,
                              clarifications=[c["detail"] for c in blocking])

    shift = "MORNING" if 6 <= at.hour < 14 else "AFTERNOON"
    new: list[Event] = []

    def add(t, payload):
        new.append(Event(ro_number, t, at, actor_id, payload,
                         source_update_id=update_id, shift=shift))

    if update_id:
        add(E.UPDATE_POSTED, {"chars": len(gt.get("_text", ""))})
    for o in gt.get("completed") or []:
        add(E.OP_COMPLETED, {"op_code": o["op_code"], "actual_hrs": o.get("actual_hrs")})
    for o in gt.get("pending") or []:
        add(E.OP_PENDING, {"op_code": o["op_code"]})
    for o in gt.get("correction") or []:
        if o.get("status") == "RECOMMENDED":
            add(E.OP_RECOMMENDED, {"op_code": o["op_code"]})
    for p in gt.get("parts") or []:
        add(E.PARTS_ORDERED, {"part_no": p["part_no"],
                              "availability": p.get("availability", "NEXT_DAY"),
                              "op_code": p.get("op_code")})
    for m in gt.get("measurements") or []:
        add(E.MEASUREMENT_TAKEN, m)
    if gt.get("dtc_codes"):
        add(E.DTC_RECORDED, {"codes": gt["dtc_codes"]})
    sig = gt.get("state_signal")
    if sig:
        try:
            nxt = ROState(sig)
            if nxt != before.state and is_legal(before.state, nxt):
                add(E.STATE_CHANGED, {"from": before.state.value, "to": nxt.value})
        except ValueError:
            pass

    dbm.insert_events(con, new)
    con.commit()
    after = fold(dbm.events_for_ro(con, ro_number),
                 promised_time=datetime.fromisoformat(ro["promised_time"]))
    return Reconciliation(ro_number, True, new, conflicts, [], before, after)
