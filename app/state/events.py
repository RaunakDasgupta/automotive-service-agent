"""Append-only event log. State is folded from events, never overwritten.

Two things fall out of this for free: a complete audit trail, and citation-able
provenance - every derived fact can name the event ids that produced it.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any
import json, uuid


class EventType(str, Enum):
    RO_OPENED         = "RO_OPENED"
    DISPATCHED        = "DISPATCHED"
    UPDATE_POSTED     = "UPDATE_POSTED"       # a technician 3 C's update
    OP_COMPLETED      = "OP_COMPLETED"
    OP_RECOMMENDED    = "OP_RECOMMENDED"
    OP_PENDING        = "OP_PENDING"
    PARTS_ORDERED     = "PARTS_ORDERED"
    PARTS_RECEIVED    = "PARTS_RECEIVED"
    AUTH_REQUESTED    = "AUTH_REQUESTED"
    AUTH_GRANTED      = "AUTH_GRANTED"
    AUTH_DECLINED     = "AUTH_DECLINED"
    STATE_CHANGED     = "STATE_CHANGED"
    SAFETY_FLAGGED    = "SAFETY_FLAGGED"
    QC_FAILED         = "QC_FAILED"
    MEASUREMENT_TAKEN = "MEASUREMENT_TAKEN"
    DTC_RECORDED      = "DTC_RECORDED"
    COMEBACK_LOGGED   = "COMEBACK_LOGGED"


def _new_id(prefix: str = "EV") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


@dataclass
class Event:
    ro_number: str
    type: EventType
    at: datetime
    actor_id: str                     # staff id, or SYSTEM
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: _new_id("EV"))
    source_update_id: str | None = None   # provenance for citation
    shift: str | None = None

    def to_row(self) -> tuple:
        return (self.event_id, self.ro_number, self.type.value, self.at.isoformat(),
                self.actor_id, self.shift, self.source_update_id,
                json.dumps(self.payload, default=str))

    @staticmethod
    def from_row(r) -> "Event":
        return Event(ro_number=r[1], type=EventType(r[2]), at=datetime.fromisoformat(r[3]),
                     actor_id=r[4], shift=r[5], source_update_id=r[6],
                     payload=json.loads(r[7]), event_id=r[0])

    def as_dict(self) -> dict:
        d = asdict(self); d["type"] = self.type.value; d["at"] = self.at.isoformat()
        return d
