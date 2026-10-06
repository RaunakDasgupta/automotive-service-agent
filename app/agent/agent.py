"""The answering agent: route to tools, then narrate the results.

The division of labour is the whole point:
  - TOOLS compute. Every number, state, date and count comes from Python.
  - The LLM narrates. It prioritises and writes prose over tool output it is given.
It is never asked to count, infer state, or recall a fact from memory, so its
answers can be checked against the tool payload that produced them.

Routing uses NIM function calling where available, with a deterministic keyword
router as fallback so the agent still works if function calling misbehaves.
"""
from __future__ import annotations
import json, os, re
import sys as _sys
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any

from app.agent.tools import TOOLS, SPECS, call, _now as _clock

SYSTEM = """You are a service operations assistant for a vehicle workshop.

You answer from the RECORDS ONLY. They are the complete truth available to you.

GROUNDING - non-negotiable:
- Never state a number, date, state or name that is not in the records.
- Never calculate. Do not sum, average, or derive any figure. Every number you
  write must appear verbatim in the records.
- If the records do not answer the question, say plainly what is missing.

CITATIONS:
- Put ids in square brackets beside the fact they support, e.g. [RO-26-08192]
  or [UPD-00002-08167].
- Brackets contain an id and nothing else. Never put a field name, a number or
  the word RECORDS inside brackets. "[RECORDS: ops_completed: N]" is WRONG.
- Never describe the data format or name its fields in your answer. Write
  "completed N operations", never "ops_completed: N".

ANSWER THE QUESTION THAT WAS ASKED:
- Direct questions - what a person did, the state of one repair order, what
  changed - answer directly from the figures. Do NOT reorder by urgency and do
  NOT open with a safety preamble.
- Only for shift handovers and shop-wide reviews, lead with what needs action:
  safety first, then breached promises, then at-risk, then blocked work.

DIGITS - read this twice:
- Every digit you write must be copied verbatim from the records.
- If you are not certain a figure is in the records, LEAVE IT OUT. An answer
  missing a number is fine. An invented number is a failure.
- A "Figures" list is appended to your answer automatically after you finish,
  listing every figure from the records. You therefore do NOT need to enumerate
  numbers. Give at most the one or two headline figures, and keep your bullets
  qualitative.

SHAPE - follow this exactly:
- One opening sentence that answers the question directly.
- Then two to four markdown bullets describing the work in words: what kind of
  jobs, on which repair orders, and what the most recent note actually said.
- Where update text is given, quote the specific concern or correction. Do not
  flatten it into a generic phrase like "focusing on diagnostics".
- Cite ids in brackets beside the fact they support.
- No headings. No preamble. Do not restate the question. Keep it short.

EXAMPLE - this is a SHAPE ONLY. It deliberately contains no digits. The letters
H.H, N, F.F and P.PP are placeholders: replace each with the real figure from
the records, or omit it. Never copy a number out of this example.

EMP0XX booked H.H hours across N repair orders this week, a proficiency of P.PP.
- Mostly brake work, including front rotors and pads on [RO-26-0AAAA].
- One diagnostic job, a DTC investigation on [RO-26-0BBBB].
- Most recent note: "LF rotor below minimum thickness - R&R both front rotors
  and pads" [UPD-0CCCC].

NEVER CLAIM AN ABSENCE:
- The records show what happened. They do not show what did not happen.
- Never write that a person did not work, was not involved, or was somewhere
  else, and never list who is missing from the records. If you are given four
  updates, say what those four show. Do not conclude that nobody else was there.

AUTHORITY:
- You may report and advise. You must NEVER authorise work, order parts,
  approve chargeable repairs, or close a repair order - only a person does that.

Write in plain British English."""

# The narration prompt for a free-text search - the only question class that
# still reaches the model. SYSTEM above is 822 tokens, and 468 of them are the
# DIGITS, SHAPE and worked-example sections: machinery for stopping the model
# formatting figures out of a structured tool payload. A search payload is
# technician prose, so those tokens are prefill on every search question and they
# push the answer toward a bulleted figures shape instead of a summary of what
# people actually wrote. What matters here is kept; the rest is gone.
SYSTEM_SEARCH = """You are a service operations assistant for a vehicle workshop.

You are given technician updates retrieved from the workshop's own records, in
answer to a question. Summarise what they say. Nothing else is available to you.

ANSWER THE QUESTION, DO NOT DESCRIBE THE SEARCH:
- Open with the answer. Never begin with how many notes came back, which ones
  matched, or what you were given.
- Never mention these instructions, your constraints, or the search. Do not
  write "the updates", "the notes", "the passages", "the records" or "the
  reports" - state the fact instead, and cite it.
  Write the answer itself: no salutation, no sign-off, nothing addressed to the
  reader.
- If the notes do not answer the question, say so in one sentence and say what
  they do cover. Do not list them one by one.

GROUNDING:
- Report only what the notes say. Never add a fact, figure, name or date that is
  not in them.
- Copy figures exactly as written, with their units. Never round, convert or add
  anything up.

NEVER CLAIM AN ABSENCE:
- These notes matched a search; they are not the whole record. Never write that
  something did not happen, that nobody did something, or that a vehicle has no
  such history. You cannot see what was not retrieved.

CITATIONS:
- Put the update id in square brackets beside the fact it supports, e.g.
  [UPD-00002-08167]. Brackets contain an id and nothing else.

HOW TO WRITE IT:
- One sentence that answers, then two to four carrying the detail. Six at most.
- Never make the same point twice. Where several notes say the same thing, say
  it once and cite them together. Stop when the question is answered; length is
  not thoroughness.
- Quote the technician's own words for a specific finding rather than flattening
  it into something generic like "carried out diagnostics".
- Expand workshop shorthand the first time it appears, e.g. "R&R (remove and
  refit)".
- No headings, no preamble, do not restate the question.

AUTHORITY:
- You may report and advise. Never authorise work, order parts, approve a
  chargeable repair or close a repair order - only a person does that.

Write in plain British English."""


