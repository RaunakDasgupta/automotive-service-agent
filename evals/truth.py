"""Ground truth for the accuracy benchmark, derived in SQL from the raw log.

Nothing here imports `app`. Every number is computed from the events table and
the reference tables by SQL written against the EVENT SEMANTICS - a part ordered
and not received, a measurement out of spec and safety related, the last
STATE_CHANGED - rather than by calling the fold that the agent uses. Two
implementations in two languages that agree is evidence; one implementation
checked against itself is not.

That is a claim about independence, so it is worth stating what it is not: these
queries were written after reading what the event types mean, so a
misunderstanding of the DATA would be shared by both. What they cannot share is
a bug in app/state/engine.py, which is what the accuracy benchmark exists to
catch, and section 13 records what it costs to find out too late that a check
and the thing it checks are the same code.

A disagreement is investigated, never reconciled by editing this file until it
matches.
"""
from __future__ import annotations
from datetime import datetime, timedelta

BLOCKING = ("AWAITING_AUTHORISATION", "PARTS_HOLD")

# The last STATE_CHANGED wins, ordered the way the fold orders events.
_STATE = """
SELECT ro_number, state FROM (
  SELECT ro_number, json_extract(payload, '$.to') AS state,
         ROW_NUMBER() OVER (PARTITION BY ro_number
                            ORDER BY at DESC, event_id DESC) AS rn
  FROM events WHERE type = 'STATE_CHANGED')
WHERE rn = 1
"""

# No SAFETY_FLAGGED events exist in this corpus; every safety finding is a
# measurement that came back out of spec on a safety-related check.
_SAFETY = """
SELECT DISTINCT ro_number FROM events
WHERE type = 'SAFETY_FLAGGED'
   OR (type = 'MEASUREMENT_TAKEN'
       AND json_extract(payload, '$.out_of_spec') = 1
       AND json_extract(payload, '$.safety_related') = 1)
"""

# An operation is still pending when nothing later completed that op code.
_PENDING = """
SELECT e.ro_number, json_extract(e.payload, '$.op_code') AS op_code
FROM events e
WHERE e.type IN ('OP_PENDING', 'OP_RECOMMENDED')
  AND NOT EXISTS (
    SELECT 1 FROM events c
    WHERE c.ro_number = e.ro_number AND c.type = 'OP_COMPLETED'
      AND json_extract(c.payload, '$.op_code') = json_extract(e.payload, '$.op_code')
      AND (c.at > e.at OR (c.at = e.at AND c.event_id > e.event_id)))
"""


def _states(con) -> dict[str, str]:
    return {r[0]: r[1] for r in con.execute(_STATE)}


def _safety(con) -> set[str]:
    return {r[0] for r in con.execute(_SAFETY)}


def _work_left(con) -> dict[str, float]:
    """Flat-rate hours still to do, from labour_ops rather than the catalog."""
    rates = {r[0]: (r[1] or 0.5) for r in
             con.execute("SELECT op_code, flat_rate_hrs FROM labour_ops")}
    out: dict[str, float] = {}
    for ro, code in con.execute(_PENDING):
        out[ro] = out.get(ro, 0.0) + rates.get(code, 0.5)
    return out


def _risk(con, now: datetime) -> dict[str, str]:
    st = _states(con)
    left = _work_left(con)
    risk: dict[str, str] = {}
    for ro, promised in con.execute("SELECT ro_number, promised_time FROM ros"):
        s = st.get(ro, "CHECKED_IN")
        if not promised or s in ("READY_FOR_DELIVERY", "INVOICED"):
            risk[ro] = "OK"
            continue
        remaining = (datetime.fromisoformat(promised) - now).total_seconds() / 3600.0
        if remaining < 0:
            risk[ro] = "BREACHED"
        elif s in BLOCKING and remaining < 4:
            risk[ro] = "AT_RISK"
        elif left.get(ro, 0.0) > remaining:
            risk[ro] = "AT_RISK"
        else:
            risk[ro] = "OK"
    return risk


# --- the counts each question class is answered with -----------------------
def n_safety(con) -> int:
    st = _states(con)
    return sum(1 for ro in _safety(con) if st.get(ro, "CHECKED_IN") != "INVOICED")


