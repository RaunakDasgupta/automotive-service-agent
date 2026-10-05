"""Generate the synthetic service-department dataset.

Reverse generation: the structured ground truth for every update is authored
first, then the technician prose is rendered from it. Ground truth therefore
exists for 100% of updates at zero LLM cost.
"""
from __future__ import annotations
import hashlib, json, random
from datetime import datetime, timedelta, time

from app.data.catalog import (FLEET, LABOUR_OPS, OP_BY_CODE, PAY_TYPES, WAIT_TYPES)
from app.data.scenarios import SCENARIOS
from app.data.vin import build_vin
from app.data.narrate import render_update, add_noise
from app.state.events import Event, EventType as E
from app.state.transitions import ROState as S
from app.state import db as dbm

FIRST = ["Alex","Sam","Jordan","Priya","Mohammed","Chloe","Daniel","Nadia","Owen","Grace",
         "Liam","Aisha","Ryan","Tomasz","Beth","Callum","Ravi","Ellie","Marcus","Freya",
         "Joel","Harpreet","Dean","Zoe","Kieran","Amara","Scott","Lucy","Hassan","Niamh"]
LAST = ["Whitfield","Okoro","Bannerjee","Kowalski","Hughes","Mensah","Doyle","Petrov","Shah",
        "Clarke","Nowak","Abbott","Rahman","Turner","Ferreira","Lynch","Osei","Bright",
        "Mackenzie","Hollis","Varga","Dunne","Sandhu","Reeve"]

ROLES = [("SERVICE_ADVISOR", "ADV", None, 6), ("PARTS", "PRT", None, 4),
         ("FOREMAN", "FOR", "MASTER", 2), ("SHOP_MANAGER", "MGR", "MASTER", 1),
         ("TECHNICIAN", "EMP", "APPRENTICE", 6), ("TECHNICIAN", "EMP", "TECH_C", 8),
         ("TECHNICIAN", "EMP", "TECH_B", 9), ("TECHNICIAN", "EMP", "TECH_A", 7),
         ("TECHNICIAN", "EMP", "MASTER", 4), ("TECHNICIAN", "EMP", "DIAG_SPEC", 3)]

SHIFTS = {"MORNING": (time(6, 0), time(14, 0)), "AFTERNOON": (time(14, 0), time(22, 0))}
SKILL_RANK = {"APPRENTICE":0,"TECH_C":1,"TECH_B":2,"TECH_A":3,"MASTER":4,"DIAG_SPEC":4}


def make_staff(rnd: random.Random) -> list[dict]:
    staff, n = [], 0
    for role, prefix, skill, count in ROLES:
        for _ in range(count):
            n += 1
            staff.append({
                "staff_id": f"{prefix}{n:03d}",
                "name": f"{rnd.choice(FIRST)} {rnd.choice(LAST)}",
                "role": role, "skill": skill,
                "shift": rnd.choice(["MORNING", "AFTERNOON"]),
                "team": rnd.choice(["Team A", "Team B", "Team C"]),
            })
    return staff


def _part_no(prefix: str, rnd: random.Random, make: str = "", model: str = "") -> str:
    """Manufacturer-style part number, e.g. 45022-T2G-A01.

    Derived deterministically from prefix + make + model, because in a real shop
    the same part fits the same model - so one backordered SKU blocks several
    vehicles at once. That collision is exactly what the cross-RO insight finds.
    """
    h = int(hashlib.sha256(f"{prefix}|{make}|{model}".encode()).hexdigest()[:12], 16)
    mid = f"{'TSRGKB'[h % 6]}{(h // 6) % 9 + 1}{'GHKMA'[(h // 54) % 5]}"
    tail = f"{'AB'[(h // 270) % 2]}{(h // 540) % 99 + 1:02d}"
    return f"{prefix}-{mid}-{tail}"


