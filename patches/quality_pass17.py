#!/usr/bin/env python3
"""Seventeenth pass: answer the question that was asked, and say which day it is.

Run from the project root:   python3 quality_pass17.py

    Q: what cars were worked on today
    A: 45 people worked on 2026-09-24.
       Showing 20 of them, busiest first.
       **Marcus Okoro** (EMP034) - Technician ... [twenty technicians]

Two faults.

1. IT ANSWERED ABOUT PEOPLE, NOT CARS. `get_shift_activity` has exactly one
   renderer and it is organised by technician, so every question routed to it
   comes back as a roster - even one that says "cars". The right facts were in
   the payload; they were grouped by the wrong entity. A manager asking what came
   through the workshop wants a list of vehicles, each with the work done on it,
   not twenty people each with four jobs.

   The tool now takes `view`: "people" or "vehicles". The planner picks it from
   the question's own noun, and the query returns `by_ro` - grouped over EVERY
   person in the window, not just the twenty the people view shows, so the
   vehicle list is complete where a renderer-side grouping would have silently
   dropped work by the other twenty-five.

2. "TODAY" PRINTED AS A BARE DATE, AND IT LOOKED WRONG. With ASOIA_NOW pinned to
   2026-09-24, "today" correctly means the 24th - but the answer said
   "worked on 2026-09-24" while the reader's calendar said the 25th, so a right
   answer read as a stale one. The pin is what makes the demo reproducible and it
   is not the thing to change; the wording is.

   The query now returns `day_label` - "today", "yesterday", or the weekday -
   computed against the same pinned clock, and the renderer leads with it:
   "**… worked today, Thursday 24 September.**" Self-consistent, and it makes the
   pin visible instead of quietly confusing.
"""
import sys, pathlib, ast

ROOT = pathlib.Path(".")
CHANGES = []


def edit(rel, old, new, label, skip_if=None):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run from the project root")
    s = p.read_text()
    if skip_if and skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    n = s.count(old)
    if n != 1:
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.\n"
                 "      Run passes 1-16 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ==================================================== 1. the query
edit("app/analytics/queries.py",
     '''    # Every figure below is computed here, in the layer that is allowed to
    # compute. A renderer must never derive one - see check_grounding.
    return {"found": bool(ordered), "date": day, "day_offset": day_offset,
            "shift": shift or "ALL",
            "people_count": len(ordered), "shown": len(ordered[:limit]),
            "ros_worked": len(ros),''',
     '''    # Grouped by vehicle, over EVERY person in the window - not just the ones
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
    label = {0: "today", -1: "yesterday", -2: "the day before yesterday"}.get(
        day_offset) or (now + timedelta(days=day_offset)).strftime("%A")

    # Every figure below is computed here, in the layer that is allowed to
    # compute. A renderer must never derive one - see check_grounding.
    return {"found": bool(ordered), "date": day, "day_offset": day_offset,
            "day_label": label,
            "date_long": (now + timedelta(days=day_offset)).strftime("%A %d %B"),
            "view": view, "shift": shift or "ALL",
            "people_count": len(ordered), "shown": len(ordered[:limit]),
            "by_ro": ranked[:limit], "ros_shown": len(ranked[:limit]),
            "ros_worked": len(ros),''',
     "queries.py  by_ro, day_label, date_long",
     skip_if='"day_label": label')

edit("app/analytics/queries.py",
     '''def get_shift_activity(con, day_offset: int = 0, shift: str | None = None,
                       now: datetime | None = None,
                       limit: int = 20) -> dict[str, Any]:''',
     '''def get_shift_activity(con, day_offset: int = 0, shift: str | None = None,
                       now: datetime | None = None, view: str = "people",
                       limit: int = 20) -> dict[str, Any]:''',
     "queries.py  accept a view",
     skip_if='view: str = "people"')

edit("app/analytics/queries.py",
     '''    if shift and shift not in ("MORNING", "AFTERNOON"):
        return {"found": False, "date": day, "shift": shift, "people": [],''',
     '''    view = "vehicles" if str(view).lower().startswith("veh") else "people"
    if shift and shift not in ("MORNING", "AFTERNOON"):
        return {"found": False, "date": day, "shift": shift, "people": [],''',
     "queries.py  normalise the view",
     skip_if='view = "vehicles" if str(view)')