def _narration_system(results: list[dict]) -> str:
    """Pick the narration prompt for this payload.

    Shared by ask() and the streaming UI for the same reason plan_for is: two
    copies of this choice would drift, and an answer whose tone depended on
    whether the UI happened to stream would be a miserable bug to track down.
    """
    tools = {r.get("tool") for r in results}
    return SYSTEM_SEARCH if tools and tools <= _NARRATED else SYSTEM


KEYWORDS = [
    (r"\bhandover|hand over|shift (brief|summary|change)\b", "generate_handover", {}),
    (r"\banomal|pattern|unusual|stalled|stuck|comeback|repeat|more than one|"
     r"multiple (job|ro)|shared part|same part\b", "detect_anomalies", {}),
    (r"\bchanged?\b.*\b(since|last|shift)\b|what.s changed", "diff_ro", {}),
    (r"\bsafety|dangerous|unsafe|illegal\b", "list_ros", {"filter": "safety"}),
    (r"\bblocked|parts hold|waiting (on|for) parts|\bheld up\b|"
     r"\bstuck on parts\b", "list_ros", {"filter": "blocked"}),
    (r"\bat.risk|late|overdue|breach\w*|promis\w*|miss\w*\b", "list_ros", {"filter": "at_risk"}),
    (r"\bwaiter|waiting customer|customers? waiting|waiting on site|"
     r"wait(ing)? in reception\b", "list_ros", {"filter": "waiter"}),
    (r"\b(EMP|ADV|FOR|PRT|MGR)\d{3}\b", "get_technician_activity", {}),
]
_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
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
    if re.search(r"\bmorning\b", q):
        shift = "MORNING"
    if re.search(r"\bafternoon\b|\bevening\b|\blate shift\b|\bback shift\b"
                 r"|\blast night\b|\bovernight\b|\btonight\b", q):
        shift = "AFTERNOON"

    off = None
    if re.search(r"\bday before yesterday\b|\btwo days ago\b", q):
        off = -2
    elif re.search(r"\byesterday\b|\blast night\b|\bovernight\b", q):
        off = -1
    elif re.search(r"\btoday\b|\bthis morning\b|\bthis afternoon\b"
                   r"|\btonight\b|\bthis evening\b|\bright now\b"
                   r"|\bon (shift|duty) now\b|\bcurrently on\b", q):
        off = 0
    else:
        m = re.search(r"\b(" + "|".join(_WEEKDAYS) + r")\b", q)
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



_WINDOW_WORDS = [
    (r"\blast (\d+) weeks?\b|\bpast (\d+) weeks?\b", lambda m: int(m.group(1) or m.group(2)) * 7),
    (r"\blast (\d+) days?\b|\bpast (\d+) days?\b", lambda m: int(m.group(1) or m.group(2))),
    (r"\bthis month\b|\blast month\b|\bthe month\b|\bmonthly\b", lambda m: 30),
    (r"\bthis week\b|\blast week\b|\bthe week\b|\bweekly\b|\bpast week\b"
     r"|\bseven days\b|\bso far this week\b", lambda m: 7),
    (r"\btoday\b|\bso far today\b|\bthis morning\b|\bthis afternoon\b", lambda m: 1),
]


def _window_days(question: str) -> int | None:
    """How many days back the question is asking about, or None.

    Deliberately narrow. A window this routing cannot read is better answered
    over the default seven days WITH THE WINDOW STATED than answered over a
    window the asker did not mean.
    """
    q = question.lower()
    for pat, days in _WINDOW_WORDS:
        m = re.search(pat, q)
        if m:
            return max(1, days(m))
    return None


# Three different questions get asked about the same vehicles, and they are
# told apart by the VERB, not by the noun:
#
#   ARRIVAL   what was booked in        -> get_intake(days)
#   ACTIVITY  what was worked on        -> get_shift_activity(offset, days)
#   STATE     what is blocked / unsafe  -> list_ros(filter)
#
# Pass 53 told them apart by the noun - "how many" plus a vehicle word - and so
# sent "how many cars were worked on yesterday" to the intake tool over a seven
# day window, and appended a spurious intake call to "how many cars are blocked"
# as well. Both were wrong in the same way: a count is not a metric.
#
# A state question wins outright. It has already matched a filter, and there is
# nothing to count over a window.
_ARRIVAL_VERB = re.compile(
    r"\b(came|come|comes|coming|arrive|arrives|arrived|arriving) in(to)?\b"
    r"|\b(booked|dropped) (in|off)\b"
    r"|\b(take|takes|took|taken) in\b"
    r"|\bintake\b|\bhow busy\b|\bnew (jobs|ros|repair orders)\b", re.I)
# "Who came in this morning" is people arriving for a shift, not demand.
_ARRIVAL_SUBJECT = re.compile(
    r"\b(cars?|vehicles?|jobs?|ros?|repair orders?|work|motors?)\b", re.I)
_NO_SUBJECT_NEEDED = re.compile(r"\bintake\b|\bhow busy\b", re.I)

# Already answered by a filter or by one repair order; a window adds nothing.
_STATE_TOOLS = {"list_ros", "detect_anomalies", "generate_handover", "diff_ro",
                "get_technician_activity", "get_ro_state", "get_ro_timeline"}


def _is_arrival(question: str) -> bool:
    if not _ARRIVAL_VERB.search(question):
        return False
    return bool(_NO_SUBJECT_NEEDED.search(question)
                or _ARRIVAL_SUBJECT.search(question))


RO_RE = re.compile(r"\bRO[- ]?\d{2}[- ]?\d{4,5}\b", re.I)
ID_RE = re.compile(r"\b(EMP|ADV|FOR|PRT|MGR)\d{3}\b", re.I)


@dataclass
class Answer:
    question: str
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    grounded: bool = True
    warnings: list[str] = field(default_factory=list)
    route: str = "keyword"
    composed: str = "llm"                 # "python" | "llm" - which path wrote text
    compose_notes: list[str] = field(default_factory=list)


