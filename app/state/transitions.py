"""Repair Order lifecycle - the workflow a real service department runs.

Deliberately not IN_PROGRESS/COMPLETE. The states that matter operationally are
the blocking ones (AWAITING_AUTHORISATION, PARTS_HOLD) because that is where
vehicles actually sit and where the agent creates value by surfacing them.
"""
from __future__ import annotations
from enum import Enum


class ROState(str, Enum):
    CHECKED_IN             = "CHECKED_IN"
    DISPATCHED             = "DISPATCHED"
    DIAGNOSING             = "DIAGNOSING"
    ESTIMATE_PREPARED      = "ESTIMATE_PREPARED"
    AWAITING_AUTHORISATION = "AWAITING_AUTHORISATION"
    AUTHORISED             = "AUTHORISED"
    DECLINED               = "DECLINED"
    PARTS_HOLD             = "PARTS_HOLD"
    REPAIR_IN_PROGRESS     = "REPAIR_IN_PROGRESS"
    QUALITY_CONTROL        = "QUALITY_CONTROL"
    ROAD_TEST              = "ROAD_TEST"
    READY_FOR_DELIVERY     = "READY_FOR_DELIVERY"
    INVOICED               = "INVOICED"


S = ROState

# Legal transitions. Anything absent is rejected by the engine and surfaced to
# the user rather than silently applied.
LEGAL: dict[ROState, set[ROState]] = {
    S.CHECKED_IN:             {S.DISPATCHED},
    S.DISPATCHED:             {S.DIAGNOSING, S.REPAIR_IN_PROGRESS,
                               S.ESTIMATE_PREPARED},                  # menu-priced work skips diag
    S.DIAGNOSING:             {S.ESTIMATE_PREPARED, S.REPAIR_IN_PROGRESS, S.PARTS_HOLD},
    S.ESTIMATE_PREPARED:      {S.AWAITING_AUTHORISATION},
    S.AWAITING_AUTHORISATION: {S.AUTHORISED, S.DECLINED},
    S.AUTHORISED:             {S.REPAIR_IN_PROGRESS, S.PARTS_HOLD},
    S.DECLINED:               {S.READY_FOR_DELIVERY, S.INVOICED},
    S.PARTS_HOLD:             {S.REPAIR_IN_PROGRESS, S.AWAITING_AUTHORISATION},
    S.REPAIR_IN_PROGRESS:     {S.PARTS_HOLD, S.QUALITY_CONTROL,
                               S.AWAITING_AUTHORISATION},            # supplementary work found
    S.QUALITY_CONTROL:        {S.ROAD_TEST, S.REPAIR_IN_PROGRESS},   # QC fail -> back to bench
    S.ROAD_TEST:              {S.READY_FOR_DELIVERY, S.REPAIR_IN_PROGRESS},
    S.READY_FOR_DELIVERY:     {S.INVOICED},
    S.INVOICED:               set(),
}

BLOCKING_STATES = {S.AWAITING_AUTHORISATION, S.PARTS_HOLD}
TERMINAL_STATES = {S.INVOICED}
# Work that cannot legitimately begin before the customer has said yes.
REQUIRES_AUTHORISATION = {S.REPAIR_IN_PROGRESS}


def is_legal(src: ROState, dst: ROState) -> bool:
    return dst in LEGAL.get(src, set())


def reason_illegal(src: ROState, dst: ROState) -> str:
    if dst == src:
        return f"already in {src.value}"
    allowed = ", ".join(sorted(s.value for s in LEGAL.get(src, set()))) or "nothing (terminal)"
    return f"cannot move {src.value} -> {dst.value}; legal next: {allowed}"