def make_ros(rnd: random.Random, n: int, days: int, start: datetime, staff: list[dict]) -> list[dict]:
    advisors = [s["staff_id"] for s in staff if s["role"] == "SERVICE_ADVISOR"]
    techs = [s for s in staff if s["role"] == "TECHNICIAN"]
    ros = []
    for i in range(n):
        # Realistic arrival curve: Monday peak, Friday bulge, quiet weekends.
        for _ in range(40):
            day = rnd.randrange(days + 1)
            d = start + timedelta(days=day)
            w = {0: 1.0, 1: 0.8, 2: 0.8, 3: 0.85, 4: 0.95, 5: 0.35, 6: 0.05}[d.weekday()]
            if rnd.random() < w:
                break
        checked_in = d.replace(hour=rnd.choice([7,8,8,9,9,10,11,13,14,15]),
                               minute=rnd.choice([0,10,15,20,30,40,45,50]))
        make, model, wmi, engine, vds_pool = rnd.choice(FLEET)
        year = rnd.randint(2016, 2025)
        scen = rnd.choice(SCENARIOS)
        wait = rnd.choices(WAIT_TYPES, weights=[62, 18, 12, 8])[0]
        # Waiters get same-day promises; drop-offs get longer windows.
        hrs = rnd.choice([2, 3, 4]) if wait == "WAITER" else rnd.choice([6, 8, 9, 24, 30])
        pay = ("WARRANTY" if (scen[0] == "Recall" or (year >= 2023 and rnd.random() < 0.35))
               else rnd.choices(PAY_TYPES, weights=[70, 14, 10, 6])[0])
        tech = rnd.choice(techs)
        ros.append({
            "ro_number": f"RO-26-{8000+i:05d}"[:11],
            "vin": build_vin(wmi, rnd.choice(vds_pool), year, rnd.choice("ABCDEFGH"),
                             rnd.randint(100000, 999999)),
            "registration": f"{rnd.choice('ABCDEFGHJKLMNOPRSTUVWXY')}{rnd.choice('ABCDEFGHJKLMNOPRSTUVWXY')}"
                            f"{str(year)[2:]}{rnd.choice('ABCDEFGHJKLMNOPRSTUVWXYZ')}"
                            f"{rnd.choice('ABCDEFGHJKLMNOPRSTUVWXYZ')}{rnd.choice('ABCDEFGHJKLMNOPRSTUVWXYZ')}",
            "make": make, "model": model, "model_year": year, "engine": engine,
            "odometer_miles": rnd.randint(4_000, 148_000),
            "pay_type": pay, "wait_type": wait,
            "checked_in_at": checked_in.isoformat(),
            "promised_time": (checked_in + timedelta(hours=hrs)).isoformat(),
            "advisor_id": rnd.choice(advisors), "primary_tech_id": tech["staff_id"],
            "concern": scen[1], "category": scen[0],
            "_scenario": scen, "_tech": tech,
        })
    return ros



VHC_ITEMS = [
    ("tyre_tread_nsf", "mm", 1.6, (1.2, 7.5)), ("tyre_tread_osf", "mm", 1.6, (1.2, 7.5)),
    ("tyre_tread_nsr", "mm", 1.6, (1.4, 7.8)), ("tyre_tread_osr", "mm", 1.6, (1.4, 7.8)),
    ("front_pad_thickness", "mm", 3.0, (1.5, 11.0)), ("rear_pad_thickness", "mm", 3.0, (1.8, 10.0)),
    ("battery_cca", "CCA", 500.0, (320.0, 780.0)), ("coolant_strength", "degC", -25.0, (-40.0, -12.0)),
]

def _vhc(ro_no, tech_id, at, rnd, post_update, events, Event, E, _shift_of):
    """Multi-point vehicle health check - findings, advisories, red items."""
    checked = rnd.sample(VHC_ITEMS, k=rnd.randint(3, 6))
    meas, red = [], False
    for name, unit, spec_min, (lo, hi) in checked:
        val = round(rnd.uniform(lo, hi), 1 if unit != "CCA" else 0)
        oos = val < spec_min
        rec = {"type": name, "value": val, "unit": unit, "spec_min": spec_min,
               "out_of_spec": oos, "safety_related": oos and "tread" in name or oos and "pad" in name}
        meas.append(rec); red = red or rec["safety_related"]
        events.append(Event(ro_no, E.MEASUREMENT_TAKEN, at, tech_id, rec, shift=_shift_of(at)))
    advisories = []
    for m in meas:
        if m["out_of_spec"]:
            if "tread" in m["type"]:   advisories.append({"op_code": "TYR-MOUNT-BAL", "status": "RECOMMENDED"})
            elif "pad" in m["type"]:   advisories.append({"op_code": "BRK-FR-PAD", "status": "RECOMMENDED"})
            elif "battery" in m["type"]: advisories.append({"op_code": "ELE-BATT-RR", "status": "RECOMMENDED"})
    return {"concern": None, "verified": False,
            "cause": "vehicle health check carried out" if not red else
                     "vehicle health check - red items found",
            "completed": [{"op_code": "TYR-INSP-TREAD", "actual_hrs": 0.2}],
            "pending": [], "correction": advisories, "parts": [], "dtc_codes": [],
            "measurements": meas, "severity": "SAFETY_RELATED" if red else None,
            "state_signal": None}