def n_blocked(con) -> int:
    return sum(1 for s in _states(con).values() if s in BLOCKING)


def n_at_risk(con, now) -> int:
    return sum(1 for v in _risk(con, now).values() if v in ("AT_RISK", "BREACHED"))


def n_waiter(con) -> int:
    st = _states(con)
    return sum(1 for ro, w in con.execute("SELECT ro_number, wait_type FROM ros")
               if w == "WAITER" and st.get(ro, "CHECKED_IN") != "INVOICED")


def n_arrived(con, now, days) -> int:
    since = (now - timedelta(days=days)).isoformat()
    return con.execute("SELECT count(*) FROM ros WHERE checked_in_at >= ? "
                       "AND checked_in_at <= ?", (since, now.isoformat())).fetchone()[0]


def _window(now, day_offset, days):
    last = (now + timedelta(days=day_offset)).date().isoformat()
    first = (now + timedelta(days=day_offset - days + 1)).date().isoformat()
    return first, last


def n_touched(con, now, day_offset=0, days=1) -> int:
    first, last = _window(now, day_offset, days)
    return con.execute(
        "SELECT count(*) FROM (SELECT ro_number FROM updates "
        "WHERE date(at) BETWEEN ? AND ? UNION SELECT ro_number FROM events "
        "WHERE date(at) BETWEEN ? AND ? AND actor_id IS NOT NULL)",
        (first, last, first, last)).fetchone()[0]


def n_people(con, now, day_offset=0, days=1, shift=None) -> int:
    first, last = _window(now, day_offset, days)
    sh = " AND upper(shift) = ?" if shift else ""
    a = (first, last, shift) if shift else (first, last)
    return con.execute(
        "SELECT count(*) FROM (SELECT staff_id AS who FROM updates "
        f"WHERE date(at) BETWEEN ? AND ?{sh} UNION SELECT actor_id FROM events "
        f"WHERE date(at) BETWEEN ? AND ?{sh} AND actor_id IS NOT NULL)",
        a + a).fetchone()[0]


def n_ops_by(con, staff_id, now, days=7) -> int:
    first, last = _window(now, 0, days)
    return con.execute(
        "SELECT count(*) FROM events WHERE type='OP_COMPLETED' AND actor_id=? "
        "AND date(at) BETWEEN ? AND ?", (staff_id, first, last)).fetchone()[0]


def n_shared_part_holds(con, now=None, days: int = 7) -> int:
    """Parts that more than one OPEN repair order is still waiting on.

    Took three attempts, and the two wrong ones are the point of writing this
    down. "Ordered and never received, ever" gave 46; "ordered in the last seven
    days and not received" gave 10; the quantity actually reported is neither.
    A part counts when its LATEST availability is still BACKORDER, NLA or
    NEXT_DAY - a later PARTS_RECEIVED sets it to IN_STOCK - and only on repair
    orders that are not yet invoiced. There is no window on the part at all.

    A truth function that answers a different question from the one asked is
    worse than no truth function: it fails loudly and sends you looking in the
    wrong place. Each attempt was corrected by reading what the event means, not
    by nudging the number towards the agent's.
    """
    WAITING = ("BACKORDER", "NLA", "NEXT_DAY")
    st = _states(con)
    rows = con.execute("""
        SELECT ro_number, type, json_extract(payload,'$.part_no') AS part,
               json_extract(payload,'$.availability') AS avail
        FROM events WHERE type IN ('PARTS_ORDERED', 'PARTS_RECEIVED')
        ORDER BY at, event_id
    """).fetchall()
    latest: dict[tuple, str] = {}
    for ro, typ, part, avail in rows:
        if not part:
            continue
        latest[(ro, part)] = "IN_STOCK" if typ == "PARTS_RECEIVED" else (avail or "")
    by_part: dict[str, set] = {}
    for (ro, part), avail in latest.items():
        if avail in WAITING and st.get(ro, "CHECKED_IN") != "INVOICED":
            by_part.setdefault(part, set()).add(ro)
    return sum(1 for ros in by_part.values() if len(ros) > 1)