def plan_keyword(question: str) -> list[dict]:
    """Deterministic routing - no LLM. Always available."""
    q = question.lower()
    plan: list[dict] = []
    ro = RO_RE.search(question)
    if ro:
        ron = re.sub(r"[^A-Z0-9-]", "", ro.group(0).upper())
        if ron.count("-") == 0 and len(ron) >= 9:
            ron = f"{ron[:2]}-{ron[2:4]}-{ron[4:]}"
        if re.search(r"\bchanged?\b|since|last shift", q):
            plan.append({"name": "diff_ro", "args": {"ro_number": ron}})
        plan.append({"name": "get_ro_state", "args": {"ro_number": ron}})
        if re.search(r"\bhistory|timeline|said|notes?\b", q):
            plan.append({"name": "get_ro_timeline", "args": {"ro_number": ron}})
    for pat, tool, args in KEYWORDS:
        if re.search(pat, q, re.I):
            a = dict(args)
            if tool == "generate_handover":
                # "Hand over to the morning shift" was answered with the
                # afternoon handover, every time, because this call was built
                # with no arguments at all and the tool's own default is
                # AFTERNOON. Routing scored it correct: the right tool ran.
                sh = _timeframe(question) or {}
                if sh.get("shift"):
                    a["shift"] = sh["shift"]
            if tool == "get_technician_activity":
                m = ID_RE.search(question)
                if not m:
                    continue
                a["staff_id"] = m.group(0).upper()
            if tool == "diff_ro":
                if not ro:
                    continue
                a["ro_number"] = plan[0]["args"].get("ro_number") if plan else None
                if not a["ro_number"]:
                    continue
            if not any(p["name"] == tool for p in plan):
                plan.append({"name": tool, "args": a})
    # A question about a day or a shift is a filter on a recorded column, not a
    # semantic search over what people typed. Step aside for handover, diff and
    # staff-id questions: those already have the right tool, and "the afternoon
    # handover" names a shift without asking who worked it.
    answered = {c["name"] for c in plan}
    tf = _timeframe(question)
    win = _window_days(question)

    # Demand: a count over a window, not a search and not a roster.
    if (_is_arrival(question) and not (answered & _STATE_TOOLS)
            and not ID_RE.search(question) and not ro):
        plan.append({"name": "get_intake", "args": {"days": win or 7}})

    # Activity: what was worked on, over a day or a window. The window is why
    # "what are the cars being worked on this week" has a tool at all; it used
    # to reach semantic search and come back with three cars out of four notes.
    if ((tf is not None or win)
            and not (answered & _STATE_TOOLS)
            and not any(p["name"] == "get_intake" for p in plan)
            and not ID_RE.search(question)
            and re.search(r"\bwho\b|\bworked?\b|\bworking\b|\bon shift\b"
                          r"|\bon duty\b|\bcame (in|through)\b|\bclocked\b|\bstaff\b"
                          r"|\bteam\b|\btechnicians?\b|\bactivity\b"
                          r"|\bhappened\b|\brecap\b|\b(was|were) done\b|\bwent through\b|\bdid we (do|work)\b", q)):
        # Answer about whatever the question names. "what cars were worked on
        # today" and "who worked today" hit the same tool over the same window,
        # but one wants vehicles and the other wants people - and until this,
        # both got a roster of technicians.
        args = dict(tf or {"day_offset": 0})
        if win and win > 1:
            args["days"] = win
        if re.search(r"\bhow many\b|\bhow much\b", q):
            args["brief"] = True
        args["view"] = ("vehicles" if re.search(
            r"\bcars?\b|\bvehicles?\b|\bmotors?\b|\bjobs?\b|\bros?\b"
            r"|\brepair orders?\b|\bwhat came (in|through)\b", q) else "people")
        plan.append({"name": "get_shift_activity", "args": args})
    if not plan:
        plan.append({"name": "search_updates", "args": {"query": question, "k": 4}})
    return plan[:3]


def plan_llm(question: str, chat_fn) -> list[dict] | None:
    """Ask the model which tools to call. Returns None if it will not cooperate."""
    try:
        out = chat_fn([
            {"role": "system",
             "content": "Choose the tools needed to answer. Reply with JSON only: "
                        '{"calls":[{"name":"<tool>","args":{...}}]}. '
                        "Available tools:\n"
                        + "\n".join(f"- {s['function']['name']}: "
                                    f"{(s['function']['description'] or '').strip().splitlines()[0]}"
                                    for s in SPECS)},
            {"role": "user", "content": question}],
            temperature=0.0, max_tokens=300, json_mode=True)
        data = json.loads(out[out.find("{"):out.rfind("}") + 1])
        calls = [c for c in data.get("calls", []) if c.get("name") in TOOLS]
        return calls[:3] or None
    except Exception:
        return None


def _collect_citations(results: list[dict]) -> list[str]:
    cits: list[str] = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                # `ros` matters: detect_anomalies puts its repair order
                # numbers there, and without it a correct shared-part or
                # repeat-visit answer cites nothing and the rail blocks it.
                # But list_ros ALSO has a top-level `ros`, holding whole records
                # rather than ids - so only harvest when the list really is ids,
                # and otherwise walk into it for the nested ro_number.
                if (k in ("citations", "event_ids", "ros", "ro_numbers")
                        and isinstance(v, list)
                        and all(isinstance(x, str) for x in v)):
                    cits.extend(v)
                elif k in ("update_id", "event_id", "ro_number") and isinstance(v, str):
                    cits.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o[:40]:
                walk(x)
    walk(results)
    return list(dict.fromkeys(cits))[:40]


_ROUTABLE_RE = re.compile(
    r"\bro\b|repair order|job|vehicle|car|tech\w*|advisor|foreman|part|shift|"
    r"handover|promis\w*|safety|blocked|waiting|outstanding|overdue|status|state|"
    r"open|closed|invoiced", re.I)


def plan_for(question: str, chat_fn=None,
             use_llm_router: bool = True) -> tuple[list[dict], str]:
    """Decide which tools to run, and say which router decided it.

    Keyword routing runs first because the LLM router costs a whole round trip.
    It is consulted only when keyword routing found nothing more specific than
    the catch-all search AND the question names something operational. A question
    with no operational vocabulary in it at all - "has anyone seen a whistling
    noise" - gives the router nothing to route to: it returns search_updates as
    well, one round trip later, on the slowest path in the system.

    Single source of truth on purpose: ask() and the streaming UI both call this.
    """
    kw = plan_keyword(question)
    generic = len(kw) == 1 and kw[0]["name"] == "search_updates"
    routable = bool(RO_RE.search(question) or ID_RE.search(question)
                    or _timeframe(question) or _ROUTABLE_RE.search(question))
    plan = (plan_llm(question, chat_fn)
            if (use_llm_router and generic and routable) else None)
    return (plan or kw), ("llm" if plan else "keyword")


