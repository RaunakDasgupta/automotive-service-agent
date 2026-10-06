#!/usr/bin/env python3
"""pass 55 - three more NeMo Evaluator benchmarks, and the bug they found.

    .venv/bin/python patches/quality_pass55.py            apply
    .venv/bin/python patches/quality_pass55.py --check    verify, change nothing

The project's testing framework is NVIDIA NeMo Evaluator (0.2.8), used as BYOB
benchmarks in evals/asoia_byob.py and driven by scripts/eval_standard.py, which
keeps every run in run/evals/history.jsonl so a release can be compared with the
last one. It had four benchmarks: routing, grounding, traceability, refusal.

All four could be satisfied by an answer that was wrong.

  - routing asked whether the right tool was IN the plan. It could not see a
    right tool called with wrong arguments, and could not see a second tool that
    should never have run. Both shipped, in pass 53.
  - grounding asked whether every figure appears in the payload. An answer that
    quotes the payload perfectly while answering a different question passes.
  - nothing compared a stated number against a number computed independently.
  - nothing asked whether the text was an answer at all.

THREE NEW BENCHMARKS

asoia_tool_calls   plan_exact, spurious_tools, arg_agreement, arg_rules_checked

    The whole call: the right tools, no others, with the arguments the question
    asked for. The expectations are derived from the QUESTION rather than from a
    gold table - "this week" means days=7, "yesterday" means day_offset=-1,
    "morning" means shift=MORNING, a vehicle noun means view=vehicles - because
    a table of expected arguments is one more thing to keep in step with the
    router, and the words in the question are the ground truth about what was
    asked.

asoia_accuracy     answer_accuracy, headline_correct, accuracy_scored

    Does the answer state the right number, and state it first? `truth` comes
    from scripts/make_eval_dataset.py, computed with direct SQL that never
    touches app.agent.tools - a number checked against the thing that produced
    it is not a check. It covers 10 of 37 questions: the ones whose truth is a
    straightforward query. A count of blocked repair orders needs the event log
    folded, and a second fold written in the scorer would be the same code
    twice rather than independent evidence. accuracy_scored reports that
    coverage, because a measure that silently skips rows reads as a pass.

asoia_relevance    relevance, answers_the_form, entity_coverage, free_of_meta

    An answer can be perfectly grounded and not be an answer. Three
    coefficients, each a failure this project has shipped: a "how many" question
    whose first line carries no number; an answer that never mentions what the
    question named; and prose about the machinery - "the search returned four
    updates", "as per the guidelines", an apology.

WHAT THEY FOUND, IMMEDIATELY

    "Hand over to the morning shift."  ->  **Shift handover - Afternoon**

Every handover was the afternoon one. The keyword route built the call with no
arguments at all, so the tool used its own default, and "Give me the afternoon
handover" had been passing by coincidence. Routing scored it correct for as
long as it has existed: the right tool ran.

The fix is three lines in plan_keyword, and handover.shift is now one of the
arguments asoia_tool_calls checks.

AND ONE THING THE SCORER HAD WRONG

entity_coverage first read 82.4%, and six of the seven misses were correct
answers being marked down for being more precise than the question: "this week"
answered by "the 7 days to 28 September". The entity is the window, not the
word, so each one now carries the forms that satisfy it. The seventh miss was
the handover.

Also fixed: pass 54 made evaluate.py's expected tool a TUPLE, which the dataset
builder wrote into expected_tool, which asoia_routing tests with `target in
tools` - so the benchmark had been scoring every row against a list. It scored
1.0 throughout because the cross-check compared it with a measure that had the
same blind spot. The cross-check now runs against plan_exact.

    routing_accuracy  100%      plan_exact        100%
    figures_supported 100%      spurious_tools    0
    traceability      100%      arg_agreement     100%
    refused           100%      answer_accuracy   100%  (10 of 37 scored)
                                relevance         100%  (was 94.1%)
"""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = "--check" in sys.argv

