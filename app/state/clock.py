"""What time is it, as far as this application is concerned.

THE PROBLEM THIS SOLVES

Nothing in this system stores state. Every derived fact - promise risk, at-risk,
"this week", which shift someone worked, what "today" means - is folded from the
event log and computed against "now". The dataset, meanwhile, is *generated*
relative to a moment and then stops moving.

So the wall clock walks away from the data. Five days after generating, with the
clock unpinned, four of the fourteen answers in scripts/verify_answers.py fail -
every one of them a time-window question, each returning nothing and citing
nothing, which the output rail then blocks:

    FAIL  What has EMP014 done this week?
    FAIL  Who worked in the afternoon yesterday?
    FAIL  Who was in this morning?
    FAIL  What happened overnight?

The workaround was to pin ASOIA_NOW on the command line and remember to move it.
A demo that needs a date typed into it correctly is a demo that will be given
wrong once.

WHAT IT DOES INSTEAD

Three sources, in order:

    1. an explicit argument           a caller that knows better
    2. ASOIA_NOW                      an operator pinning it, for reproducibility
    3. the newest event in the log    the default

Anchoring to the data means the shop is always "live" - the last thing that
happened, happened just now - so a dataset never goes stale and the pin becomes
optional rather than load-bearing. It costs 1.4 microseconds: `MAX(at)` over an
indexed column, measured over a 10,715-event log.

ASOIA_CLOCK=wall forces the wall clock back, for anyone who wants the old
behaviour or is running against live data.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta


def _env_pin() -> datetime | None:
    v = (os.environ.get("ASOIA_NOW") or "").strip()
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        # A malformed pin must not take the whole application down, and must not
        # be silently ignored either - it was typed on purpose.
        print(f"[clock] ASOIA_NOW={v!r} is not an ISO timestamp; ignoring it")
        return None


def data_now() -> datetime | None:
    """The newest event in the log, or None if there is no readable log."""
    try:
        from app.state import db as dbm
        row = dbm.connect().execute("SELECT MAX(at) FROM events").fetchone()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(row[0])
    except (TypeError, ValueError):
        return None


def now(explicit: datetime | None = None) -> datetime:
    """The application's current time. Never raises."""
    if explicit:
        return explicit
    pinned = _env_pin()
    if pinned:
        return pinned
    if (os.environ.get("ASOIA_CLOCK") or "").lower() != "wall":
        anchored = data_now()
        if anchored:
            return anchored
    return datetime.now()


def event_time(explicit: datetime | None = None) -> datetime:
    """The timestamp for a NEW event. Not the same question as `now()`.

    Reads can use the newest event as "now". Writes cannot: stamping a new event
    at exactly the time of the newest one makes every update posted in a session
    pile onto a single timestamp, and `ORDER BY at` stops meaning anything. One
    second past the last event keeps the log strictly ordered, and keeps a
    just-dictated update inside "today" as the application sees it - which is the
    whole point of anchoring, and would be lost if writes used the wall clock
    while reads used the data.
    """
    if explicit:
        return explicit
    pinned = _env_pin()
    if pinned:
        return pinned
    if (os.environ.get("ASOIA_CLOCK") or "").lower() != "wall":
        anchored = data_now()
        if anchored:
            return anchored + timedelta(seconds=1)
    return datetime.now()


def source() -> dict:
    """Which of the three the clock is using, and what the others would say.

    Reported by /health and by the review Overview, because "why does it think
    today is the 21st" is a question somebody will ask during a demo, and the
    answer should be one click away rather than a code read.
    """
    wall = datetime.now()
    pinned = _env_pin()
    anchored = data_now()
    forced_wall = (os.environ.get("ASOIA_CLOCK") or "").lower() == "wall"
    if pinned:
        which, why = "pinned", "ASOIA_NOW is set"
    elif forced_wall:
        which, why = "wall", "ASOIA_CLOCK=wall"
    elif anchored:
        which, why = "data", "the newest event in the log"
    else:
        which, why = "wall", "no events to anchor to"
    resolved = now()
    out = {"source": which, "why": why, "now": resolved.isoformat(),
           "wall_clock": wall.isoformat(),
           "newest_event": anchored.isoformat() if anchored else None,
           "pinned": pinned.isoformat() if pinned else None}
    if anchored:
        behind = (wall - anchored).total_seconds() / 86400.0
        out["data_age_days"] = round(behind, 2)
        # Worth saying out loud: this is the gap that used to break the
        # time-window questions, and on the wall clock it still would.
        out["wall_clock_would_break_time_questions"] = bool(behind > 1.0)
    return out