def check_grounding(text: str, results: list[dict]) -> list[str]:
    """Flag numbers and RO references in the answer that the tools never produced."""
    blob = json.dumps(results, default=str)
    warnings = []
    for ro in set(RO_RE.findall(text)):
        if ro.replace(" ", "-").upper() not in blob.upper():
            warnings.append(f"RO {ro} does not appear in tool results")
    # Decimals matter most here - booked hours are the figures a manager acts on,
    # so an invented "7.4" must not slip through a digits-only check.
    for n in set(re.findall(r"(?<![\w.-])\d+\.\d+(?![\w.-])", text)):
        if n not in blob:
            warnings.append(f"figure {n} does not appear in tool results")
    for n in set(re.findall(r"(?<![\w.-])\d{2,}(?![\w.\-\d])", text)):
        if n not in blob and n not in ("24", "26"):
            warnings.append(f"figure {n} does not appear in tool results")
    return warnings[:6]


_NEG_RE = re.compile(
    r"\b(did not work|did not|didn't|were not|weren't|was not|wasn't|"
    r"no one|no-one|nobody|none of (them|the)|"
    r"nothing (else )?(was|happened)|neither)\b", re.I)


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


def _render(results: list[dict]) -> str:
    """Tool results as labelled lines. A small model narrates this far better
    than a single-line JSON dump, and every figure stays verbatim so
    check_grounding still matches."""
    def lines(o, pad="", depth=0):
        if depth > 5:
            return pad + json.dumps(o, default=str)[:300]
        if isinstance(o, dict):
            out = []
            for k, v in o.items():
                if isinstance(v, (dict, list)) and v:
                    out.append(f"{pad}{k}:")
                    out.append(lines(v, pad + "  ", depth + 1))
                else:
                    out.append(f"{pad}{k}: {v}")
            return "\n".join(out)
        if isinstance(o, list):
            out = []
            for x in o[:25]:
                if isinstance(x, list) and not any(isinstance(y, (dict, list)) for y in x):
                    out.append(f"{pad}- " + ", ".join(str(y) for y in x))
                elif isinstance(x, (dict, list)):
                    out.append(f"{pad}-")
                    out.append(lines(x, pad + "  ", depth + 1))
                else:
                    out.append(f"{pad}- {x}")
            if len(o) > 25:
                out.append(f"{pad}... {len(o) - 25} more")
            return "\n".join(out)
        return f"{pad}{o}"

    blocks = []
    for r in results:
        args = ", ".join(f"{k}={v}" for k, v in (r.get("args") or {}).items())
        blocks.append(f"{r['tool']}({args})\n{lines(r.get('result'), '  ')}")
    return "\n\n".join(blocks)


_FIG_LABELS = {
    "ops_completed":    "Operations completed",
    "ros_touched":      "Repair orders touched",
    "hours_booked":     "Hours booked",
    "flat_rate_earned": "Flat-rate hours earned",
    "proficiency":      "Proficiency (flat-rate / actual)",
    "updates_posted":   "Updates posted",
    "window_days":      "Window (days)",
    "state":            "State",
    "days_open":        "Days open",
    "promised_at":      "Promised",
    # No "count" here. It was the number of update texts a search returned -
    # a fact about the retrieval rather than about the shop, and the only
    # figure a narrated answer ever carried. The citation footer already names
    # every source it used.
}


def _figures(results: list[dict]) -> str:
    """Render the figures deterministically from the tool output.

    Every value here is computed in Python, so it is correct and complete
    whether or not the model chose to mention it. Bounded on purpose - this
    appends a short block, not a data dump.
    """
    out: list[str] = []
    for r in results:
        res = r.get("result")
        if not isinstance(res, dict):
            continue
        if res.get("found") is False:
            continue
        for k, label in _FIG_LABELS.items():
            v = res.get(k)
            if v is None or isinstance(v, (dict, list)):
                continue
            out.append(f"- {label}: **{v}**")
        for c in (res.get("completed") or [])[:8]:
            if isinstance(c, dict) and c.get("ro_number"):
                out.append(f"- {c.get('op_code')} on [{c['ro_number']}]"
                           f" - {c.get('actual_hrs')} h")
        cats = res.get("top_categories")
        if isinstance(cats, list) and cats:
            pretty = ", ".join(f"{c[0]} ({c[1]})" for c in cats
                               if isinstance(c, (list, tuple)) and len(c) >= 2)
            if pretty:
                out.append(f"- Categories: {pretty}")
        for u in (res.get("recent_updates") or [])[:3]:
            if isinstance(u, dict) and u.get("text"):
                t = " ".join(str(u["text"]).split())
                if len(t) > 180:
                    t = t[:180] + "..."
                out.append(f'- [{u.get("update_id")}] "{t}"')
    return "\n".join(dict.fromkeys(out))


_JARGON = {
    "R&R":  "remove and refit",
    "C/S":  "customer states",
    "NSF":  "nearside front (front left)",
    "OSF":  "offside front (front right)",
    "NSR":  "nearside rear (rear left)",
    "OSR":  "offside rear (rear right)",
    "NLA":  "no longer available from the manufacturer",
    "TSB":  "technical service bulletin (a manufacturer fix notice)",
    "DTC":  "diagnostic trouble code (a stored fault code)",
    "VHC":  "vehicle health check",
    "CCA":  "cold cranking amps (a measure of battery strength)",
    "QC":   "quality control check",
    "LF":   "left front", "RF": "right front",
    "LR":   "left rear",  "RR": "right rear",
}


def _jargon_in(text: str) -> dict:
    """Trade shorthand present in the text, so a non-technical reader can follow
    the note without it being paraphrased away."""
    found = {}
    for k, v in _JARGON.items():
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])",
                     text, re.I):
            found[k] = v
    return found