EDITS = [
    ('app/agent/agent.py', [
        ('    for pat, tool, args in KEYWORDS:\n        if re.search(pat, q, re.I):\n            a = dict(args)\n            if tool == "get_technician_activity":\n                m = ID_RE.search(question)\n                if not m:',
         '    for pat, tool, args in KEYWORDS:\n        if re.search(pat, q, re.I):\n            a = dict(args)\n            if tool == "generate_handover":\n                # "Hand over to the morning shift" was answered with the\n                # afternoon handover, every time, because this call was built\n                # with no arguments at all and the tool\'s own default is\n                # AFTERNOON. Routing scored it correct: the right tool ran.\n                sh = _timeframe(question) or {}\n                if sh.get("shift"):\n                    a["shift"] = sh["shift"]\n            if tool == "get_technician_activity":\n                m = ID_RE.search(question)\n                if not m:'),
    ]),
    ('evals/asoia_byob.py', [
        ('    safety decision from prose - which would be a worse test than the rail.\n    """\n    return {"refused_before_tools": 1.0 if inp.metadata.get("refused") else 0.0}',
         '    safety decision from prose - which would be a worse test than the rail.\n    """\n    return {"refused_before_tools": 1.0 if inp.metadata.get("refused") else 0.0}\n\n\n# ===========================================================================\n# Tool calling, scored at the ARGUMENT level\n# ===========================================================================\n# Routing above asks whether the right tool ran. It cannot see a right tool\n# called with wrong arguments, and it cannot see a second tool that should not\n# have run at all. Both happened in pass 53: "how many cars were worked on\n# yesterday" reached get_intake with days=7, and "how many cars are blocked"\n# ran list_ros AND get_intake. Routing scored 30/30 through both.\n#\n# The expectations here are derived from the QUESTION, not from a gold table.\n# A table of expected arguments is another thing to keep in step with the\n# router, and the two would drift; the words in the question are the ground\n# truth about what was asked.\n_DAY = [\n    (re.compile(r"\\byesterday\\b|\\bovernight\\b|\\blast night\\b", re.I), -1),\n    (re.compile(r"\\bday before yesterday\\b|\\btwo days ago\\b", re.I), -2),\n    (re.compile(r"\\btoday\\b|\\bthis morning\\b|\\bthis afternoon\\b|\\btonight\\b", re.I), 0),\n]\n_SHIFT = [\n    (re.compile(r"\\bafternoon\\b|\\bevening\\b|\\bovernight\\b|\\blast night\\b", re.I), "AFTERNOON"),\n    (re.compile(r"\\bmorning\\b", re.I), "MORNING"),\n]\n_WINDOW = [\n    (re.compile(r"\\blast (\\d+) weeks?\\b|\\bpast (\\d+) weeks?\\b", re.I), None),\n    (re.compile(r"\\blast (\\d+) days?\\b|\\bpast (\\d+) days?\\b", re.I), None),\n    (re.compile(r"\\bthis month\\b|\\blast month\\b|\\bmonthly\\b", re.I), 30),\n    (re.compile(r"\\bthis week\\b|\\blast week\\b|\\bpast week\\b|\\bweekly\\b|\\bseven days\\b", re.I), 7),\n    (re.compile(r"\\btoday\\b|\\bthis morning\\b|\\bthis afternoon\\b", re.I), 1),\n]\n_VEHICLE_WORD = re.compile(r"\\bcars?\\b|\\bvehicles?\\b|\\bmotors?\\b|\\bjobs?\\b"\n                           r"|\\brepair orders?\\b|\\bros?\\b", re.I)\n_PEOPLE_WORD = re.compile(r"\\bwho\\b|\\btechnicians?\\b|\\bstaff\\b|\\bteam\\b|\\bpeople\\b", re.I)\n_FILTER = [\n    (re.compile(r"\\bsafety|unsafe|dangerous|released?\\b", re.I), "safety"),\n    (re.compile(r"\\bblocked|parts hold|waiting (on|for) parts|held up\\b", re.I), "blocked"),\n    (re.compile(r"\\bat.risk|late|overdue|breach|promis|miss\\w*\\b", re.I), "at_risk"),\n    (re.compile(r"\\bwaiter|customers? waiting|waiting on site\\b", re.I), "waiter"),\n]\n\n\ndef _window_of(q: str):\n    for rx, fixed in _WINDOW:\n        m = rx.search(q)\n        if not m:\n            continue\n        if fixed is not None:\n            return fixed\n        n = next((g for g in m.groups() if g), None)\n        if n is None:\n            return None\n        return int(n) * (7 if "week" in m.group(0).lower() else 1)\n    return None\n\n\ndef _arg_rules(question: str, call: dict):\n    """Every expectation the QUESTION creates for this call: (name, ok)."""\n    q, name, args = question, call.get("name"), call.get("args") or {}\n    out = []\n    if name == "get_intake":\n        want = _window_of(q)\n        out.append(("intake.days", args.get("days") == (want or 7)))\n    if name == "get_shift_activity":\n        day = next((v for rx, v in _DAY if rx.search(q)), 0)\n        out.append(("activity.day_offset", int(args.get("day_offset", 0)) == day))\n        sh = next((v for rx, v in _SHIFT if rx.search(q)), None)\n        if sh:\n            out.append(("activity.shift", str(args.get("shift", "")).upper() == sh))\n        if _VEHICLE_WORD.search(q) and not _PEOPLE_WORD.search(q):\n            out.append(("activity.view", args.get("view") == "vehicles"))\n        elif _PEOPLE_WORD.search(q):\n            out.append(("activity.view", args.get("view") == "people"))\n        win = _window_of(q)\n        if win and win > 1:\n            out.append(("activity.days", int(args.get("days", 1)) == win))\n    if name == "generate_handover":\n        sh = next((v for rx, v in _SHIFT if rx.search(q)), None)\n        if sh:\n            out.append(("handover.shift", str(args.get("shift", "")).upper() == sh))\n    if name == "list_ros":\n        want = next((v for rx, v in _FILTER if rx.search(q)), None)\n        if want:\n            out.append(("list_ros.filter", args.get("filter") == want))\n    return out\n\n\n@benchmark(\n    name="asoia_tool_calls",\n    dataset="data/answers.jsonl",\n    prompt="{question}",\n    target_field="expected_plan",\n    response_field="response",\n)\ndef tool_calls(inp: ScorerInput) -> dict:\n    """The whole call: the right tools, no others, with arguments the question asked for."""\n    want = inp.target if isinstance(inp.target, list) else [inp.target]\n    plan = list(inp.metadata.get("plan") or [])\n    got = [c.get("name") for c in plan]\n    checks = [ok for c in plan for _, ok in _arg_rules(inp.metadata.get("question", ""), c)]\n    spurious = [n for n in got if n not in want]\n    return {\n        "plan_exact": 1.0 if got == list(want) else 0.0,\n        "spurious_tools": float(len(spurious)),\n        "arg_agreement": (sum(1.0 for c in checks if c) / len(checks)) if checks else 1.0,\n        "arg_rules_checked": float(len(checks)),\n    }\n\n\n# ===========================================================================\n# Accuracy against a number this scorer did not produce\n# ===========================================================================\n@benchmark(\n    name="asoia_accuracy",\n    dataset="data/answers.jsonl",\n    prompt="{question}",\n    target_field="truth",\n    response_field="response",\n)\ndef accuracy(inp: ScorerInput) -> dict:\n    """Does the answer state the number, and state it FIRST?\n\n    `truth` is computed in make_eval_dataset.py by direct SQL that never touches\n    the agent\'s tools, so this is the one measure here that could catch a tool\n    which is wrong in the same way its renderer is. Rows with no truth - the\n    ones whose answer needs the event log folded - are scored 1.0 and counted\n    separately, because a measure that silently skips rows reads as a pass.\n    """\n    truth = inp.target\n    if truth is None or truth == "":\n        return {"answer_accuracy": 1.0, "accuracy_scored": 0.0,\n                "headline_correct": 1.0}\n    want = str(int(truth)) if str(truth).isdigit() or isinstance(truth, int) else str(truth)\n    text = inp.response or ""\n    first = next((ln for ln in text.splitlines() if ln.strip()), "")\n    present = want in NUM_RE.findall(text)\n    return {\n        "answer_accuracy": 1.0 if present else 0.0,\n        "accuracy_scored": 1.0,\n        # The pass-53 failure stated a real number from the wrong question. A\n        # headline that leads with a figure that is not the answer is worse\n        # than one that omits it.\n        "headline_correct": 1.0 if want in NUM_RE.findall(first) else 0.0,\n    }\n\n\n# ===========================================================================\n# Relevance: is this an answer to THIS question\n# ===========================================================================\n_META = re.compile(\n    r"\\bthe search returned\\b|\\bas per the guidelines?\\b|\\bthe passages?\\b"\n    r"|\\bthe updates (provided|mention|also)\\b|\\bthe notes (provided|mention)\\b"\n    r"|\\bI\'?m sorry\\b|\\bI cannot\\b|\\bI am unable\\b|\\bas an AI\\b"\n    r"|\\brepeat_call\\b|\\bper your instruction", re.I)\n_RO = re.compile(r"\\bRO-\\d{2}-\\d{4,5}\\b", re.I)\n_STAFF = re.compile(r"\\b(EMP|ADV|FOR|PRT|MGR)\\d{3}\\b", re.I)\n_COUNT_Q = re.compile(r"\\bhow many\\b|\\bhow much\\b|\\bhow busy\\b", re.I)\n_OPEN_Q = re.compile(r"^\\s*(which|what|who|where|when)\\b", re.I)\n\n\n# "This week" is answered by "the 7 days to 28 September". The entity is the\n# window, not the word, so each one carries the forms that satisfy it - without\n# this the scorer marked six correct answers down for being more precise than\n# the question.\n_ENTITY_FORMS = {\n    "week": ("week", "7 days", "seven days"),\n    "month": ("month", "30 days", "thirty days"),\n    "morning": ("morning",),\n    "afternoon": ("afternoon", "evening"),\n    "yesterday": ("yesterday",),\n    "safety": ("safety", "unsafe"),\n    "part": ("part", "blocked"),\n    "promis": ("promis", "late", "overdue"),\n    "waiting": ("waiting", "waiter"),\n}\n\n\ndef _covers(entity: str, text_up: str, text_low: str) -> bool:\n    forms = _ENTITY_FORMS.get(entity)\n    if forms:\n        return any(f in text_low for f in forms)\n    return entity.upper() in text_up\n\n\ndef _question_entities(q: str):\n    """What the question is about, in terms an answer can be checked against."""\n    ents = set(m.group(0).upper() for m in _RO.finditer(q))\n    ents |= set(m.group(0).upper() for m in _STAFF.finditer(q))\n    for rx, word in ((re.compile(r"\\bsafety|unsafe|dangerous\\b", re.I), "safety"),\n                     (re.compile(r"\\bblocked|parts\\b", re.I), "part"),\n                     (re.compile(r"\\bpromis|late|overdue\\b", re.I), "promis"),\n                     (re.compile(r"\\bwaiting|waiter\\b", re.I), "waiting"),\n                     (re.compile(r"\\bmorning\\b", re.I), "morning"),\n                     (re.compile(r"\\bafternoon\\b", re.I), "afternoon"),\n                     (re.compile(r"\\byesterday\\b", re.I), "yesterday"),\n                     (re.compile(r"\\bweek\\b", re.I), "week"),\n                     (re.compile(r"\\bmonth\\b", re.I), "month")):\n        if rx.search(q):\n            ents.add(word)\n    return ents\n\n\n@benchmark(\n    name="asoia_relevance",\n    dataset="data/answers.jsonl",\n    prompt="{question}",\n    target_field="question",\n    response_field="response",\n)\ndef relevance(inp: ScorerInput) -> dict:\n    """An answer can be perfectly grounded and still not be an answer.\n\n    Three things, each a coefficient in [0, 1] and each a failure this project\n    has actually shipped:\n\n      answers_the_form  a "how many" question whose first line carries no number\n                        was the pass-53 regression; a "which" question with no\n                        entity named is the search answer that listed three cars.\n      entity_coverage   the share of what the question named that the answer\n                        mentions. An answer about the wrong repair order scores\n                        zero here while grounding scores one.\n      free_of_meta      no "the search returned", no "as per the guidelines",\n                        no apology. Prose about the machinery is not an answer,\n                        and every one of these phrases was in a shipped reply.\n\n    `relevance` is their mean, reported alongside the three so a middling score\n    can be read rather than guessed at.\n    """\n    q = inp.target if isinstance(inp.target, str) else str(inp.target)\n    text = (inp.response or "").strip()\n    first = next((ln for ln in text.splitlines() if ln.strip()), "")\n\n    if not text:\n        form = 0.0\n    elif _COUNT_Q.search(q):\n        form = 1.0 if NUM_RE.findall(first) else 0.0\n    elif _OPEN_Q.search(q):\n        named = bool(_RO.search(text) or _STAFF.search(text)\n                     or NUM_RE.findall(first))\n        none_said = re.search(r"\\bno\\b|\\bnone\\b|\\bnothing\\b", first, re.I)\n        form = 1.0 if (named or none_said) else 0.0\n    else:\n        form = 1.0 if text else 0.0\n\n    ents = _question_entities(q)\n    up, low = text.upper(), text.lower()\n    hit = sum(1 for e in ents if _covers(e, up, low))\n    coverage = (hit / len(ents)) if ents else 1.0\n    meta = 0.0 if _META.search(text) else 1.0\n    return {"relevance": round((form + coverage + meta) / 3, 4),\n            "answers_the_form": form,\n            "entity_coverage": round(coverage, 4),\n            "free_of_meta": meta}'),
    ]),
    ('scripts/make_eval_dataset.py', [
        ('OUT = pathlib.Path("evals/data")\n\n\ndef main() -> int:\n    import evaluate as EV                      # the labelled sets, one source\n    from app.agent.agent import ask',
         'OUT = pathlib.Path("evals/data")\n\n\n\n# --- independent ground truth ----------------------------------------------\n# Computed with direct SQL that does not touch app.agent.tools. A benchmark\n# scored against the thing it is testing is not a benchmark, so the number an\n# answer is checked against has to come from somewhere else.\n#\n# Only the questions whose truth is a straightforward query are here. A count of\n# blocked or unsafe repair orders is derived by folding the event log, and a\n# second fold written here would be the same code twice rather than independent\n# evidence - which is the mistake the rail harness made in section 13. Those\n# questions carry no truth and are not scored for accuracy, and saying which\n# ones are unscored is part of the measure.\ndef _truths(now):\n    import sqlite3, os\n    from datetime import timedelta\n    db = os.environ.get("ASOIA_DB", "data/generated/service.sqlite")\n    con = sqlite3.connect(db)\n\n    def one(sql, *args):\n        return con.execute(sql, args).fetchone()[0]\n\n    def arrived(days):\n        since = (now - timedelta(days=days)).isoformat()\n        return one("SELECT count(*) FROM ros WHERE checked_in_at >= ? "\n                   "AND checked_in_at <= ?", since, now.isoformat())\n\n    def touched(day_offset, days=1):\n        last = (now + timedelta(days=day_offset)).date().isoformat()\n        first = (now + timedelta(days=day_offset - days + 1)).date().isoformat()\n        return one(\n            "SELECT count(*) FROM (SELECT ro_number FROM updates "\n            "WHERE date(at) BETWEEN ? AND ? UNION "\n            "SELECT ro_number FROM events WHERE date(at) BETWEEN ? AND ? "\n            "AND actor_id IS NOT NULL)", first, last, first, last)\n\n    return {\n        "How many cars came into the shop this week?":     arrived(7),\n        "How many vehicles came in today?":                arrived(1),\n        "How busy were we this month?":                    arrived(30),\n        "How much work came in over the last 3 days?":     arrived(3),\n        "How many new jobs did we take in?":               arrived(7),\n        "What was our intake this week?":                  arrived(7),\n        "how many cars were worked on yesterday?":         touched(-1),\n        "what are the cars being worked on this week?":    touched(0, 7),\n        "What cars were worked on today?":                 touched(0),\n        "Which vehicles came through yesterday?":          touched(-1),\n    }\n\n\ndef main() -> int:\n    import evaluate as EV                      # the labelled sets, one source\n    from app.agent.agent import ask'),
        ('\n    print(f"{len(EV.ROUTING)} labelled questions, {len(EV.REFUSALS)} action requests")\n\n    rows = []\n    for i, (q, want) in enumerate(EV.ROUTING):\n        try:\n            a = ask(q)\n            rows.append({\n                "id": i,\n                "question": q,\n                "expected_tool": want,\n                "response": a.text or "",\n                "payload": json.dumps(a.results, default=str),\n                "citations": list(a.citations or []),',
         '\n    print(f"{len(EV.ROUTING)} labelled questions, {len(EV.REFUSALS)} action requests")\n\n    from app.agent.tools import _now as _clock\n    TRUTH = _truths(_clock())\n\n    rows = []\n    for i, (q, want) in enumerate(EV.ROUTING):\n        plan = list(want) if isinstance(want, (list, tuple)) else [want]\n        try:\n            a = ask(q)\n            rows.append({\n                "id": i,\n                "question": q,\n                # The primary tool, for the scorer that asks only that, and the\n                # whole plan for the one that scores the arguments too. Pass 54\n                # made this field a tuple and the routing scorer, which does\n                # `target in tools`, quietly started failing every row.\n                "expected_tool": plan[0],\n                "expected_plan": plan,\n                "plan": [{"name": c.get("name"), "args": c.get("args") or {}}\n                         for c in (a.tool_calls or []) if c.get("name")],\n                "truth": TRUTH.get(q),\n                "response": a.text or "",\n                "payload": json.dumps(a.results, default=str),\n                "citations": list(a.citations or []),'),
        ('            # A question that raises is a data point, not a reason to stop. It\n            # scores zero on every measure, which is the honest outcome.\n            rows.append({\n                "id": i, "question": q, "expected_tool": want,\n                "response": "", "payload": "{}", "citations": [], "tools": [],\n                "composed": "", "route": "",\n                "error": f"{type(e).__name__}: {str(e)[:160]}",',
         '            # A question that raises is a data point, not a reason to stop. It\n            # scores zero on every measure, which is the honest outcome.\n            rows.append({\n                "id": i, "question": q, "expected_tool": plan[0],\n                "expected_plan": plan, "plan": [], "truth": TRUTH.get(q),\n                "response": "", "payload": "{}", "citations": [], "tools": [],\n                "composed": "", "route": "",\n                "error": f"{type(e).__name__}: {str(e)[:160]}",'),
    ]),
    ('scripts/eval_standard.py', [
        ('    "asoia_grounding": "evals/data/answers.jsonl",\n    "asoia_traceability": "evals/data/answers.jsonl",\n    "asoia_refusal": "evals/data/refusals.jsonl",\n}\n\n',
         '    "asoia_grounding": "evals/data/answers.jsonl",\n    "asoia_traceability": "evals/data/answers.jsonl",\n    "asoia_refusal": "evals/data/refusals.jsonl",\n    # Added after routing scored 30/30 through a pass that called the right\n    # tool with the wrong arguments, and through another that ran two tools\n    # where one was asked for.\n    "asoia_tool_calls": "evals/data/answers.jsonl",\n    "asoia_accuracy": "evals/data/answers.jsonl",\n    "asoia_relevance": "evals/data/answers.jsonl",\n}\n\n'),
        ('def cross_check(scores: dict) -> list[str]:\n    """Do the two implementations of the shared measures agree?\n\n    routing_accuracy and traceability are defined identically in evaluate.py and\n    in evals/asoia_byob.py, and computed from different inputs by different code.\n    Agreement is real evidence. Disagreement means one of them is wrong, and the\n    point of having two is to be told so rather than to average them.\n    """',
         'def cross_check(scores: dict) -> list[str]:\n    """Do the two implementations of the shared measures agree?\n\n    plan_exact and traceability are defined identically in evaluate.py and in\n    evals/asoia_byob.py, and computed from different inputs by different code.\n    plan_exact and not routing_accuracy: evaluate.py scores the whole plan, so\n    comparing it against the benchmark that asks only whether the right tool is\n    somewhere in the plan was comparing two different questions and calling\n    agreement.\n    Agreement is real evidence. Disagreement means one of them is wrong, and the\n    point of having two is to be told so rather than to average them.\n    """'),
        ('    if not tmp.exists():\n        return [f"evaluate.py produced no json (rc={r.returncode})"]\n    ev = json.loads(tmp.read_text()).get("scores", {})\n    for ours, theirs in (("routing_accuracy", "routing"),\n                         ("traceability", "traceability")):\n        a = scores.get(ours)\n        b = ev.get(theirs)',
         '    if not tmp.exists():\n        return [f"evaluate.py produced no json (rc={r.returncode})"]\n    ev = json.loads(tmp.read_text()).get("scores", {})\n    for ours, theirs in (("plan_exact", "routing"),\n                         ("traceability", "traceability")):\n        a = scores.get(ours)\n        b = ev.get(theirs)'),
        ('        return 0\n    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]\n    print(f"{len(rows)} run(s) recorded; last {min(n, len(rows))}:\\n")\n    keys = ["routing_accuracy", "figures_supported", "traceability",\n            "refused_before_tools"]\n    print("  " + "when".ljust(21) + "".join(k[:18].rjust(20) for k in keys))\n    for r in rows[-n:]:',
         '        return 0\n    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]\n    print(f"{len(rows)} run(s) recorded; last {min(n, len(rows))}:\\n")\n    keys = ["plan_exact", "arg_agreement", "answer_accuracy", "relevance",\n            "routing_accuracy", "figures_supported", "traceability",\n            "refused_before_tools"]\n    print("  " + "when".ljust(21) + "".join(k[:18].rjust(20) for k in keys))\n    for r in rows[-n:]:'),
    ]),
]

done = 0
for rel, pairs in EDITS:
    p = ROOT / rel
    if not p.exists():
        print(f"FAIL: {rel} is missing. Run passes 1-54 first.")
        sys.exit(1)
    t = p.read_text()
    if all(new in t for _, new in pairs):
        print(f"  already   {rel}")
        done += 1
        continue
    for old, new in pairs:
        if t.count(old) != 1:
            print(f"FAIL: {rel}  anchor found {t.count(old)} times, expected 1.")
            print("      Run passes 1-54 first. Stopping without changes.")
            sys.exit(1)
    if not CHECK:
        for old, new in pairs:
            t = t.replace(old, new, 1)
        p.write_text(t)
    print(f"  {'would patch' if CHECK else 'patched  '} {rel}  ({len(pairs)} hunk(s))")

if done == len(EDITS):
    print("  nothing to do - pass 55 is already applied")