def _shift_of(dt: datetime) -> str:
    return "MORNING" if time(6, 0) <= dt.time() < time(14, 0) else "AFTERNOON"


def simulate_ro(ro: dict, rnd: random.Random, now: datetime,
                parts_ids: list[str] | None = None,
                foreman_ids: list[str] | None = None) -> tuple[list[Event], list[dict]]:
    """Walk one RO through a realistic lifecycle, emitting events and updates."""
    cat, concern, diag_ops, repair_ops, dtcs, meas, part_prefix, safety = ro["_scenario"]
    tech, ro_no = ro["_tech"], ro["ro_number"]
    advisor = ro["advisor_id"]
    parts_clerk = rnd.choice(parts_ids) if parts_ids else advisor
    foreman = rnd.choice(foreman_ids) if foreman_ids else advisor
    t = datetime.fromisoformat(ro["checked_in_at"])
    events: list[Event] = [Event(ro_no, E.RO_OPENED, t, "SYSTEM",
                                 {"promised_time": ro["promised_time"]}, shift=_shift_of(t))]
    updates: list[dict] = []
    state = S.CHECKED_IN

    def go(to: S, at: datetime, actor: str):
        nonlocal state
        events.append(Event(ro_no, E.STATE_CHANGED, at, actor, {"from": state.value, "to": to.value},
                            shift=_shift_of(at)))
        state = to

    def emit_pending(at: datetime, actor: str, gt: dict):
        """Outstanding work named in an update must also exist in the event log,
        otherwise the engine cannot report what is still open."""
        for o in gt.get("pending") or []:
            events.append(Event(ro_no, E.OP_PENDING, at, actor,
                                {"op_code": o["op_code"]}, shift=_shift_of(at)))

    def post_update(at: datetime, actor: str, gt: dict) -> str:
        uid = f"UPD-{len(updates):05d}-{ro_no[-5:]}"
        text = add_noise(render_update(gt, rnd), rnd)
        updates.append({"update_id": uid, "ro_number": ro_no, "staff_id": actor,
                        "at": at.isoformat(), "shift": _shift_of(at),
                        "text": text, "ground_truth": gt})
        events.append(Event(ro_no, E.UPDATE_POSTED, at, actor, {"chars": len(text)},
                            source_update_id=uid, shift=_shift_of(at)))
        emit_pending(at, actor, gt)
        return uid

    t += timedelta(minutes=rnd.randint(15, 90)); go(S.DISPATCHED, t, advisor)

    # Every RO gets a vehicle health check on arrival at the bench.
    t += timedelta(minutes=rnd.randint(10, 35))
    if t <= now:
        gt_vhc = _vhc(ro_no, tech["staff_id"], t, rnd, post_update, events, Event, E, _shift_of)
        post_update(t, tech["staff_id"], gt_vhc)

    needs_diag = bool(diag_ops)
    needs_auth = ro["pay_type"] == "CUSTOMER_PAY" and cat not in ("Maintenance", "Recall")

    # ---- diagnosis -----------------------------------------------------------
    if needs_diag:
        t += timedelta(minutes=rnd.randint(10, 60)); go(S.DIAGNOSING, t, tech["staff_id"])
        gt = {"concern": concern, "verified": rnd.random() < 0.85, "cause": None,
              "completed": [], "pending": [], "correction": [], "parts": [],
              "dtc_codes": list(dtcs), "measurements": [], "severity": None,
              "state_signal": None}
        for op in diag_ops:
            fr = OP_BY_CODE[op].flat_rate_hrs
            actual = round(max(0.1, rnd.gauss(fr, fr * 0.22)), 1)
            t += timedelta(hours=actual)
            events.append(Event(ro_no, E.OP_COMPLETED, t, tech["staff_id"],
                                {"op_code": op, "actual_hrs": actual}, shift=_shift_of(t)))
            gt["completed"].append({"op_code": op, "actual_hrs": actual})
        if dtcs:
            events.append(Event(ro_no, E.DTC_RECORDED, t, tech["staff_id"],
                                {"codes": list(dtcs)}, shift=_shift_of(t)))
        for (mtype, val, unit, spec_min) in meas:
            oos = val < spec_min if "camber" not in mtype and "toe" not in mtype else abs(val) > abs(spec_min)
            rec = {"type": mtype, "value": val, "unit": unit, "spec_min": spec_min,
                   "out_of_spec": oos, "safety_related": bool(safety and oos)}
            events.append(Event(ro_no, E.MEASUREMENT_TAKEN, t, tech["staff_id"], rec, shift=_shift_of(t)))
            gt["measurements"].append(rec)
            if rec["safety_related"]:
                gt["severity"] = "SAFETY_RELATED"
        gt["cause"] = f"{concern.split(',')[0]} traced to {OP_BY_CODE[repair_ops[0]].description.lower()}"
        for op in repair_ops:
            events.append(Event(ro_no, E.OP_RECOMMENDED, t, tech["staff_id"],
                                {"op_code": op}, shift=_shift_of(t)))
            gt["correction"].append({"op_code": op, "status": "RECOMMENDED"})
        if needs_auth:
            gt["state_signal"] = "AWAITING_AUTHORISATION"
        post_update(t, tech["staff_id"], gt)

    # ---- authorisation --------------------------------------------------------
    if needs_auth:
        t += timedelta(minutes=rnd.randint(10, 40))
        if state in (S.DIAGNOSING, S.DISPATCHED):
            go(S.ESTIMATE_PREPARED, t, tech["staff_id"])
        t += timedelta(minutes=rnd.randint(5, 25)); go(S.AWAITING_AUTHORISATION, t, advisor)
        events.append(Event(ro_no, E.AUTH_REQUESTED, t, advisor, {}, shift=_shift_of(t)))
        wait_h = rnd.choices([0.5, 1.5, 3, 6, 20], weights=[30, 30, 20, 12, 8])[0]
        if wait_h >= 6 and t + timedelta(hours=4) <= now:
            t += timedelta(hours=rnd.uniform(3, 5))
            post_update(t, advisor, {
                "concern": None, "verified": False,
                "cause": "customer not reached - left voicemail, awaiting callback",
                "completed": [], "pending": [{"op_code": o} for o in repair_ops],
                "correction": [], "parts": [], "dtc_codes": [], "measurements": [],
                "severity": None, "state_signal": "AWAITING_AUTHORISATION"})
            wait_h -= 4
        t += timedelta(hours=max(0.5, wait_h))
        if t > now:                                    # still waiting - live blocked RO
            return events, updates
        if rnd.random() < 0.12:
            events.append(Event(ro_no, E.AUTH_DECLINED, t, advisor, {}, shift=_shift_of(t)))
            go(S.DECLINED, t, advisor)
            t += timedelta(minutes=30); go(S.READY_FOR_DELIVERY, t, advisor)
            if t <= now - timedelta(hours=2):
                t += timedelta(hours=1); go(S.INVOICED, t, advisor)
            return events, updates
        events.append(Event(ro_no, E.AUTH_GRANTED, t, advisor, {}, shift=_shift_of(t)))
        go(S.AUTHORISED, t, advisor)

    # ---- parts ----------------------------------------------------------------
    part_no = _part_no(part_prefix, rnd, ro["make"], ro["model"])
    # Availability is a property of the SKU, not of the individual job: when a
    # part is on backorder every vehicle needing it is held. That is what makes
    # "one order clears four repair orders" a real, findable pattern.
    _a = int(hashlib.sha256(("avail|" + part_no).encode()).hexdigest()[:8], 16) % 100
    avail = ("IN_STOCK" if _a < 62 else "NEXT_DAY" if _a < 86
             else "BACKORDER" if _a < 97 else "NLA")
    if repair_ops:
        events.append(Event(ro_no, E.PARTS_ORDERED, t, parts_clerk,
                            {"part_no": part_no, "availability": avail,
                             "op_code": repair_ops[0]}, shift=_shift_of(t)))
    if avail != "IN_STOCK":
        t += timedelta(minutes=rnd.randint(10, 45))
        if state in (S.AUTHORISED, S.DIAGNOSING):
            go(S.PARTS_HOLD, t, parts_clerk)
        gt = {"concern": None, "verified": False, "cause": None, "completed": [], "pending":
              [{"op_code": o} for o in repair_ops], "correction": [], "dtc_codes": [],
              "measurements": [], "parts": [{"part_no": part_no, "availability": avail}],
              "severity": "SAFETY_RELATED" if safety else None, "state_signal": "PARTS_HOLD"}
        post_update(t, tech["staff_id"], gt)
        delay = {"NEXT_DAY": 20, "BACKORDER": 60, "NLA": 200}[avail]
        target = t + timedelta(hours=rnd.uniform(delay * 0.6, delay * 1.4))
        while t + timedelta(hours=10) < target:        # chase notes while waiting
            t += timedelta(hours=rnd.uniform(8, 14))
            if t > now:
                return events, updates
            if rnd.random() < 0.55:
                post_update(t, rnd.choice([tech["staff_id"], parts_clerk]), {
                    "concern": None, "verified": False, "cause": None, "completed": [],
                    "pending": [{"op_code": o} for o in repair_ops], "correction": [],
                    "parts": [{"part_no": part_no, "availability": avail}],
                    "dtc_codes": [], "measurements": [],
                    "severity": "SAFETY_RELATED" if safety else None,
                    "state_signal": "PARTS_HOLD"})
        t = target
        if t > now:                                    # still on parts hold - live blocked RO
            return events, updates
        events.append(Event(ro_no, E.PARTS_RECEIVED, t, parts_clerk, {"part_no": part_no},
                            shift=_shift_of(t)))

    # ---- repair ---------------------------------------------------------------
    if state != S.REPAIR_IN_PROGRESS:
        t += timedelta(minutes=rnd.randint(10, 50)); go(S.REPAIR_IN_PROGRESS, t, tech["staff_id"])
    done, pend, batch = [], [], []
    prev_shift = _shift_of(t)
    for op in repair_ops:
        fr = OP_BY_CODE[op].flat_rate_hrs
        actual = round(max(0.2, rnd.gauss(fr * 0.95, fr * 0.2)), 1)
        t += timedelta(hours=actual)
        if t > now:
            pend.append({"op_code": op}); continue
        events.append(Event(ro_no, E.OP_COMPLETED, t, tech["staff_id"],
                            {"op_code": op, "actual_hrs": actual}, shift=_shift_of(t)))
        done.append({"op_code": op, "actual_hrs": actual})
        batch.append({"op_code": op, "actual_hrs": actual})
        # Techs log as they go. Always log on a shift change (handover), otherwise
        # log each op most of the time and occasionally batch two together.
        shift_changed = _shift_of(t) != prev_shift
        if batch and (shift_changed or rnd.random() < 0.72):
            post_update(t, tech["staff_id"], {
                "concern": None, "verified": False, "cause": None,
                "completed": batch, "pending": [], "correction": [], "parts": [],
                "dtc_codes": [], "measurements": [], "severity": None,
                "state_signal": None})
            batch = []
        prev_shift = _shift_of(t)
    if batch or pend:
        post_update(t if t <= now else now, tech["staff_id"], {
            "concern": None, "verified": False,
            "cause": None, "completed": batch, "pending": pend, "correction": [],
            "parts": [], "dtc_codes": [], "measurements": [],
            "severity": "SAFETY_RELATED" if safety and pend else None,
            "state_signal": "PARTS_HOLD" if pend else None})
    if pend or t > now:
        return events, updates

    # ---- QC, road test, delivery ------------------------------------------------
    t += timedelta(minutes=rnd.randint(10, 30)); go(S.QUALITY_CONTROL, t, foreman)
    if rnd.random() < 0.09:                            # QC failure -> rework (comeback)
        t += timedelta(minutes=rnd.randint(15, 40))
        events.append(Event(ro_no, E.QC_FAILED, t, foreman,
                            {"reason": "torque check failed on road wheel"}, shift=_shift_of(t)))
        go(S.REPAIR_IN_PROGRESS, t, tech["staff_id"])
        t += timedelta(hours=rnd.uniform(0.3, 1.2))
        if t > now: return events, updates
        post_update(t, tech["staff_id"], {
            "concern": None, "verified": False, "cause": "QC rejected - rework required",
            "completed": [{"op_code": repair_ops[0], "actual_hrs": 0.4}] if repair_ops else [],
            "pending": [], "correction": [], "parts": [], "dtc_codes": [],
            "measurements": [], "severity": None, "state_signal": None})
        go(S.QUALITY_CONTROL, t, foreman)
    t += timedelta(minutes=rnd.randint(10, 25))
    if t > now: return events, updates
    go(S.ROAD_TEST, t, tech["staff_id"])
    if rnd.random() < 0.6:
        post_update(t, foreman, {
            "concern": None, "verified": True, "cause": None,
            "completed": [{"op_code": "DIAG-ROAD-TEST", "actual_hrs": 0.3}],
            "pending": [], "correction": [], "parts": [], "dtc_codes": [],
            "measurements": [], "severity": None, "state_signal": None})
    t += timedelta(minutes=rnd.randint(15, 40))
    if t > now: return events, updates
    go(S.READY_FOR_DELIVERY, t, advisor)
    t += timedelta(hours=rnd.uniform(0.5, 8))
    if t > now: return events, updates
    go(S.INVOICED, t, advisor)
    return events, updates