def _tech_summary(d: dict) -> str:
    """The whole answer, composed from the record. Every figure is copied, never
    derived, so it is correct by construction."""
    ctx = d.get("ro_context") or {}
    L: list[str] = []

    skill = (d.get("skill") or "").replace("_", " ").title()
    shift = (d.get("shift") or "").title()
    bits = [b for b in (skill, f"{shift} shift" if shift else "") if b]
    who = f"**{d.get('name')}** ({d.get('staff_id')})"
    if bits:
        who += " - " + ", ".join(bits)
    L.append(f"{who} - completed **{d.get('ops_completed')} jobs** across "
             f"**{d.get('ros_touched')} repair orders** in the last "
             f"{d.get('window_days')} days, and posted "
             f"**{d.get('updates_posted')} updates**.")

    hrs, flat, prof = (d.get("hours_booked"), d.get("flat_rate_earned"),
                       d.get("proficiency"))
    if hrs and flat and prof:
        verdict = ("ahead of the standard allowance" if prof > 1.02 else
                   "behind the standard allowance" if prof < 0.98 else
                   "in line with the standard allowance")
        L.append(f"\nTime: **{hrs} hours** spent on work the manual allows "
                 f"**{flat} hours** for - a ratio of **{prof}**, {verdict}.")

    by_ro: dict = {}
    for c in d.get("completed") or []:
        by_ro.setdefault(c.get("ro_number"), []).append(c)
    if by_ro:
        L.append("\n**The work, by repair order**")
        for ron, ops in by_ro.items():
            v = ctx.get(ron) or {}
            head = f"\n**{ron}**"
            if v.get("vehicle"):
                head += f" - {v['vehicle']}"
                if v.get("registration"):
                    head += f", {v['registration']}"
            L.append(head)
            if v.get("concern"):
                L.append(f"- Customer reported: {v['concern']}")
            for c in ops:
                desc = c.get("description") or c.get("op_code")
                flag = "  **safety-critical**" if c.get("safety_critical") else ""
                L.append(f"- {desc} - {c.get('actual_hrs')} hours{flag}")

    notes = d.get("recent_updates") or []
    if notes:
        L.append("\n**What was written most recently**")
        jargon: dict = {}
        for u in notes[:3]:
            t = " ".join(str(u.get("text") or "").split())
            jargon.update(_jargon_in(t))
            when = str(u.get("at") or "")[:16].replace("T", " ")
            L.append(f'\n- **{when}**, {u.get("ro_number")} '
                     f'[{u.get("update_id")}]\n  "{t}"')
        if jargon:
            L.append("\n**Shorthand used in those notes**")
            for k, v in sorted(jargon.items()):
                L.append(f"- **{k}** - {v}")
    return "\n".join(L)


_RISK_WORDS = {
    "BREACHED": "promised time already missed",
    "AT_RISK":  "at risk of missing the promised time",
    "OK":       "on track",
}

_FILTER_TITLES = {
    "safety":  "cannot be released on safety grounds",
    "blocked": "are blocked and cannot progress",
    "at_risk": "are at risk of missing their promised time",
    "waiter":  "have a customer waiting on site",
    "active":  "are currently open",
    "all":     "are on file",
}

_SHOW_MAX = 12          # display cap; never printed, so it cannot be flagged


def _when(v) -> str:
    return str(v or "")[:16].replace("T", " ")


def _titlecase(v) -> str:
    return str(v or "").replace("_", " ").title()



def _day_name(iso: str | None) -> str:
    """A date a person would say out loud: "28 September"."""
    if not iso:
        return "now"
    try:
        d = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)[:10]
    return f"{d.day} {d.strftime('%B')}"


def _ros_summary(d: dict) -> str:
    """The shop list - safety, blocked, at-risk, waiters."""
    ros = d.get("ros") or []
    filt = str(d.get("filter") or "").lower()
    title = _FILTER_TITLES.get(filt, f"match {filt}")
    if not ros:
        return f"No repair orders {title} at the moment."

    count, shown = d.get("count"), d.get("shown")
    head = f"**{count} repair orders {title}.**"
    if isinstance(count, int) and isinstance(shown, int) and shown < count:
        head += f" Showing {shown}, most urgent first."
    else:
        head += " Most urgent first."
    L = [head]

    for r in ros[:_SHOW_MAX]:
        line = f"\n**{r.get('ro_number')}**"
        if r.get("vehicle"):
            line += f" - {r['vehicle']}"
        if r.get("registration"):
            line += f", {r['registration']}"
        L.append(line)

        status = f"- Status: {_titlecase(r.get('state'))}"
        risk = _RISK_WORDS.get(r.get("promise_risk"))
        if risk:
            status += f", {risk}"
        if r.get("promised_time"):
            status += f" (promised {_when(r['promised_time'])})"
        L.append(status)

        for s in (r.get("safety_detail") or []):
            L.append(f"- **Safety finding:** {s}")
        if r.get("concern"):
            L.append(f"- Customer reported: {r['concern']}")
        if r.get("blocked") and r.get("blocked_on"):
            L.append(f"- Waiting on: {r['blocked_on']}")
        pend = [p for p in (r.get("pending") or []) if p]
        if pend:
            L.append(f"- Still to do: {'; '.join(pend[:4])}")
        if r.get("wait_type") == "WAITER":
            L.append("- Customer is waiting on site")
    if len(ros) > _SHOW_MAX:
        L.append("\nThe remainder are listed on the Shop Floor tab.")
    return "\n".join(L)


