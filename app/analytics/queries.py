"""Deterministic queries over the event log.

Everything the agent will ever state as fact is computed HERE, in Python, and
returned with the event ids that produced it. The LLM narrates these results;
it never counts, never infers state, never does arithmetic.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any
import json

from app.state import db as dbm
from app.state.engine import fold, ROSnapshot
from app.state.transitions import ROState, BLOCKING_STATES
from app.data.catalog import OP_BY_CODE


def _snapshot(con, ro_number: str) -> tuple[dict, ROSnapshot] | tuple[None, None]:
    ro = dbm.get_ro(con, ro_number)
    if not ro:
        return None, None
    evs = dbm.events_for_ro(con, ro_number)
    if not evs:
        return ro, None
    return ro, fold(evs, promised_time=datetime.fromisoformat(ro["promised_time"]))


def _vehicle(ro: dict) -> str:
    return f"{ro['model_year']} {ro['make']} {ro['model']}"


def get_ro_state(con, ro_number: str, now: datetime | None = None) -> dict[str, Any]:
    """Current derived state of one Repair Order, with provenance."""
    ro, snap = _snapshot(con, ro_number)
    if not ro:
        return {"found": False, "ro_number": ro_number,
                "error": f"No repair order {ro_number} on file."}
    if not snap:
        return {"found": False, "ro_number": ro_number, "error": "No events recorded."}
    now = now or datetime.now()
    return {
        "found": True, "ro_number": ro_number,
        "vehicle": _vehicle(ro), "vin": ro["vin"], "registration": ro["registration"],
        "odometer_miles": ro["odometer_miles"],
        "concern": ro["concern"], "category": ro["category"],
        "pay_type": ro["pay_type"], "wait_type": ro["wait_type"],
        "state": snap.state.value,
        "blocked": snap.is_blocked, "blocked_on": snap.blocked_on,
        "promised_time": ro["promised_time"],
        "promise_risk": snap.promise_risk(now),
        "completed": [{"op_code": o.op_code, "description": o.description,
                       "actual_hrs": o.actual_hrs, "flat_rate_hrs": o.flat_rate,
                       "by": o.by, "event_id": o.event_id} for o in snap.completed_ops],
        "pending": [{"op_code": o.op_code, "description": o.description,
                     "event_id": o.event_id} for o in snap.pending_ops],
        "recommended": [{"op_code": o.op_code, "description": o.description,
                         "event_id": o.event_id} for o in snap.recommended_ops],
        "parts": snap.parts, "dtc_codes": snap.dtcs,
        "safety_flags": [f for f in snap.safety_flags if not f.get("resolved")],
        "conflicts": [{"kind": c.kind, "detail": c.detail, "evidence": c.evidence}
                      for c in snap.conflicts],
        "hours_booked": snap.hours_booked, "flat_rate_total": snap.flat_rate_total,
        "proficiency": snap.proficiency, "comebacks": snap.comebacks,
        "last_update_at": snap.last_update_at.isoformat() if snap.last_update_at else None,
        "last_actor": snap.last_actor,
        "citations": snap.event_ids[-12:],
    }


def get_ro_timeline(con, ro_number: str, limit: int = 40) -> dict[str, Any]:
    """Chronological history: updates as written, plus the events they produced."""
    ro = dbm.get_ro(con, ro_number)
    if not ro:
        return {"found": False, "error": f"No repair order {ro_number} on file."}
    rows = con.execute(
        "SELECT u.update_id, u.at, u.shift, u.text, u.staff_id, s.name, s.role "
        "FROM updates u LEFT JOIN staff s ON s.staff_id=u.staff_id "
        "WHERE u.ro_number=? ORDER BY u.at", (ro_number,)).fetchall()
    return {"found": True, "ro_number": ro_number, "vehicle": _vehicle(ro),
            "entries": [{"update_id": r["update_id"], "at": r["at"], "shift": r["shift"],
                         "by": r["name"] or r["staff_id"], "role": r["role"],
                         "text": r["text"]} for r in rows[-limit:]]}


def list_ros(con, filter: str = "active", limit: int = 50,
             now: datetime | None = None) -> dict[str, Any]:
    """Filter the shop. filter: active|blocked|at_risk|safety|waiter|all|<state>."""
    now = now or datetime.now()
    out = []
    for ro_no in dbm.all_ro_numbers(con):
        ro, snap = _snapshot(con, ro_no)
        if not snap:
            continue
        risk = snap.promise_risk(now)
        rec = {"ro_number": ro_no, "vehicle": _vehicle(ro), "state": snap.state.value,
               "blocked": snap.is_blocked, "blocked_on": snap.blocked_on,
               "promise_risk": risk, "promised_time": ro["promised_time"],
               "wait_type": ro["wait_type"], "pay_type": ro["pay_type"],
               "safety": snap.has_open_safety, "concern": ro["concern"],
               # The REASON, not just the flag. Without this an answer can only
               # say "has a safety concern" or, worse, borrow the concern text.
               "safety_detail": [f["detail"] for f in snap.safety_flags
                                 if not f.get("resolved")],
               "registration": ro["registration"],
               "pending": [o.description for o in snap.pending_ops],
               "pending_count": len(snap.pending_ops), "last_actor": snap.last_actor}
        f = filter.lower()
        keep = (
            f == "all"
            or (f == "active" and snap.state not in (ROState.INVOICED,))
            or (f == "blocked" and snap.is_blocked)
            or (f == "at_risk" and risk in ("AT_RISK", "BREACHED"))
            or (f == "safety" and snap.has_open_safety and snap.state != ROState.INVOICED)
            or (f == "waiter" and ro["wait_type"] == "WAITER" and snap.state != ROState.INVOICED)
            or (f.upper() == snap.state.value)
        )
        if keep:
            out.append(rec)
    order = {"BREACHED": 0, "AT_RISK": 1, "OK": 2}
    out.sort(key=lambda r: (not r["safety"], order.get(r["promise_risk"], 3), r["promised_time"]))
    # `shown` lets an answer state truncation honestly instead of implying
    # that `count` rows follow.
    return {"filter": filter, "count": len(out), "shown": len(out[:limit]),
            "ros": out[:limit]}


def get_technician_activity(con, staff_id: str, days: int = 7,
                            now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    since = (now - timedelta(days=days)).isoformat()
    person = con.execute("SELECT * FROM staff WHERE staff_id=?", (staff_id,)).fetchone()
    if not person:
        return {"found": False, "error": f"No staff member {staff_id}."}
    rows = con.execute(
        "SELECT ro_number, type, at, payload FROM events "
        "WHERE actor_id=? AND at>=? ORDER BY at", (staff_id, since)).fetchall()
    completed, hrs, flat = [], 0.0, 0.0
    for r in rows:
        if r["type"] == "OP_COMPLETED":
            p = json.loads(r["payload"]); code = p.get("op_code")
            a = p.get("actual_hrs") or 0.0
            hrs += a
            flat += (OP_BY_CODE[code].flat_rate_hrs if code in OP_BY_CODE else 0.0)
            completed.append({"ro_number": r["ro_number"], "op_code": code, "actual_hrs": a})
    n_upd = con.execute("SELECT COUNT(*) FROM updates WHERE staff_id=? AND at>=?",
                        (staff_id, since)).fetchone()[0]
    recent = con.execute(
        "SELECT update_id, ro_number, at, text FROM updates "
        "WHERE staff_id=? AND at>=? ORDER BY at DESC LIMIT 6",
        (staff_id, since)).fetchall()
    # Plain-English context, all of it already in the database. An op code means
    # nothing to a service manager; "30,000 mile service interval" does.
    for c in completed:
        op = OP_BY_CODE.get(c["op_code"])
        if op:
            c["description"] = op.description
            c["category"] = op.category
            c["safety_critical"] = bool(op.safety_critical)
            c["flat_rate_hrs"] = op.flat_rate_hrs
    ro_ctx: dict[str, Any] = {}
    for ron in sorted({c["ro_number"] for c in completed}
                      | {r["ro_number"] for r in recent}):
        v = con.execute(
            "SELECT make, model, model_year, registration, concern, "
            "promised_time, wait_type FROM ros WHERE ro_number=?", (ron,)).fetchone()
        if v:
            ro_ctx[ron] = {
                "vehicle": " ".join(str(x) for x in
                                    (v["model_year"], v["make"], v["model"]) if x),
                "registration": v["registration"], "concern": v["concern"],
                "promised_time": v["promised_time"], "wait_type": v["wait_type"]}
    cats = {}
    for c in completed:
        op = OP_BY_CODE.get(c["op_code"])
        if op: cats[op.category] = cats.get(op.category, 0) + 1
    return {"found": True, "staff_id": staff_id, "name": person["name"],
            "role": person["role"], "skill": person["skill"], "shift": person["shift"],
            "window_days": days,
            "recent_updates": [dict(r) for r in recent],
            "ro_context": ro_ctx,
            "ros_touched": len({c["ro_number"] for c in completed}),
            "ops_completed": len(completed),
            "hours_booked": round(hrs, 2), "flat_rate_earned": round(flat, 2),
            "proficiency": round(flat / hrs, 2) if hrs else None,
            "updates_posted": n_upd,
            "top_categories": sorted(cats.items(), key=lambda x: -x[1])[:4]}


def get_shift_activity(con, day_offset: int = 0, shift: str | None = None,
                       now: datetime | None = None, view: str = "people",
                       limit: int = 20, days: int = 1,
                       brief: bool = False) -> dict[str, Any]:
    """Who worked on one day - optionally one shift - and what they did.

    `updates.shift` and `events.shift` are columns, written when the work was
    logged. The shift a person worked is therefore RECORDED, not something to be
    inferred from the words they typed, so this is an exact filter. That is the
    whole reason this function exists: "who worked yesterday afternoon?" used to
    fall through to semantic search over update text, which retrieved notes
    containing the word "afternoon" and left an 8B model to guess the rest.

    day_offset 0 is today, -1 yesterday. Boundary, from the generator's
    `_shift_of`: 06:00-13:59 is MORNING and everything else AFTERNOON, so work
    logged after midnight belongs to that calendar day's afternoon shift.
    """
    now = now or datetime.now()
    # A window, not only a day. "What are the cars being worked on this week"
    # had no tool at all: this one did a single date, so the question fell
    # through to semantic search and came back with three cars out of four
    # notes. days=1 is the original behaviour exactly.
    days = max(1, int(days))
    brief = bool(brief)
    day = (now + timedelta(days=day_offset)).date().isoformat()
    first = (now + timedelta(days=day_offset - days + 1)).date().isoformat()
    shift = (shift or "").strip().upper() or None
    view = "vehicles" if str(view).lower().startswith("veh") else "people"
    if shift and shift not in ("MORNING", "AFTERNOON"):
        return {"found": False, "date": day, "shift": shift, "people": [],
                "error": f"The shop runs MORNING and AFTERNOON shifts; "
                         f"there is no {shift} shift on file."}

    where = ("WHERE date(at) BETWEEN ? AND ?"
             + (" AND upper(shift)=?" if shift else ""))
    args = (first, day, shift) if shift else (first, day)
    urows = con.execute(
        "SELECT update_id, ro_number, staff_id, at, shift, text FROM updates "
        + where + " ORDER BY at", args).fetchall()
    erows = con.execute(
        "SELECT event_id, ro_number, type, at, actor_id, shift, payload FROM events "
        + where + " AND actor_id IS NOT NULL ORDER BY at", args).fetchall()

    people: dict[str, dict] = {}

    def slot(sid: str) -> dict:
        if sid not in people:
            s = con.execute("SELECT name, role, skill, shift FROM staff "
                            "WHERE staff_id=?", (sid,)).fetchone()
            people[sid] = {
                "staff_id": sid, "name": s["name"] if s else sid,
                "role": s["role"] if s else None,
                "skill": s["skill"] if s else None,
                "assigned_shift": s["shift"] if s else None,
                "shifts_worked": [], "ros": [], "work": [], "updates": [],
                "updates_posted": 0, "ops_completed": 0, "hours_booked": 0.0,
                "first_at": None, "last_at": None}
        return people[sid]

    def seen(rec: dict, at: str, sh: str | None, ron: str | None) -> None:
        rec["first_at"] = min(x for x in (rec["first_at"], at) if x)
        rec["last_at"] = max(x for x in (rec["last_at"], at) if x)
        if sh and sh not in rec["shifts_worked"]:
            rec["shifts_worked"].append(sh)
        if ron and ron not in rec["ros"]:
            rec["ros"].append(ron)

    for r in urows:
        rec = slot(r["staff_id"])
        rec["updates_posted"] += 1
        rec["updates"].append({"update_id": r["update_id"],
                               "ro_number": r["ro_number"],
                               "at": r["at"], "text": r["text"]})
        seen(rec, r["at"], r["shift"], r["ro_number"])

    for r in erows:
        rec = slot(r["actor_id"])
        seen(rec, r["at"], r["shift"], r["ro_number"])
        if r["type"] != "OP_COMPLETED":
            continue
        pl = json.loads(r["payload"])
        code = pl.get("op_code")
        hrs = pl.get("actual_hrs") or 0.0
        op = OP_BY_CODE.get(code)
        rec["ops_completed"] += 1
        rec["hours_booked"] = round(rec["hours_booked"] + hrs, 2)
        rec["work"].append({"ro_number": r["ro_number"], "op_code": code,
                            "description": op.description if op else code,
                            "category": op.category if op else None,
                            "safety_critical": bool(op.safety_critical) if op else False,
                            "actual_hrs": hrs, "event_id": r["event_id"]})

    # Busiest first: a manager asking who worked wants the people who did the
    # most work named first, not alphabetical order.
    ordered = sorted(people.values(), key=lambda p: (-p["ops_completed"],
                                                     -p["updates_posted"],
                                                     str(p["name"])))
    for p in ordered:
        p["updates"] = p["updates"][-4:]        # the latest notes, not all of them
    ros = sorted({x for p in ordered for x in p["ros"]})
    ctx: dict[str, Any] = {}
    for ron in ros:
        v = con.execute("SELECT make, model, model_year, registration, concern "
                        "FROM ros WHERE ro_number=?", (ron,)).fetchone()
        if v:
            ctx[ron] = {"vehicle": " ".join(str(x) for x in
                                            (v["model_year"], v["make"], v["model"]) if x),
                        "registration": v["registration"], "concern": v["concern"]}
    cits = ([r["update_id"] for r in urows]
            + [w["event_id"] for p in ordered for w in p["work"]])
    # Grouped by vehicle, over EVERY person in the window - not just the ones
    # the people view shows. Doing this in the renderer would silently drop the
    # work of anyone past the display cap, and the answer would look complete.
    by_ro: dict[str, Any] = {}
    for p in ordered:
        for w in p["work"]:
            r = by_ro.setdefault(w["ro_number"], {
                "ro_number": w["ro_number"], "ops": [], "people": [],
                "ops_completed": 0, "hours_booked": 0.0, "safety": False})
            r["ops"].append({"description": w["description"],
                             "actual_hrs": w["actual_hrs"],
                             "safety_critical": w["safety_critical"],
                             "by": p["name"]})
            if p["name"] not in r["people"]:
                r["people"].append(p["name"])
            r["ops_completed"] += 1
            r["hours_booked"] = round(r["hours_booked"] + (w["actual_hrs"] or 0), 2)
            r["safety"] = r["safety"] or bool(w["safety_critical"])
    for ron, r in by_ro.items():
        v = ctx.get(ron) or {}
        r["vehicle"] = v.get("vehicle")
        r["registration"] = v.get("registration")
        r["concern"] = v.get("concern")
    ranked = sorted(by_ro.values(),
                    key=lambda r: (not r["safety"], -r["ops_completed"],
                                   r["ro_number"]))

    # "2026-09-24" against a reader's calendar saying the 25th reads as stale.
    # The label is computed against the same clock the window was, so the answer
    # is self-consistent whether or not ASOIA_NOW is pinned.
    if days > 1:
        label = (f"the {days} days to "
                 + (now + timedelta(days=day_offset)).strftime("%d %B").lstrip("0"))
    else:
        label = {0: "today", -1: "yesterday", -2: "the day before yesterday"}.get(
            day_offset) or (now + timedelta(days=day_offset)).strftime("%A")

    # Every figure below is computed here, in the layer that is allowed to
    # compute. A renderer must never derive one - see check_grounding.
    return {"found": bool(ordered), "date": day, "day_offset": day_offset,
            "window_days": days, "from_date": first, "brief": brief,
            "day_label": label,
            "date_long": (now + timedelta(days=day_offset)).strftime("%A %d %B"),
            "view": view, "shift": shift or "ALL",
            "people_count": len(ordered), "shown": len(ordered[:limit]),
            # ros_worked counts every repair order TOUCHED in the window;
            # ros_with_ops counts those with a completed operation, which is
            # what by_ro lists. The renderer printed the first and then
            # "showing" the second, which read as a display cap and was not.
            "by_ro": ranked[:limit], "ros_with_ops": len(ranked),
            "ros_shown": len(ranked[:limit]),
            "ros_worked": len(ros),
            "updates_posted": sum(p["updates_posted"] for p in ordered),
            "ops_completed": sum(p["ops_completed"] for p in ordered),
            "hours_booked": round(sum(p["hours_booked"] for p in ordered), 2),
            "people": ordered[:limit], "ros": ros, "ro_context": ctx,
            "citations": cits[:40]}


def get_intake(con, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    """How much work came INTO the shop over a window, and what became of it.

    "How many cars came in this week" used to fall through to semantic search
    over update text, which retrieved four notes containing the word "shop" and
    left an 8B to guess - it reported four. The arrival of a vehicle is a
    recorded column, `ros.checked_in_at`, so the count is exact and the model
    never sees this question.

    Arrival is not the same as work: `get_shift_activity` answers what came
    THROUGH the shop on a day, from the updates logged against it. This answers
    what was BOOKED IN, which is the question a manager asks about demand.
    """
    now = now or datetime.now()
    days = max(1, int(days))
    since = now - timedelta(days=days)
    rows = con.execute(
        "SELECT ro_number, checked_in_at, make, model, model_year, category, "
        "       pay_type, wait_type, registration "
        "FROM ros WHERE checked_in_at >= ? AND checked_in_at <= ? "
        "ORDER BY checked_in_at", (since.isoformat(), now.isoformat())).fetchall()

    by_day: dict[str, int] = {}
    by_category: dict[str, int] = {}
    waiters = 0
    still_open = 0
    blocked = 0
    safety = 0
    citations: list[str] = []
    for r in rows:
        day = str(r["checked_in_at"])[:10]
        by_day[day] = by_day.get(day, 0) + 1
        cat = r["category"] or "Uncategorised"
        by_category[cat] = by_category.get(cat, 0) + 1
        if r["wait_type"] == "WAITER":
            waiters += 1
        _, snap = _snapshot(con, r["ro_number"])
        if not snap:
            continue
        if snap.state is not ROState.INVOICED:
            still_open += 1
            if snap.is_blocked:
                blocked += 1
            if snap.has_open_safety:
                safety += 1
        ev = dbm.events_for_ro(con, r["ro_number"])
        if ev:
            citations.append(ev[0].event_id)

    busiest = max(by_day.items(), key=lambda kv: (kv[1], kv[0])) if by_day else None
    return {
        "found": True,
        "window_days": days,
        "since": since.isoformat(timespec="minutes"),
        "until": now.isoformat(timespec="minutes"),
        "count": len(rows),
        "per_day_average": round(len(rows) / days, 1),
        "still_open": still_open,
        # Not "completed": get_ro_state returns a LIST under that name and the
        # figures block walks it, so an int here crashed every intake answer.
        "invoiced": len(rows) - still_open,
        "blocked": blocked,
        "open_safety": safety,
        "waiters": waiters,
        "busiest_day": ({"date": busiest[0], "count": busiest[1]} if busiest else None),
        "by_day": [{"date": d, "count": n} for d, n in sorted(by_day.items())],
        "by_category": [{"category": c, "count": n} for c, n in
                        sorted(by_category.items(), key=lambda kv: -kv[1])],
        "citations": citations[:40],
    }