def build_dataset(db_path: str = "data/generated/service.sqlite", n_ros: int = 400,
                  days: int = 14, seed: int = 20260924, now: datetime | None = None) -> dict:
    """Generate the full dataset and persist it. Returns summary stats."""
    rnd = random.Random(seed)
    now = now or datetime.now().replace(second=0, microsecond=0)
    start = now - timedelta(days=days)

    staff = make_staff(rnd)
    ros = make_ros(rnd, n_ros, days, start, staff)

    con = dbm.connect(db_path)
    dbm.init_schema(con)
    con.executescript("DELETE FROM events; DELETE FROM updates; DELETE FROM ros;"
                      " DELETE FROM staff; DELETE FROM labour_ops;")

    con.executemany("INSERT INTO staff VALUES (:staff_id,:name,:role,:skill,:shift,:team)", staff)
    con.executemany(
        "INSERT INTO labour_ops VALUES (?,?,?,?,?,?)",
        [(o.op_code, o.description, o.flat_rate_hrs, o.category, o.min_skill,
          int(o.safety_critical)) for o in LABOUR_OPS])

    parts_ids = [x['staff_id'] for x in staff if x['role'] == 'PARTS']
    foreman_ids = [x['staff_id'] for x in staff if x['role'] in ('FOREMAN', 'SHOP_MANAGER')]
    all_events, all_updates, ro_rows = [], [], []
    for ro in ros:
        events, updates = simulate_ro(ro, rnd, now, parts_ids, foreman_ids)
        all_events.extend(events)
        all_updates.extend(updates)
        ro_rows.append({k: v for k, v in ro.items() if not k.startswith("_")})

    con.executemany(
        "INSERT INTO ros VALUES (:ro_number,:vin,:registration,:make,:model,:model_year,"
        ":engine,:odometer_miles,:pay_type,:wait_type,:checked_in_at,:promised_time,"
        ":advisor_id,:primary_tech_id,:concern,:category)", ro_rows)
    dbm.insert_events(con, all_events)
    con.executemany(
        "INSERT INTO updates VALUES (?,?,?,?,?,?,?)",
        [(u["update_id"], u["ro_number"], u["staff_id"], u["at"], u["shift"], u["text"],
          json.dumps(u["ground_truth"])) for u in all_updates])
    con.commit()

    stats = {"ros": len(ro_rows), "staff": len(staff), "events": len(all_events),
             "updates": len(all_updates), "labour_ops": len(LABOUR_OPS),
             "window_days": days, "generated_at": now.isoformat(), "db": db_path}
    con.close()
    return stats


if __name__ == "__main__":
    import sys
    print(json.dumps(build_dataset(), indent=2))