def _ro_state_summary(d: dict) -> str:
    """One repair order, in full."""
    if not d.get("found"):
        return str(d.get("error") or "That repair order is not on file.")
    L = []
    head = f"**{d.get('ro_number')}** - {d.get('vehicle')}"
    if d.get("registration"):
        head += f", {d['registration']}"
    if d.get("odometer_miles"):
        head += f" - {d['odometer_miles']} miles"
    L.append(head)

    status = f"Status: **{_titlecase(d.get('state'))}**"
    risk = _RISK_WORDS.get(d.get("promise_risk"))
    if risk:
        status += f" - {risk}"
    if d.get("promised_time"):
        status += f" (promised {_when(d['promised_time'])})"
    L.append(status)
    if d.get("concern"):
        L.append(f"Customer reported: {d['concern']}")
    if d.get("wait_type") == "WAITER":
        L.append("The customer is waiting on site.")

    sf = d.get("safety_flags") or []
    if sf:
        L.append("\n**Safety - do not release**")
        for f in sf:
            L.append(f"- {f.get('detail')}")
    if d.get("blocked") and d.get("blocked_on"):
        L.append(f"\n**Blocked** - waiting on {d['blocked_on']}")

    comp = d.get("completed") or []
    if comp:
        h = "\n**Work completed**"
        hb, fr = d.get("hours_booked"), d.get("flat_rate_total")
        if hb and fr:
            h += f" - {hb} hours booked against {fr} allowed"
        L.append(h)
        for c in comp:
            who = f" ({c['by']})" if c.get("by") else ""
            L.append(f"- {c.get('description') or c.get('op_code')}"
                     f" - {c.get('actual_hrs')} hours{who}")
    for key, label in (("pending", "Still to do"),
                       ("recommended", "Recommended - needs customer authorisation")):
        items = d.get(key) or []
        if items:
            L.append(f"\n**{label}**")
            for o in items:
                L.append(f"- {o.get('description') or o.get('op_code')}")

    parts = d.get("parts") or {}
    if parts:
        L.append("\n**Parts**")
        # snapshot.parts is {part_no: {"availability": ...}}. Slicing a dict
        # raises, and _summarise swallows it - which silently disabled this
        # whole renderer until it was caught.
        pairs = (list(parts.items()) if isinstance(parts, dict)
                 else [(p, None) for p in parts])
        for name, info in pairs[:8]:
            avail = (info or {}).get("availability") if isinstance(info, dict) else None
            L.append(f"- {name}" + (f" - {_titlecase(avail)}" if avail else ""))
    if d.get("dtc_codes"):
        L.append("\n**Fault codes recorded:** " + ", ".join(str(c) for c in d["dtc_codes"]))
    conf = d.get("conflicts") or []
    if conf:
        L.append("\n**Contradictions found in the updates**")
        for c in conf:
            L.append(f"- {_titlecase(c.get('kind'))}: {c.get('detail')}")
    return "\n".join(L)


def _handover_summary(d: dict) -> str:
    """The prioritised shift handover."""
    t = d.get("totals") or {}
    L = [f"**Shift handover - {_titlecase(d.get('shift'))}**",
         f"\n{t.get('open')} open repair orders: **{t.get('safety')} with safety "
         f"findings**, {t.get('at_risk')} at risk of missing their promise, "
         f"{t.get('blocked')} blocked, {t.get('pending_ops')} operations still to do."]
    for bucket, items in (d.get("groups") or {}).items():
        items = items or []
        if not items:
            continue
        L.append(f"\n**{_titlecase(bucket)}**")
        for r in items[:_SHOW_MAX]:
            line = f"\n- **{r.get('ro_number')}**"
            if r.get("vehicle"):
                line += f" - {r['vehicle']}"
            risk = _RISK_WORDS.get(r.get("promise_risk"))
            if risk:
                line += f", {risk}"
            L.append(line)
            for s in (r.get("safety") or []):
                L.append(f"  - **Safety finding:** {s}")
            if r.get("concern"):
                L.append(f"  - Customer reported: {r['concern']}")
            if r.get("blocked_on"):
                L.append(f"  - Waiting on: {r['blocked_on']}")
            pend = [p for p in (r.get("pending") or []) if p]
            if pend:
                L.append(f"  - Still to do: {'; '.join(pend[:3])}")
            if r.get("next_action"):
                L.append(f"  - **Next action:** {r['next_action']}")
        if len(items) > _SHOW_MAX:
            L.append("\n  The remainder are on the Shift Handover tab.")
    return "\n".join(L)


def _anomaly_summary(d: dict) -> str:
    """Cross-RO patterns. Every figure is read from the payload, never derived."""
    L = [f"Patterns across the last {d.get('window_days')} days."]
    if d.get("shared_part_holds"):
        L.append("\n**One part blocking several jobs** - order once, clear several")
        for x in d["shared_part_holds"]:
            L.append(f"- `{x.get('part_no')}` is holding **{x.get('ro_count')}** repair "
                     f"orders: {', '.join(x.get('ros') or [])}")
    if d.get("authorisation_delays"):
        L.append("\n**Waiting on customer authorisation**")
        for x in d["authorisation_delays"]:
            tail = " - customer waiting on site" if x.get("wait_type") == "WAITER" else ""
            L.append(f"- {x.get('ro_number')} {x.get('vehicle')} - "
                     f"**{x.get('waiting_hours')}h** without a decision{tail}")
    if d.get("stalled_ros"):
        L.append("\n**Stalled - nothing logged for over a day**")
        for x in d["stalled_ros"]:
            L.append(f"- {x.get('ro_number')} {x.get('vehicle')} - idle "
                     f"**{x.get('idle_hours')}h** in {_titlecase(x.get('state'))}, "
                     f"last touched by {x.get('last_actor')}")
    if d.get("comebacks"):
        L.append("\n**Comebacks and rework**")
        for x in d["comebacks"]:
            det = x.get("detail")
            det = "; ".join(det) if isinstance(det, list) else (det or "")
            L.append(f"- {x.get('ro_number')} {x.get('vehicle')} - "
                     f"**{x.get('count')}** recorded" + (f": {det}" if det else ""))
    if d.get("repeat_visits"):
        L.append("\n**Same vehicle back again**")
        for x in d["repeat_visits"]:
            L.append(f"- VIN `{x.get('vin')}` - **{x.get('visits')}** visits: "
                     f"{', '.join(x.get('ros') or [])}")
    if len(L) == 1:
        L.append("\nNothing unusual in this window.")
    return "\n".join(L)