# ==================================================== 2. the tool
edit("app/agent/tools.py",
     '''def get_shift_activity(day_offset: int = 0, shift: str = "") -> dict:
    """Who worked on a day and shift, and what each of them did. day_offset 0 is
    today, -1 yesterday. shift MORNING or AFTERNOON, or omit for the whole day.
    Use for "who worked...", "who was on...", "what happened yesterday".
    """
    return Q.get_shift_activity(con(), day_offset=day_offset, shift=shift,
                                now=_now())''',
     '''def get_shift_activity(day_offset: int = 0, shift: str = "",
                       view: str = "people") -> dict:
    """What happened on a day and shift. day_offset 0 is today, -1 yesterday.
    shift MORNING or AFTERNOON, or omit for the whole day. view "people" for who
    worked, "vehicles" for which cars came through and what was done to each.
    """
    return Q.get_shift_activity(con(), day_offset=day_offset, shift=shift,
                                view=view, now=_now())''',
     "tools.py  pass the view through",
     skip_if='view: str = "people") -> dict:')

edit("app/agent/tools.py",
     '''      "shift":{"type":"string","enum":["MORNING","AFTERNOON",""]}}}}},''',
     '''      "shift":{"type":"string","enum":["MORNING","AFTERNOON",""]},
      "view":{"type":"string","enum":["people","vehicles"],
              "description":"people = who worked; vehicles = which cars"}}}}},''',
     "tools.py  schema knows about the view",
     skip_if='"view":{"type":"string"')


# ==================================================== 3. the planner picks it
edit("app/agent/agent.py",
     '''        plan.append({"name": "get_shift_activity", "args": tf})''',
     '''        # Answer about whatever the question names. "what cars were worked on
        # today" and "who worked today" hit the same tool over the same window,
        # but one wants vehicles and the other wants people - and until this,
        # both got a roster of technicians.
        args = dict(tf)
        args["view"] = ("vehicles" if re.search(
            r"\\bcars?\\b|\\bvehicles?\\b|\\bmotors?\\b|\\bjobs?\\b|\\bros?\\b"
            r"|\\brepair orders?\\b|\\bwhat came (in|through)\\b", q) else "people")
        plan.append({"name": "get_shift_activity", "args": args})''',
     "agent.py  choose the view from the question",
     skip_if='args["view"] = (')


# ============================= 3b. phrasings the trigger did not reach
# Found by this pass's own tests. "came through" and "were done" are at least as
# natural as "came in" and "was done", and missing them sent the question to
# semantic search - the exact failure pass 11 was written to stop. "Overnight"
# means the night just gone, so it belongs to yesterday's afternoon shift; it was
# landing on today's and covering the wrong twelve hours.
edit("app/agent/agent.py",
     '|\\bcame in\\b|\\bclocked\\b',
     '|\\bcame (in|through)\\b|\\bclocked\\b',
     "agent.py  'came through' reaches the shift tool",
     skip_if='|\\bcame (in|through)\\b|\\bclocked\\b')

edit("app/agent/agent.py",
     '|\\bwas done\\b", q)):',
     '|\\b(was|were) done\\b|\\bwent through\\b|\\bdid we (do|work)\\b", q)):',
     "agent.py  'were done' reaches the shift tool",
     skip_if='(was|were) done')

edit("app/agent/agent.py",
     'r"\\byesterday\\b|\\blast night\\b", q):',
     'r"\\byesterday\\b|\\blast night\\b|\\bovernight\\b", q):',
     'agent.py  overnight is last night, not tonight',
     skip_if='\\byesterday\\b|\\blast night\\b|\\bovernight\\b')

# ==================================================== 4. the renderer
edit("app/agent/agent.py",
     '''    sh = str(d.get("shift") or "ALL")
    when = (str(d.get("date")) if sh not in _SHIFT_WORDS
            else f"the {_SHIFT_WORDS[sh]} of {d.get('date')}")
    if not d.get("found"):''',
     '''    sh = str(d.get("shift") or "ALL")
    # Lead with "today"/"yesterday" and a written date. A bare ISO date read
    # against the reader's own calendar makes a correct answer look stale,
    # which is exactly what happened with ASOIA_NOW pinned a day back.
    day = ", ".join(str(x) for x in (d.get("day_label"), d.get("date_long")) if x) \\
        or str(d.get("date"))
    when = day if sh not in _SHIFT_WORDS else f"the {_SHIFT_WORDS[sh]} of {day}"
    if not d.get("found"):''',
     "agent.py  say which day in words",
     skip_if='d.get("day_label"), d.get("date_long")')

