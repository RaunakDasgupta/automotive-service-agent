"""Fold the event log into derived RO state, and reconcile new updates against it.

Core rule: every field below is COMPUTED here, in Python. The LLM never counts,
never infers state, never does arithmetic - it only narrates what this produces.
That is what makes the agent's figures trustworthy and its citations enforceable.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from app.state.events import Event, EventType
from app.state.transitions import ROState, is_legal, reason_illegal, BLOCKING_STATES
from app.data.catalog import OP_BY_CODE


@dataclass
class Conflict:
    kind: str
    detail: str
    evidence: list[str] = field(default_factory=list)   # event ids -> citation

    def __str__(self) -> str:
        return f"[{self.kind}] {self.detail}"


@dataclass
class OpStatus:
    op_code: str
    status: str                 # COMPLETED | PENDING | RECOMMENDED
    actual_hrs: float | None = None
    by: str | None = None
    at: datetime | None = None
    event_id: str | None = None

    @property
    def flat_rate(self) -> float | None:
        op = OP_BY_CODE.get(self.op_code)
        return op.flat_rate_hrs if op else None

    @property
    def description(self) -> str:
        op = OP_BY_CODE.get(self.op_code)
        return op.description if op else self.op_code


@dataclass
class ROSnapshot:
    """Derived state of one Repair Order at a point in time."""
    ro_number: str
    state: ROState
    ops: dict[str, OpStatus] = field(default_factory=dict)
    parts: dict[str, dict] = field(default_factory=dict)
    dtcs: list[str] = field(default_factory=list)
    measurements: list[dict] = field(default_factory=list)
    safety_flags: list[dict] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    authorised: bool = False
    promised_time: datetime | None = None
    last_update_at: datetime | None = None
    last_actor: str | None = None
    event_ids: list[str] = field(default_factory=list)
    comebacks: int = 0

    # --- derived metrics a service manager actually tracks -----------------
    @property
    def completed_ops(self) -> list[OpStatus]:
        return [o for o in self.ops.values() if o.status == "COMPLETED"]

    @property
    def pending_ops(self) -> list[OpStatus]:
        return [o for o in self.ops.values() if o.status == "PENDING"]

    @property
    def recommended_ops(self) -> list[OpStatus]:
        return [o for o in self.ops.values() if o.status == "RECOMMENDED"]

    @property
    def hours_booked(self) -> float:
        return round(sum(o.actual_hrs or 0.0 for o in self.completed_ops), 2)

    @property
    def flat_rate_total(self) -> float:
        return round(sum(o.flat_rate or 0.0 for o in self.completed_ops), 2)

    @property
    def proficiency(self) -> float | None:
        """Flat-rate hours earned / actual hours taken - the real shop metric."""
        if not self.hours_booked:
            return None
        return round(self.flat_rate_total / self.hours_booked, 2)

    @property
    def is_blocked(self) -> bool:
        return self.state in BLOCKING_STATES

    @property
    def blocked_on(self) -> str | None:
        if self.state == ROState.AWAITING_AUTHORISATION:
            return "customer authorisation"
        if self.state == ROState.PARTS_HOLD:
            waiting = [p for p, d in self.parts.items()
                       if d.get("availability") in ("NEXT_DAY", "BACKORDER", "NLA")]
            return f"parts: {', '.join(waiting)}" if waiting else "parts"
        return None

    @property
    def has_open_safety(self) -> bool:
        return any(not f.get("resolved") for f in self.safety_flags)

    def promise_risk(self, now: datetime | None = None) -> str:
        """OK | AT_RISK | BREACHED - the field a service manager looks at first."""
        if not self.promised_time:
            return "OK"
        now = now or datetime.now()
        if self.state in (ROState.READY_FOR_DELIVERY, ROState.INVOICED):
            return "OK"
        remaining = (self.promised_time - now).total_seconds() / 3600.0
        work_left = sum(o.flat_rate or 0.5 for o in self.pending_ops)
        if remaining < 0:
            return "BREACHED"
        if self.is_blocked and remaining < 4:
            return "AT_RISK"
        if work_left > remaining:
            return "AT_RISK"
        return "OK"


def fold(events: Iterable[Event], promised_time: datetime | None = None) -> ROSnapshot:
    """Rebuild current state by replaying the log. Pure function - no I/O."""
    events = sorted(events, key=lambda e: (e.at, e.event_id))
    if not events:
        raise ValueError("cannot fold an empty event log")

    snap = ROSnapshot(ro_number=events[0].ro_number, state=ROState.CHECKED_IN,
                      promised_time=promised_time)

    for ev in events:
        snap.event_ids.append(ev.event_id)
        p = ev.payload
        t = ev.type

        if t == EventType.RO_OPENED:
            snap.promised_time = snap.promised_time or p.get("promised_time")
        elif t == EventType.STATE_CHANGED:
            nxt = ROState(p["to"])
            if is_legal(snap.state, nxt):
                snap.state = nxt
            else:
                snap.conflicts.append(Conflict(
                    "ILLEGAL_TRANSITION", reason_illegal(snap.state, nxt), [ev.event_id]))
        elif t == EventType.OP_COMPLETED:
            code = p["op_code"]
            prior = snap.ops.get(code)
            if prior and prior.status == "COMPLETED":
                snap.comebacks += 1
                snap.conflicts.append(Conflict(
                    "REPEAT_OP",
                    f"{code} reported complete again - possible comeback or rework",
                    [prior.event_id or "", ev.event_id]))
            snap.ops[code] = OpStatus(code, "COMPLETED", p.get("actual_hrs"),
                                      ev.actor_id, ev.at, ev.event_id)
        elif t == EventType.OP_PENDING:
            code = p["op_code"]
            if snap.ops.get(code, OpStatus(code, "")).status != "COMPLETED":
                snap.ops[code] = OpStatus(code, "PENDING", None, ev.actor_id, ev.at, ev.event_id)
        elif t == EventType.OP_RECOMMENDED:
            code = p["op_code"]
            if code not in snap.ops:
                snap.ops[code] = OpStatus(code, "RECOMMENDED", None, ev.actor_id, ev.at, ev.event_id)
        elif t == EventType.PARTS_ORDERED:
            snap.parts[p["part_no"]] = {"availability": p.get("availability", "NEXT_DAY"),
                                        "eta": p.get("eta"), "event_id": ev.event_id,
                                        "op_code": p.get("op_code")}
        elif t == EventType.PARTS_RECEIVED:
            snap.parts.setdefault(p["part_no"], {})["availability"] = "IN_STOCK"
        elif t == EventType.AUTH_REQUESTED:
            snap.authorised = False
        elif t == EventType.AUTH_GRANTED:
            snap.authorised = True
        elif t == EventType.AUTH_DECLINED:
            snap.authorised = False
        elif t == EventType.SAFETY_FLAGGED:
            snap.safety_flags.append({**p, "event_id": ev.event_id, "resolved": False})
        elif t == EventType.MEASUREMENT_TAKEN:
            snap.measurements.append({**p, "event_id": ev.event_id})
            if p.get("out_of_spec") and p.get("safety_related"):
                snap.safety_flags.append({
                    "detail": f"{p.get('type')} {p.get('value')}{p.get('unit','')} "
                              f"below minimum {p.get('spec_min')}{p.get('unit','')}",
                    "event_id": ev.event_id, "resolved": False})
        elif t == EventType.DTC_RECORDED:
            for c in p.get("codes", []):
                if c not in snap.dtcs:
                    snap.dtcs.append(c)
        elif t == EventType.COMEBACK_LOGGED:
            snap.comebacks += 1

        if t != EventType.STATE_CHANGED:
            snap.last_update_at = ev.at
            snap.last_actor = ev.actor_id

    return snap
