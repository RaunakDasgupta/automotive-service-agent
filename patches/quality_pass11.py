#!/usr/bin/env python3
"""Eleventh pass: day-and-shift questions are answered from the shift column.

Run from the project root:   python3 quality_pass11.py

THE DEFECT

    Q: who worked in the afternoon yesterday?
    A: Alex Whitfield worked in the afternoon yesterday on RO-26-08321 ...
       (Nadia Kowalski, Hassan Turner and Priya Hughes did not work in the
       afternoon yesterday; their updates were recorded at different times.)
       Matches: 4

Three separate failures in one answer.

1. NO TOOL COULD ANSWER IT. There was no tool for "who worked on day D, shift
   S", so the question fell to the catch-all `search_updates` - semantic search
   over the TEXT technicians typed. It retrieved updates whose text happened to
   contain the word "afternoon" ("handing over to afternoon"), which is not the
   same thing at all, and then asked an 8B model to work out the answer.

   Meanwhile `updates.shift` and `events.shift` are COLUMNS, populated at
   generation time by `_shift_of()`. The shift someone worked is recorded. The
   question is one WHERE clause, and the answer was reachable exactly.

2. THE MODEL INVENTED AN ABSENCE. "Nadia, Hassan and Priya did not work in the
   afternoon" cannot be established from four retrieved passages - it is a claim
   about the whole roster drawn from a keyword search. No existing check could
   catch it: it contains no invented number and no invented id, so both the
   grounding rail and verify_answers.py passed it.

3. "Matches: 4" was the retrieval candidate count, sitting directly under a
   sentence naming one person. It reads as "four people worked".

THE FIX

- `get_shift_activity(day_offset, shift)`: new deterministic query. Filters
  `updates` and `events` on `date(at)` and `shift`, groups by person, and
  returns each one's repair orders, completed operations, booked hours and the
  notes they wrote, with every figure computed in SQL.
- `_timeframe()`: parses "yesterday", "this morning", "last night", "Tuesday"
  and friends into (day_offset, shift) deterministically. Weekday names resolve
  backwards against ASOIA_NOW, so routing stays reproducible.
- Routing sends who/what-happened questions carrying a day or shift to the new
  tool, and explicitly steps aside for handover, diff and staff-id questions so
  the paths already verified keep working.
- `_shift_summary()`: renderer, so these answers now make ZERO LLM calls. This
  is the response-time half of the fix - the class went from an embedding call,
  a rerank call and a narration call to one SQL read.
- `check_negations()`: flags claims about what did NOT happen on the LLM path.
  Renderers are exempt; their negatives are read off empty lists in the payload.
- The misleading figure label is fixed.
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
                 "      Run passes 1-10 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def harness(old, new, label, skip_if):
    """Edit verify_answers.py wherever it is, and say so if it is absent.

    It is a tool rather than part of the application, so a tree without it is
    not broken - but a tree with it must keep it in step with the code it checks.
    """
    for rel in ("scripts/verify_answers.py", "verify_answers.py"):
        if (ROOT / rel).exists():
            edit(rel, old, new, f"{rel}  {label}", skip_if=skip_if)
            return
    CHANGES.append(f"  note  verify_answers.py not found - {label} not applied")


def append(rel, text, label, skip_if):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run from the project root")
    s = p.read_text()
    if skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    p.write_text(s.rstrip("\n") + "\n\n\n" + text.strip("\n") + "\n")
    CHANGES.append(f"  ok    {label}")


# ============================================================ 1. the query
append("app/analytics/queries.py", '''
def get_shift_activity(con, day_offset: int = 0, shift: str | None = None,
                       now: datetime | None = None,
                       limit: int = 20) -> dict[str, Any]:
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
    day = (now + timedelta(days=day_offset)).date().isoformat()
    shift = (shift or "").strip().upper() or None
    if shift and shift not in ("MORNING", "AFTERNOON"):
        return {"found": False, "date": day, "shift": shift, "people": [],
                "error": f"The shop runs MORNING and AFTERNOON shifts; "
                         f"there is no {shift} shift on file."}

    where = "WHERE date(at)=?" + (" AND upper(shift)=?" if shift else "")
    args = (day, shift) if shift else (day,)
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
    # Every figure below is computed here, in the layer that is allowed to
    # compute. A renderer must never derive one - see check_grounding.
    return {"found": bool(ordered), "date": day, "day_offset": day_offset,
            "shift": shift or "ALL",
            "people_count": len(ordered), "shown": len(ordered[:limit]),
            "ros_worked": len(ros),
            "updates_posted": sum(p["updates_posted"] for p in ordered),
            "ops_completed": sum(p["ops_completed"] for p in ordered),
            "hours_booked": round(sum(p["hours_booked"] for p in ordered), 2),
            "people": ordered[:limit], "ros": ros, "ro_context": ctx,
            "citations": cits[:40]}
''', "queries.py  get_shift_activity", skip_if="def get_shift_activity")


# ============================================================ 2. the tool
edit("app/agent/tools.py",
     '''TOOLS: dict[str, Callable[..., dict]] = {''',
     '''def get_shift_activity(day_offset: int = 0, shift: str = "") -> dict:
    """Who worked on a day and shift, and what each of them did. day_offset 0 is
    today, -1 yesterday. shift MORNING or AFTERNOON, or omit for the whole day.
    Use for "who worked...", "who was on...", "what happened yesterday".
    """
    return Q.get_shift_activity(con(), day_offset=day_offset, shift=shift,
                                now=_now())


TOOLS: dict[str, Callable[..., dict]] = {''',
     "tools.py  get_shift_activity wrapper",
     skip_if="def get_shift_activity")

edit("app/agent/tools.py",
     '''    "get_op_code_info": get_op_code_info,''',
     '''    "get_op_code_info": get_op_code_info,
    "get_shift_activity": get_shift_activity,''',
     "tools.py  register in TOOLS",
     skip_if='"get_shift_activity": get_shift_activity')

edit("app/agent/tools.py",
     ''' {"type":"function","function":{"name":"get_op_code_info",
  "description":get_op_code_info.__doc__,
  "parameters":{"type":"object","properties":{"op_code":{"type":"string"}},
                "required":["op_code"]}}},
]''',
     ''' {"type":"function","function":{"name":"get_op_code_info",
  "description":get_op_code_info.__doc__,
  "parameters":{"type":"object","properties":{"op_code":{"type":"string"}},
                "required":["op_code"]}}},
 {"type":"function","function":{"name":"get_shift_activity",
  "description":get_shift_activity.__doc__,
  "parameters":{"type":"object","properties":{
      "day_offset":{"type":"integer",
                    "description":"0 today, -1 yesterday, -2 the day before"},
      "shift":{"type":"string","enum":["MORNING","AFTERNOON",""]}}}}},
]''',
     "tools.py  function-calling schema",
     skip_if='"name":"get_shift_activity"')


# ============================================================ 3. time parsing
edit("app/agent/agent.py",
     '''from app.agent.tools import TOOLS, SPECS, call''',
     '''from app.agent.tools import TOOLS, SPECS, call, _now as _clock''',
     "agent.py  import the clock",
     skip_if="_now as _clock")

edit("app/agent/agent.py",
     '''RO_RE = re.compile(r"\\bRO[- ]?\\d{2}[- ]?\\d{4,5}\\b", re.I)''',
     '''_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


def _timeframe(question: str) -> dict | None:
    """Parse a day and/or shift out of the question, or return None.

    A shift is a column in the database, so a question about one must become a
    WHERE clause. Resolving it here - deterministically, and against ASOIA_NOW
    rather than the wall clock - keeps routing reproducible and testable without
    a model or a database.
    """
    q = question.lower()
    shift = None
    if re.search(r"\\bmorning\\b", q):
        shift = "MORNING"
    if re.search(r"\\bafternoon\\b|\\bevening\\b|\\blate shift\\b|\\bback shift\\b"
                 r"|\\blast night\\b|\\bovernight\\b|\\btonight\\b", q):
        shift = "AFTERNOON"

    off = None
    if re.search(r"\\bday before yesterday\\b|\\btwo days ago\\b", q):
        off = -2
    elif re.search(r"\\byesterday\\b|\\blast night\\b", q):
        off = -1
    elif re.search(r"\\btoday\\b|\\bthis morning\\b|\\bthis afternoon\\b"
                   r"|\\btonight\\b|\\bthis evening\\b|\\bright now\\b"
                   r"|\\bon (shift|duty) now\\b|\\bcurrently on\\b", q):
        off = 0
    else:
        m = re.search(r"\\b(" + "|".join(_WEEKDAYS) + r")\\b", q)
        if m:
            # The most recent such weekday, today included.
            today = _clock().weekday()
            back = (today - _WEEKDAYS[m.group(1)]) % 7
            off = -back
    if off is None and shift is None:
        return None
    tf: dict = {"day_offset": off if off is not None else 0}
    if shift:
        tf["shift"] = shift
    return tf


RO_RE = re.compile(r"\\bRO[- ]?\\d{2}[- ]?\\d{4,5}\\b", re.I)''',
     "agent.py  _timeframe parser",
     skip_if="def _timeframe")


# ============================================================ 4. routing
edit("app/agent/agent.py",
     '''    if not plan:
        plan.append({"name": "search_updates", "args": {"query": question, "k": 4}})
    return plan[:3]''',
     '''    # A question about a day or a shift is a filter on a recorded column, not a
    # semantic search over what people typed. Step aside for handover, diff and
    # staff-id questions: those already have the right tool, and "the afternoon
    # handover" names a shift without asking who worked it.
    tf = _timeframe(question)
    if (tf is not None
            and not ID_RE.search(question)
            and not any(p["name"] in ("generate_handover", "diff_ro") for p in plan)
            and re.search(r"\\bwho\\b|\\bworked?\\b|\\bworking\\b|\\bon shift\\b"
                          r"|\\bon duty\\b|\\bcame in\\b|\\bclocked\\b|\\bstaff\\b"
                          r"|\\bteam\\b|\\btechnicians?\\b|\\bactivity\\b"
                          r"|\\bhappened\\b|\\brecap\\b|\\bwas done\\b", q)):
        plan.append({"name": "get_shift_activity", "args": tf})
    if not plan:
        plan.append({"name": "search_updates", "args": {"query": question, "k": 4}})
    return plan[:3]''',
     "agent.py  route day/shift questions",
     skip_if='"name": "get_shift_activity", "args": tf')


# ============================================================ 5. the renderer
edit("app/agent/agent.py",
     '''_RENDERERS = {''',
     '''_SHIFT_WORDS = {"MORNING": "morning shift", "AFTERNOON": "afternoon shift"}


def _plural(n, one: str, many: str) -> str:
    """Print the payload's own figure, choosing the word to go with it.

    Branching on a value is not deriving one - the digit still comes straight
    from the payload, so the grounding rail has nothing to catch. "1 updates"
    is the kind of detail that makes an answer look machine-written.
    """
    return f"**{n} {one if n == 1 else many}**"


def _shift_summary(d: dict) -> str:
    """Who worked on a day or shift, and what they did.

    Exact by construction: the shift came from a column, and every figure below
    is copied from the payload rather than derived here.
    """
    sh = str(d.get("shift") or "ALL")
    when = (str(d.get("date")) if sh not in _SHIFT_WORDS
            else f"the {_SHIFT_WORDS[sh]} of {d.get('date')}")
    if not d.get("found"):
        if d.get("error"):
            return str(d["error"])
        return (f"**Nothing is recorded for {when}.** No technician posted an "
                f"update and no operation was booked in that window.\\n\\n"
                f"That is what the log contains - it is not evidence that the "
                f"workshop was closed, only that no work was logged against it.")

    n = d.get("people_count")
    L = [f"**{n} {'person' if n == 1 else 'people'} worked on {when}.**"]

    bits = []
    for key, one, many in (("ops_completed", "operation completed",
                            "operations completed"),
                           ("hours_booked", "hours booked", "hours booked"),
                           ("updates_posted", "update posted", "updates posted"),
                           ("ros_worked", "repair order touched",
                            "repair orders touched")):
        v = d.get(key)
        if v:
            bits.append(_plural(v, one, many))
    if bits:
        L.append("In that window: " + ", ".join(bits) + ".")
    if d.get("shown") != d.get("people_count"):
        L.append(f"Showing **{d.get('shown')}** of them, busiest first.")

    ctx = d.get("ro_context") or {}
    jargon: dict = {}
    for p in d.get("people") or []:
        head = f"\\n**{p.get('name')}** ({p.get('staff_id')})"
        role = _titlecase(p.get("role"))
        if role:
            head += f" - {role}"
        asg = str(p.get("assigned_shift") or "").upper()
        # Someone working outside their rostered shift is covering for another,
        # and that is exactly what a manager asking this question wants to see.
        if asg and d.get("shift") in ("MORNING", "AFTERNOON") and asg != d.get("shift"):
            head += f", normally on the {asg.lower()} shift"
        L.append(head)
        lo, hi = _when(p.get("first_at")), _when(p.get("last_at"))
        if lo and hi and lo == hi:
            L.append(f"- One entry, at {hi[11:]}")
        elif lo and hi and lo[:10] == hi[:10]:
            L.append(f"- Logged work from {lo[11:]} to {hi[11:]}")
        elif lo and hi:
            L.append(f"- Logged work from {lo} to {hi}")
        for w in (p.get("work") or [])[:4]:
            v = ctx.get(w.get("ro_number")) or {}
            veh = f", {v['vehicle']}" if v.get("vehicle") else ""
            flag = "  **safety-critical**" if w.get("safety_critical") else ""
            L.append(f"- {w.get('description')} on {w.get('ro_number')}{veh}"
                     f" - {w.get('actual_hrs')} hours{flag}")
        if not p.get("work") and p.get("updates_posted"):
            L.append("- Posted "
                     + _plural(p.get("updates_posted"), "update", "updates")
                     + " but booked no completed operation in this window")
        for u in (p.get("updates") or [])[-1:]:
            t = " ".join(str(u.get("text") or "").split())
            if len(t) > 220:
                t = t[:220] + "..."
            jargon.update(_jargon_in(t))
            L.append(f'- Last note, {u.get("ro_number")} '
                     f'[{u.get("update_id")}]: "{t}"')
    if jargon:
        L.append("\\n**Shorthand used in those notes**")
        for k, v in sorted(jargon.items()):
            L.append(f"- **{k}** - {v}")
    L.append("\\nThis is everyone with work logged in that window, taken from the "
             "shift recorded on each update - not from a text search.")
    return "\\n".join(L)


_RENDERERS = {''',
     "agent.py  _shift_summary renderer",
     skip_if="def _shift_summary")

edit("app/agent/agent.py",
     '''    "diff_ro":                 _diff_summary,
}''',
     '''    "diff_ro":                 _diff_summary,
    "get_shift_activity":      _shift_summary,
}''',
     "agent.py  register the renderer",
     skip_if='"get_shift_activity":      _shift_summary')


# ============================================================ 6. the negation rail
edit("app/agent/agent.py",
     '''AUTHORITY:
- You may report and advise.''',
     '''NEVER CLAIM AN ABSENCE:
- The records show what happened. They do not show what did not happen.
- Never write that a person did not work, was not involved, or was somewhere
  else, and never list who is missing from the records. If you are given four
  updates, say what those four show. Do not conclude that nobody else was there.

AUTHORITY:
- You may report and advise.''',
     "agent.py  SYSTEM forbids claiming an absence",
     skip_if="NEVER CLAIM AN ABSENCE")

edit("app/agent/agent.py",
     '''def _render(results: list[dict]) -> str:''',
     '''_NEG_RE = re.compile(
    r"\\b(did not work|did not|didn't|were not|weren't|was not|wasn't|"
    r"no one|no-one|nobody|none of (them|the)|"
    r"nothing (else )?(was|happened)|neither)\\b", re.I)


def check_negations(text: str) -> list[str]:
    """Flag claims about what did NOT happen.

    Absence from the records is not evidence of absence in the workshop. Asked
    who worked one afternoon, the model answered with one name and then added
    that three other technicians "did not work in the afternoon" - a claim about
    the whole roster, drawn from four semantically retrieved passages. It carried
    no invented number and no invented id, so neither check_grounding nor the
    verification harness could see it.

    Quoted spans are excluded. A technician may perfectly well have written "the
    noise was not present on the test drive" - repeating what someone recorded is
    the opposite of inventing an absence, and flagging it would block correct
    answers on the strength of the source material.

    This runs on the LLM path only. Renderers are exempt: their negatives
    ("no blockers recorded") are read off an empty list in the payload, and are
    worded as absence from the log rather than absence in fact.
    """
    own_words = re.sub(r'"[^"]*"', ' ', text or "")
    return [f'claims something did not happen ("{m.group(0)}") - the records '
            f'cannot establish that'
            for m in list(_NEG_RE.finditer(own_words))[:3]]


def _render(results: list[dict]) -> str:''',
     "agent.py  check_negations",
     skip_if="def check_negations")

# The LLM path's copy of these three lines - the deterministic branch above has
# the same text, so the figures block is what makes this anchor unique.
edit("app/agent/agent.py",
     '''                        fig)
    ans.warnings = check_grounding(ans.text, ans.results)
    ans.grounded = not ans.warnings
    return ans''',
     '''                        fig)
    ans.warnings = check_grounding(ans.text, ans.results)
    if os.environ.get("ASOIA_NEGATION_RAIL", "1") == "1":
        ans.warnings += check_negations(ans.text)
    ans.grounded = not ans.warnings
    return ans''',
     "agent.py  run the negation rail on the LLM path",
     skip_if="ASOIA_NEGATION_RAIL")


# ============================================================ 7. figure label
edit("app/agent/agent.py",
     '''    "count":            "Matches",''',
     '''    # "Matches" sat under a sentence naming one person and read as a count of
    # people. It is the number of update texts the search returned.
    "count":            "Updates matching the search",''',
     "agent.py  unambiguous figure label",
     skip_if="Updates matching the search")


# ============================================================ 8. the empty-answer rail
# Found while testing the renderer, not by reading the code: an honest "nothing
# is recorded for that window" answer has no ids in it, so check_output replaced
# it with "I can't answer that from the records I have. no source citations." -
# which reads as a malfunction rather than an empty afternoon.
edit("app/guardrails/rails.py",
     '''def check_output(answer) -> RailResult:
    """Block an answer carrying claims the tools never produced."""
    reasons = list(getattr(answer, "warnings", []) or [])
    if not getattr(answer, "citations", None):
        reasons.append("no source citations")''',
     '''def _empty_by_construction(answer) -> bool:
    """True when the answer reports an empty result that Python composed itself.

    The citation requirement exists to catch an answer making claims the tools
    never produced. Reporting an absence - "nothing is recorded for that
    afternoon", "no vehicle is held on safety grounds" - makes no such claim and
    has nothing it could cite.

    Deliberately narrow. It applies only to the deterministic path, and only when
    every tool in the plan came back with nothing citable in it. A tool that
    returned real data and still yielded no citations is exactly the bug this
    rail was written for - that was how every technician question came to be
    blocked - and it still blocks.
    """
    if getattr(answer, "composed", None) != "python":
        return False
    results = getattr(answer, "results", None) or []
    if not results:
        return False
    for r in results:
        res = r.get("result") if isinstance(r, dict) else None
        if not isinstance(res, dict):
            return False
        if res.get("found") is False or res.get("error"):
            continue
        if any(isinstance(v, (list, dict)) and v for v in res.values()):
            return False        # it held data; the missing citations are a bug
    return True


def check_output(answer) -> RailResult:
    """Block an answer carrying claims the tools never produced."""
    reasons = list(getattr(answer, "warnings", []) or [])
    if not getattr(answer, "citations", None) and not _empty_by_construction(answer):
        reasons.append("no source citations")''',
     "rails.py  an empty result is not an ungrounded answer",
     skip_if="_empty_by_construction")


# ============================================================ 9. harness cases
harness('''    ("has anyone seen a whistling noise on a Passat",         "llm"),
]''',
     '''    ("has anyone seen a whistling noise on a Passat",         "llm"),
    # Day and shift questions. These fell through to semantic search over update
    # text until pass 11, and the model answered them by naming who it thought
    # had NOT been there.
    ("Who worked in the afternoon yesterday?",                "python"),
    ("Who was in this morning?",                              "python"),
    ("What happened overnight?",                              "python"),
]''',
     "day and shift cases",
     skip_if="Who worked in the afternoon yesterday")

harness('''    gate = check_output(a)
    if not gate.allowed:
        fails.append(f"rail: blocked ({gate.rail})")''',
     '''    gate = check_output(a)
    if not gate.allowed:
        fails.append(f"rail: blocked ({gate.rail})")
    # No check above can see a false claim about what did NOT happen: it carries
    # no invented number and no invented id. Asked who worked one afternoon, the
    # model once named three technicians who "did not work in the afternoon".
    from app.agent.agent import check_negations
    neg = check_negations(a.text or "")
    if neg:
        fails.append("negation: " + "; ".join(neg[:2]))''',
     "check for invented absences",
     skip_if="check_negations")


# ============================================================ verify
print("Quality pass 11:")
for c in CHANGES:
    print(c)
for f in ("app/agent/agent.py", "app/agent/tools.py", "app/analytics/queries.py"):
    ast.parse((ROOT / f).read_text())
print("\nagent.py, tools.py and queries.py all parse cleanly.")

# ------------------------------------------------- prove the time parsing
import re, os
from datetime import datetime
src = (ROOT / "app/agent/agent.py").read_text()
os.environ.setdefault("ASOIA_NOW", "2026-09-24T16:55:00")   # a Thursday
ns = {"re": re, "_clock": lambda: datetime.fromisoformat(os.environ["ASOIA_NOW"])}
s = src.index("_WEEKDAYS = {")
exec(src[s:src.index("RO_RE = re.compile")], ns)
_tf = ns["_timeframe"]

TF = [
    ("who worked in the afternoon yesterday?",   {"day_offset": -1, "shift": "AFTERNOON"}),
    ("who was on the morning shift today?",      {"day_offset": 0,  "shift": "MORNING"}),
    ("what happened last night?",                {"day_offset": -1, "shift": "AFTERNOON"}),
    ("who is on shift now?",                     {"day_offset": 0}),
    ("what was done on tuesday?",                {"day_offset": -2}),
    ("who worked the day before yesterday?",     {"day_offset": -2}),
    ("Which jobs will miss their promised time?", None),
    ("Any unusual patterns in the shop this week?", None),
]
print("\ntime parsing (ASOIA_NOW is Thursday 2026-09-24):")
bad = 0
for q, want in TF:
    got = _tf(q)
    ok = got == want
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {got}  <- {q}")
    if not ok:
        print(f"           expected {want}")

# ------------------------------------------------- prove the routing
ns2 = {"re": re, "_clock": ns["_clock"],
       "RO_RE": re.compile(r"\bRO[- ]?\d{2}[- ]?\d{4,5}\b", re.I),
       "ID_RE": re.compile(r"\b(EMP|ADV|FOR|PRT|MGR)\d{3}\b", re.I),
       "_timeframe": _tf}
exec(src[src.index("KEYWORDS = ["):src.index("_WEEKDAYS = {")], ns2)
s = src.index("def plan_keyword"); e = src.index("\ndef ", s + 5)
exec(src[s:e], ns2)
plan_keyword = ns2["plan_keyword"]

ROUTE = [
    # the question that started this pass
    ("who worked in the afternoon yesterday?",                "get_shift_activity"),
    ("who was in this morning?",                              "get_shift_activity"),
    ("what happened overnight?",                              "get_shift_activity"),
    ("which technicians were on duty today?",                 "get_shift_activity"),
    # must NOT be hijacked - these were already verified
    ("Give me the afternoon handover, worst first.",           "generate_handover"),
    ("What has EMP014 done this week?",                        "get_technician_activity"),
    ("Which vehicles cannot be released on safety grounds?",   "list_ros"),
    ("Any unusual patterns in the shop this week?",            "detect_anomalies"),
    ("has anyone seen a whistling noise on a Passat",          "search_updates"),
]
print("\nrouting:")
for q, want in ROUTE:
    tools = [c["name"] for c in plan_keyword(q)]
    ok = want in tools
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {tools}  <- {q}")
    if not ok:
        print(f"           expected {want}")

# ------------------------------------------------- prove the negation rail
exec(src[src.index("_NEG_RE = re.compile"):src.index("def _render")], ns2)
check_negations = ns2["check_negations"]
NEG = [
    ("Nadia Kowalski, Hassan Turner and Priya Hughes did not work in the "
     "afternoon yesterday.", True),
    ("Nobody was on site after 18:00.", True),
    ("Alex Whitfield completed the alternator R&R on RO-26-08321.", False),
    ("No blockers are recorded against this repair order.", False),
    # quoted source material, not the assistant's own claim
    ('Last note [UPD-1]: "C/S noise - was not present on the test drive."', False),
]
print("\nnegation rail:")
for t, should_flag in NEG:
    flagged = bool(check_negations(t))
    ok = flagged == should_flag
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {'flagged' if flagged else 'allowed'}"
          f"  <- {t[:64]}")

print(f"\n{bad} check(s) unexpected - do not restart Gradio yet" if bad
      else "\nAll pass-11 checks behaved as expected.")
print("\nNext:  .venv/bin/python scripts/verify_answers.py")
print("Then:  restart Gradio (the serving process still has the old code)")