edit("app/agent/agent.py",
     '''    n = d.get("people_count")
    L = [f"**{n} {'person' if n == 1 else 'people'} worked on {when}.**"]''',
     '''    if d.get("view") == "vehicles":
        return _vehicles_summary(d, when)

    n = d.get("people_count")
    L = [f"**{n} {'person' if n == 1 else 'people'} worked {when}.**"]''',
     "agent.py  branch to the vehicle view",
     skip_if="_vehicles_summary(d, when)")

edit("app/agent/agent.py",
     '''def _shift_summary(d: dict) -> str:''',
     '''def _vehicles_summary(d: dict, when: str) -> str:
    """Which vehicles came through, and what was done to each.

    Reads `by_ro`, which the query grouped over every person in the window -
    grouping here would quietly lose the work of anyone past the display cap.
    Safety-critical jobs sort first, because that is what a manager scanning this
    list is looking for.
    """
    L = [f"**{d.get('ros_worked')} vehicles had work booked {when}**, "
         f"{_plural(d.get('ops_completed'), 'operation', 'operations')} across "
         f"{_plural(d.get('hours_booked'), 'hour', 'hours')}."]
    if d.get("ros_shown") != d.get("ros_worked"):
        L.append(f"Showing **{d.get('ros_shown')}**, safety-critical first.")

    for r in d.get("by_ro") or []:
        head = f"\\n**{r.get('ro_number')}**"
        if r.get("vehicle"):
            head += f" - {r['vehicle']}"
        if r.get("registration"):
            head += f", {r['registration']}"
        if r.get("safety"):
            head += "  **safety-critical work**"
        L.append(head)
        if r.get("concern"):
            L.append(f"- Customer reported: {r['concern']}")
        for op in (r.get("ops") or [])[:5]:
            flag = "  **safety-critical**" if op.get("safety_critical") else ""
            L.append(f"- {op.get('description')} - {op.get('actual_hrs')} hours, "
                     f"{op.get('by')}{flag}")
    L.append("\\nEvery vehicle with an operation booked in that window, taken "
             "from the shift recorded against each job.")
    return "\\n".join(L)


def _shift_summary(d: dict) -> str:''',
     "agent.py  _vehicles_summary",
     skip_if="def _vehicles_summary")


# ==================================================== verify
print("Quality pass 17:")
for c in CHANGES:
    print(c)
for f in ("app/agent/agent.py", "app/agent/tools.py", "app/analytics/queries.py"):
    ast.parse((ROOT / f).read_text())
print("\nagent.py, tools.py and queries.py all parse cleanly.")

import re, os
from datetime import datetime
os.environ.setdefault("ASOIA_NOW", "2026-09-24T20:03:00")
src = (ROOT / "app/agent/agent.py").read_text()
ns = {"re": re, "_clock": lambda: datetime.fromisoformat(os.environ["ASOIA_NOW"]),
      "RO_RE": re.compile(r"\bRO[- ]?\d{2}[- ]?\d{4,5}\b", re.I),
      "ID_RE": re.compile(r"\b(EMP|ADV|FOR|PRT|MGR)\d{3}\b", re.I)}
exec(src[src.index("_WEEKDAYS = {"):src.index("RO_RE = re.compile")], ns)
exec(src[src.index("KEYWORDS = ["):src.index("_WEEKDAYS = {")], ns)
s = src.index("def plan_keyword"); e = src.index("\ndef ", s + 5)
exec(src[s:e], ns)
plan_keyword = ns["plan_keyword"]

bad = 0
CASES = [
    ("what cars were worked on today",            0, "vehicles"),
    ("which vehicles came through yesterday",    -1, "vehicles"),
    ("what jobs were done this morning",          0, "vehicles"),
    ("who worked in the afternoon yesterday",    -1, "people"),
    ("which technicians were on duty today",      0, "people"),
    ("what happened overnight",                  -1, "people"),
]
print("\nview selection:")
for q, off, want in CASES:
    steps = [c for c in plan_keyword(q) if c["name"] == "get_shift_activity"]
    if not steps:
        bad += 1
        print(f"  WRONG   not routed to get_shift_activity  <- {q}")
        continue
    a = steps[0]["args"]
    ok = a.get("view") == want and a.get("day_offset") == off
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} view={a.get('view'):8s} "
          f"day_offset={a.get('day_offset')}  <- {q}")
    if not ok:
        print(f"           expected view={want}, day_offset={off}")

print(f"\n{bad} check(s) unexpected" if bad
      else "\nAll pass-17 routing checks behaved as expected.")
print("\nNext:  .venv/bin/python -m pytest tests/ -q")
print("Then:  .venv/bin/python scripts/verify_answers.py")
print("Then:  restart Gradio")