def _diff_summary(d: dict) -> str:
    """What changed on one repair order since a cutoff."""
    if not d.get("found"):
        return str(d.get("error") or "That repair order is not on file.")
    L = [f"**{d.get('ro_number')}** - {d.get('vehicle')} - changes in the last "
         f"{d.get('window_hours')} hours"]
    if d.get("state_changed") and d.get("state_before"):
        L.append(f"- Moved from {_titlecase(d.get('state_before'))} to "
                 f"**{_titlecase(d.get('state_now'))}**")
    elif d.get("state_now"):
        L.append(f"- Still in **{_titlecase(d.get('state_now'))}** - no state change")
    for x in d.get("newly_completed") or []:
        L.append(f"- Completed: {x.get('description') or x.get('op_code')}")
    for x in d.get("newly_raised") or []:
        status = f" ({_titlecase(x.get('status'))})" if x.get("status") else ""
        L.append(f"- Raised: {x.get('description') or x.get('op_code')}{status}")
    for s in d.get("new_safety") or []:
        L.append(f"- **New safety finding:** {s}")
    if d.get("technician_changed"):
        L.append(f"- Handed from {d.get('from_actor')} to **{d.get('to_actor')}**")
    risk = _RISK_WORDS.get(d.get("promise_risk"))
    if risk:
        L.append(f"- Promise status: {risk}")
    if len(L) == 1:
        L.append("- Nothing changed in this window.")
    return "\n".join(L)


_SHIFT_WORDS = {"MORNING": "morning shift", "AFTERNOON": "afternoon shift"}


def _plural(n, one: str, many: str) -> str:
    """Print the payload's own figure, choosing the word to go with it.

    Branching on a value is not deriving one - the digit still comes straight
    from the payload, so the grounding rail has nothing to catch. "1 updates"
    is the kind of detail that makes an answer look machine-written.
    """
    return f"**{n} {one if n == 1 else many}**"


def _vehicles_summary(d: dict, when: str) -> str:
    """Which vehicles came through, and what was done to each.

    Reads `by_ro`, which the query grouped over every person in the window -
    grouping here would quietly lose the work of anyone past the display cap.
    Safety-critical jobs sort first, because that is what a manager scanning this
    list is looking for.
    """
    with_ops = d.get("ros_with_ops")
    L = [f"**{d.get('ros_worked')} vehicles were worked on {when}** - "
         f"{_plural(d.get('ops_completed'), 'operation', 'operations')} completed "
         f"across {_plural(d.get('hours_booked'), 'hour', 'hours')}"
         + (f", on {with_ops} of them." if with_ops is not None else ".")]
    if d.get("brief"):
        # "How many" is a question about a number. Thirteen vehicle cards
        # underneath one is not an answer, it is the payload.
        safety = sum(1 for r in (d.get("by_ro") or []) if r.get("safety"))
        if safety:
            L.append(f"- Safety-critical work on **{safety}** of them.")
        return "\n".join(L)
    if with_ops and d.get("ros_shown") != with_ops:
        L.append(f"Showing **{d.get('ros_shown')}** of those {with_ops}, "
                 f"safety-critical first.")

    for r in d.get("by_ro") or []:
        head = f"\n**{r.get('ro_number')}**"
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
    L.append("\nEvery vehicle with an operation booked in that window, taken "
             "from the shift recorded against each job.")
    return "\n".join(L)


def _shift_summary(d: dict) -> str:
    """Who worked on a day or shift, and what they did.

    Exact by construction: the shift came from a column, and every figure below
    is copied from the payload rather than derived here.
    """
    sh = str(d.get("shift") or "ALL")
    # Lead with "today"/"yesterday" and a written date. A bare ISO date read
    # against the reader's own calendar makes a correct answer look stale,
    # which is exactly what happened with ASOIA_NOW pinned a day back.
    parts = [d.get("day_label")]
    if not (d.get("window_days") or 1) > 1:
        parts.append(d.get("date_long"))
    day = ", ".join(str(x) for x in parts if x) or str(d.get("date"))
    when = day if sh not in _SHIFT_WORDS else f"the {_SHIFT_WORDS[sh]} of {day}"
    if not d.get("found"):
        if d.get("error"):
            return str(d["error"])
        return (f"**Nothing is recorded for {when}.** No technician posted an "
                f"update and no operation was booked in that window.\n\n"
                f"That is what the log contains - it is not evidence that the "
                f"workshop was closed, only that no work was logged against it.")

    if d.get("view") == "vehicles":
        return _vehicles_summary(d, when)

    n = d.get("people_count")
    L = [f"**{n} {'person' if n == 1 else 'people'} worked {when}.**"]

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
        head = f"\n**{p.get('name')}** ({p.get('staff_id')})"
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
        L.append("\n**Shorthand used in those notes**")
        for k, v in sorted(jargon.items()):
            L.append(f"- **{k}** - {v}")
    L.append("\nThis is everyone with work logged in that window, taken from the "
             "shift recorded on each update - not from a text search.")
    return "\n".join(L)



def _intake_summary(d: dict) -> str:
    """How much work came in. Count first - the question is a number."""
    if not d.get("found"):
        return None
    n, days = d.get("count"), d.get("window_days")
    when = _day_name(d.get("until"))
    if not n:
        return f"**No vehicles came into the shop in the {days} days to {when}.**"
    L = [f"**{n} vehicles came into the shop in the {days} days to {when}** "
         f"- {d.get('per_day_average')} a day."]
    open_n, done = d.get("still_open"), d.get("invoiced")
    bits = []
    if d.get("blocked"):
        bits.append(f"{d['blocked']} waiting on parts")
    if d.get("open_safety"):
        bits.append(f"{d['open_safety']} with an open safety finding")
    tail = f", of which {' and '.join(bits)}" if bits else ""
    L.append(f"- Still open: **{open_n}**{tail}")
    L.append(f"- Completed and invoiced: {done}")
    if d.get("waiters"):
        L.append(f"- Customer waiting on site: {d['waiters']}")
    b = d.get("busiest_day")
    if b:
        L.append(f"- Busiest day: {_day_name(b['date'])}, {b['count']} arrivals")
    cats = d.get("by_category") or []
    if cats:
        top = ", ".join(f"{c['category']} {c['count']}" for c in cats[:3])
        L.append(f"- Most common work: {top}")
    return "\n".join(L)


