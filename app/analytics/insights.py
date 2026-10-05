"""Insight analytics - computed in Python, narrated by the LLM.

The difference between a lookup ("RO-26-08165 is on parts hold") and something a
service manager can act on ("NLA part, promise already breached, customer is a
waiter - call them now"). All of that reasoning happens here, deterministically.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.state import db as dbm
from app.state.engine import fold
from app.state.transitions import ROState
from app.analytics.queries import _snapshot, _vehicle, list_ros
from app.data.catalog import OP_BY_CODE

PRIORITY = {"SAFETY": 0, "BREACHED": 1, "AT_RISK": 2, "BLOCKED": 3, "IN_FLIGHT": 4}


def _classify(snap, ro, risk) -> str:
    if snap.has_open_safety:            return "SAFETY"
    if risk == "BREACHED":              return "BREACHED"
    if risk == "AT_RISK":               return "AT_RISK"
    if snap.is_blocked:                 return "BLOCKED"
    return "IN_FLIGHT"


def _next_action(snap, ro) -> str:
    """The single concrete thing to do next. This is what makes a handover useful."""
    st = snap.state
    if snap.has_open_safety and st != ROState.INVOICED:
        f = next((f for f in snap.safety_flags if not f.get("resolved")), None)
        return f"Advise customer of safety item ({f['detail']})" if f else "Review safety finding"
    if st == ROState.AWAITING_AUTHORISATION:
        return "Chase customer for authorisation"
    if st == ROState.PARTS_HOLD:
        nla = [p for p, d in snap.parts.items() if d.get("availability") == "NLA"]
        if nla:
            return f"Part {nla[0]} is NLA - source alternative or advise customer"
        back = [p for p, d in snap.parts.items() if d.get("availability") == "BACKORDER"]
        return f"Chase backorder on {back[0]}" if back else "Chase parts ETA"
    if st == ROState.REPAIR_IN_PROGRESS:
        p = snap.pending_ops
        return f"Continue {p[0].description}" if p else "Complete repair and book to QC"
    if st == ROState.QUALITY_CONTROL:  return "Foreman QC check"
    if st == ROState.ROAD_TEST:        return "Road test and release"
    if st == ROState.READY_FOR_DELIVERY: return "Call customer - vehicle ready"
    if st == ROState.DISPATCHED:       return "Begin diagnosis"
    return "Review"


def generate_handover(con, shift: str = "AFTERNOON", now: datetime | None = None) -> dict[str, Any]:
    """Prioritised shift handover: safety first, then breached, at-risk, blocked."""
    now = now or datetime.now()
    groups: dict[str, list] = defaultdict(list)
    totals = {"open": 0, "blocked": 0, "safety": 0, "at_risk": 0, "pending_ops": 0}

    for ro_no in dbm.all_ro_numbers(con):
        ro, snap = _snapshot(con, ro_no)
        if not snap or snap.state == ROState.INVOICED:
            continue
        risk = snap.promise_risk(now)
        bucket = _classify(snap, ro, risk)
        totals["open"] += 1
        totals["blocked"] += snap.is_blocked
        totals["safety"] += snap.has_open_safety
        totals["at_risk"] += risk in ("AT_RISK", "BREACHED")
        totals["pending_ops"] += len(snap.pending_ops)
        groups[bucket].append({
            "ro_number": ro_no, "vehicle": _vehicle(ro), "state": snap.state.value,
            "concern": ro["concern"], "promise_risk": risk,
            "promised_time": ro["promised_time"], "wait_type": ro["wait_type"],
            "blocked_on": snap.blocked_on,
            "safety": [f["detail"] for f in snap.safety_flags if not f.get("resolved")],
            "next_action": _next_action(snap, ro),
            "pending": [o.description for o in snap.pending_ops],
            "citations": snap.event_ids[-5:],
        })

    ordered = {k: sorted(groups.get(k, []), key=lambda r: r["promised_time"])
               for k in sorted(groups, key=lambda k: PRIORITY.get(k, 9))}
    return {"shift": shift, "generated_at": now.isoformat(), "totals": totals,
            "groups": ordered}


def detect_anomalies(con, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    """Cross-RO patterns a person scanning one RO at a time would never see."""
    now = now or datetime.now()
    since = now - timedelta(days=days)
    parts_wait: dict[str, list] = defaultdict(list)
    repeat_vin: dict[str, list] = defaultdict(list)
    stalled, comebacks, auth_delays = [], [], []

    for ro_no in dbm.all_ro_numbers(con):
        ro, snap = _snapshot(con, ro_no)
        if not snap:
            continue
        open_ro = snap.state != ROState.INVOICED

        if open_ro:
            for part, d in snap.parts.items():
                if d.get("availability") in ("BACKORDER", "NLA", "NEXT_DAY"):
                    parts_wait[part].append(ro_no)
            if snap.last_update_at and snap.last_update_at < now - timedelta(hours=24):
                idle_h = (now - snap.last_update_at).total_seconds() / 3600
                stalled.append({"ro_number": ro_no, "vehicle": _vehicle(ro),
                                "state": snap.state.value, "idle_hours": round(idle_h, 1),
                                "last_actor": snap.last_actor})
            if snap.state == ROState.AWAITING_AUTHORISATION and snap.last_update_at:
                wait_h = (now - snap.last_update_at).total_seconds() / 3600
                if wait_h > 8:
                    auth_delays.append({"ro_number": ro_no, "vehicle": _vehicle(ro),
                                        "waiting_hours": round(wait_h, 1),
                                        "wait_type": ro["wait_type"]})
        if snap.comebacks:
            comebacks.append({"ro_number": ro_no, "vehicle": _vehicle(ro),
                              "count": snap.comebacks,
                              "detail": [c.detail for c in snap.conflicts
                                         if c.kind == "REPEAT_OP"][:1]})
        if datetime.fromisoformat(ro["checked_in_at"]) >= since:
            repeat_vin[ro["vin"]].append(ro_no)

    shared_parts = [{"part_no": p, "ro_count": len(r), "ros": r}
                    for p, r in parts_wait.items() if len(r) > 1]
    shared_parts.sort(key=lambda x: -x["ro_count"])
    repeat_visits = [{"vin": v, "visits": len(r), "ros": r}
                     for v, r in repeat_vin.items() if len(r) > 1]

    return {
        "window_days": days, "generated_at": now.isoformat(),
        "shared_part_holds": shared_parts[:10],
        "stalled_ros": sorted(stalled, key=lambda x: -x["idle_hours"])[:10],
        "authorisation_delays": sorted(auth_delays, key=lambda x: -x["waiting_hours"])[:10],
        "comebacks": comebacks[:10],
        "repeat_visits": repeat_visits[:10],
        "summary": {
            "shared_part_holds": len(shared_parts), "stalled": len(stalled),
            "auth_delays": len(auth_delays), "comebacks": len(comebacks),
            "repeat_visits": len(repeat_visits)},
    }


def diff_ro(con, ro_number: str, since_hours: int = 12,
            now: datetime | None = None) -> dict[str, Any]:
    """What changed on this RO since a point in time - the 'what changed?' answer."""
    now = now or datetime.now()
    cutoff = now - timedelta(hours=since_hours)
    ro, snap_now = _snapshot(con, ro_number)
    if not ro or not snap_now:
        return {"found": False, "error": f"No repair order {ro_number}."}
    evs = dbm.events_for_ro(con, ro_number)
    before = [e for e in evs if e.at <= cutoff]
    snap_before = fold(before, promised_time=datetime.fromisoformat(ro["promised_time"])) if before else None

    prior_ops = set(snap_before.ops) if snap_before else set()
    prior_done = {o.op_code for o in snap_before.completed_ops} if snap_before else set()
    now_done = {o.op_code for o in snap_now.completed_ops}

    return {
        "found": True, "ro_number": ro_number, "vehicle": _vehicle(ro),
        "since": cutoff.isoformat(), "window_hours": since_hours,
        "state_before": snap_before.state.value if snap_before else None,
        "state_now": snap_now.state.value,
        "state_changed": (snap_before.state != snap_now.state) if snap_before else True,
        "newly_completed": [{"op_code": c, "description": OP_BY_CODE[c].description}
                            for c in sorted(now_done - prior_done) if c in OP_BY_CODE],
        "newly_raised": [{"op_code": c, "status": snap_now.ops[c].status}
                         for c in sorted(set(snap_now.ops) - prior_ops)],
        "new_safety": [f["detail"] for f in snap_now.safety_flags
                       if f.get("event_id") not in
                       {g.get("event_id") for g in (snap_before.safety_flags if snap_before else [])}],
        "technician_changed": (snap_before.last_actor != snap_now.last_actor) if snap_before else False,
        "from_actor": snap_before.last_actor if snap_before else None,
        "to_actor": snap_now.last_actor,
        "promise_risk": snap_now.promise_risk(now),
        "citations": [e.event_id for e in evs if e.at > cutoff][:12],
    }