_RENDERERS = {
    "get_technician_activity": lambda res: _tech_summary(res) if res.get("found") else None,
    "list_ros":                _ros_summary,
    "get_ro_state":            _ro_state_summary,
    "generate_handover":       _handover_summary,
    "detect_anomalies":        _anomaly_summary,
    "diff_ro":                 _diff_summary,
    "get_shift_activity":      _shift_summary,
    "get_intake":              _intake_summary,
}


# Tools with no renderer BY DESIGN. Summarising what technicians wrote in prose
# is genuine language work - the one job the model does better than a renderer
# could. Reaching the model through these is the intended path, so it must not
# raise a warning: an alarm that fires on correct behaviour is an alarm nobody
# reads on the day it means something.
_NARRATED = {"search_updates"}


def _summarise(results: list[dict], notes: list | None = None) -> str | None:
    """Compose the answer in Python when every tool in the plan has a renderer.

    If any tool does not, return None so the LLM narrates the whole payload
    rather than the answer silently losing part of it.

    Every UNINTENDED reason for falling back is recorded in `notes` and warned on
    stderr. A silent fallback once hid a renderer crash for an entire release; it
    should never be possible to degrade to narration without a trace. The tools
    in `_NARRATED` are the exception, and only because they were never meant to
    have a renderer.
    """
    def note(msg: str):
        if notes is not None:
            notes.append(msg)
        print(f"[compose] falling back to the model: {msg}", file=_sys.stderr)

    blocks = []
    for r in results:
        tool = r.get("tool")
        fn = _RENDERERS.get(tool)
        if fn is None:
            if tool not in _NARRATED:
                note(f"no renderer for {tool}")
            return None
        res = r.get("result")
        if not isinstance(res, dict):
            note(f"{tool} returned {type(res).__name__}, expected dict")
            return None
        # call() turns an exception inside a tool into {"error": ...}. Without
        # this the renderer composes over the wreckage and the answer looks fine.
        if res.get("error") and res.get("found") is not False:
            note(f"{tool} failed: {str(res['error'])[:120]}")
            return None
        try:
            out = fn(res)
        except Exception as ex:
            note(f"renderer for {tool} raised {type(ex).__name__}: {ex}")
            return None
        if not out:
            note(f"renderer for {tool} produced nothing")
            return None
        blocks.append(out)
    if not blocks:
        note("no tool results to compose from")
        return None
    return "\n\n".join(blocks)


def ask(question: str, chat_fn=None, use_llm_router: bool = True) -> Answer:
    """Answer a question, and record how it went. See app/obs/metrics.py."""
    import time as _t
    from app.obs import metrics as _M
    _start = _t.perf_counter()
    ans = _ask_inner(question, chat_fn, use_llm_router)
    _elapsed = _t.perf_counter() - _start
    _M.record_answer(ans, _elapsed)
    # Provenance for app/review: what was asked, what it cited, whether
    # grounding passed. Best effort by construction - an audit trail that
    # can break answering is worse than no audit trail. ASOIA_LOG_ANSWERS=0
    # turns it off.
    try:
        from app.review.store import log_answer as _log
        _log(ans, _elapsed)
    except Exception:
        pass
    return ans


def _ask_inner(question: str, chat_fn=None, use_llm_router: bool = True) -> Answer:
    if chat_fn is None:
        from app.nim.client import chat as chat_fn
    ans = Answer(question=question)

    # Routing, and the decision not to pay for the LLM router - see plan_for.
    plan, ans.route = plan_for(question, chat_fn, use_llm_router)
    ans.tool_calls = plan

    for step in plan:
        ans.results.append({"tool": step["name"], "args": step.get("args", {}),
                            "result": call(step["name"], **step.get("args", {}))})
    ans.citations = _collect_citations(ans.results)

    notes: list[str] = []
    # A stale vector index is the only fault that yields a confident, well-formed,
    # fully "grounded" answer citing records that are not there - check_grounding
    # checks figures against tool results, never that a cited id resolves. The
    # tool detects it; this is where it becomes visible to whoever is reading.
    for _r in ans.results:
        _res = _r.get("result")
        _stale = _res.get("stale_index") if isinstance(_res, dict) else None
        if _stale:
            notes.append(_stale.get("note")
                         or "the vector index does not match the database")
    summary = (_summarise(ans.results, notes)
               if os.environ.get("ASOIA_DETERMINISTIC", "1") == "1" else None)
    ans.compose_notes = notes
    if summary:
        # Composed from the record - no narration call, nothing to hallucinate.
        # Grounding still runs: a renderer bug must not get a free pass either.
        ans.composed = "python"
        ans.text = summary
        ans.warnings = check_grounding(ans.text, ans.results)
        ans.grounded = not ans.warnings
        return ans
    ans.composed = "llm"

    payload = _render(ans.results)
    if len(payload) > 22000:
        payload = payload[:22000] + "\n...[truncated]"
    msgs = [{"role": "system", "content": _narration_system(ans.results)},
            {"role": "user",
             "content": f"Question: {question}\n\nRECORDS:\n{payload}"}]
    # Ask for the finish reason when the chat function can report one. The
    # verification harness passes a spy with its own signature, so this is
    # checked rather than assumed.
    meta: dict = {}
    try:
        import inspect as _inspect
        wants_meta = "meta" in _inspect.signature(chat_fn).parameters
    except (TypeError, ValueError):
        wants_meta = False
    if wants_meta:
        ans.text = chat_fn(msgs, temperature=0.0, max_tokens=400, meta=meta)
    else:
        ans.text = chat_fn(msgs, temperature=0.0, max_tokens=400)
    if meta.get("finish_reason") == "length":
        ans.compose_notes = list(ans.compose_notes) + [
            "the model ran out of room at 400 tokens - the answer is cut short"]
    if os.environ.get("ASOIA_FIGURES", "1") == "1":
        fig = _figures(ans.results)
        if fig:
            ans.text = (ans.text.rstrip() +
                        "\n\n**Figures** (computed from the record, not generated):\n" +
                        fig)
    ans.warnings = check_grounding(ans.text, ans.results)
    if os.environ.get("ASOIA_NEGATION_RAIL", "1") == "1":
        ans.warnings += check_negations(ans.text)
    ans.grounded = not ans.warnings
    return ans
