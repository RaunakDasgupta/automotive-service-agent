"""The project's answer-level measures as NeMo Evaluator BYOB benchmarks.

    .venv/bin/python scripts/eval_standard.py

WHY THIS EXISTS

`scripts/evaluate.py` prints six measures to a terminal. They are good measures and
they are not a benchmark: there is no record of a run, no schema, and nothing to
compare this release against the last one with. A loop that is supposed to improve
needs a yardstick that outlives the terminal it was printed in.

These benchmarks produce NeMo Evaluator's own result schema:

    {"tasks": {"asoia_routing": {"metrics": {"pass@1": {"scores":
      {"routing_accuracy": {"stats": {"count": 24, "mean": 1.0, ...},
                            "value": 1.0}}}}}}}

HOW IT FITS AN AGENT RATHER THAN A MODEL

BYOB benchmarks normally send a prompt to an endpoint and score the reply. This
agent is not an endpoint: an answer is composed in Python from tool results, and
only one of six question classes reaches a model at all. `response_field` is the
feature that makes it work - when set, "the model is not called and responses are
read directly from the dataset". So `scripts/make_eval_dataset.py` runs the agent,
records what it answered and what it answered FROM, and these score those rows.

THE SCORERS DEPEND ONLY ON THE ROW

Nothing here imports `app`. Everything a scorer needs - the response, the payload
it was built from, the citations, the tools that ran - is in the dataset, so a run
is reproducible by anyone holding the JSONL, which is the point of a benchmark.

It also means these are a SECOND, INDEPENDENT implementation of two measures
evaluate.py already computes. That is deliberate. `scripts/eval_standard.py`
cross-checks routing and traceability against evaluate.py and fails if they
disagree: two implementations that agree is stronger evidence than one shared
helper, and this project has been bitten more than once by a single helper that
was confidently wrong in both places at once.
"""
from __future__ import annotations
import re

from nemo_evaluator.contrib.byob import ScorerInput, benchmark

# Same shape as evaluate.py's: a run of digits that is not part of a word, an
# identifier or a decimal fragment. Written out rather than imported, because a
# scorer that reaches into the project is a scorer that cannot be shipped with the
# dataset.
NUM_RE = re.compile(r"(?<![\w.\-])\d+(?:\.\d+)?(?![\w.\-\d])")


@benchmark(
    name="asoia_routing",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="expected_tool",
    response_field="response",
)
def routing(inp: ScorerInput) -> dict:
    """Did the question reach the tool that can answer it?

    The weakest link in the system and the one nothing structural prevents: an
    answer can be perfectly grounded and about the wrong repair order.
    """
    ran = inp.metadata.get("tools") or []
    return {"routing_accuracy": 1.0 if inp.target in ran else 0.0}


@benchmark(
    name="asoia_grounding",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="payload",
    response_field="response",
)
def grounding(inp: ScorerInput) -> dict:
    """Every figure in the answer must appear in the payload it was built from.

    `target` is the serialised tool payload rather than a gold answer. That is a
    liberty with the field's name and the right ground truth for the question
    being asked: there is no correct wording for these answers, only a rule about
    where their numbers may come from.

    Named `figures_supported` and not `grounded` on purpose. evaluate.py's
    grounding measure also checks negations, citation existence and the output
    rail; this checks one of those four things, and a metric that claims more than
    it tests is how a benchmark starts lying.
    """
    blob = inp.target if isinstance(inp.target, str) else str(inp.target)
    found = {n for n in NUM_RE.findall(inp.response or "") if len(n) >= 2}
    missing = sorted(n for n in found if n not in blob)
    return {"figures_supported": 0.0 if missing else 1.0,
            "unsupported_figures": float(len(missing))}


@benchmark(
    name="asoia_traceability",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="payload",
    response_field="response",
)
def traceability(inp: ScorerInput) -> dict:
    """Of the citations an answer carries, how many resolve in its payload.

    The capstone's acceptance criteria ask for 100% of findings linked to
    evidence. This is that criterion, with a number attached to it.
    """
    blob = inp.target if isinstance(inp.target, str) else str(inp.target)
    cites = list(inp.metadata.get("citations") or [])
    unresolved = [c for c in cites if c not in blob]
    return {"traceability": 1.0 if not unresolved else 0.0,
            "citations": float(len(cites)),
            "unresolved_citations": float(len(unresolved))}


@benchmark(
    name="asoia_refusal",
    dataset="data/refusals.jsonl",
    prompt="{question}",
    target_field="expected",
    response_field="response",
)
def refusal(inp: ScorerInput) -> dict:
    """An action request must be refused BEFORE any tool runs.

    `refused_before_tools` is recorded by the dataset builder from the input rail's
    own verdict, so this scorer checks the recorded fact rather than re-deriving a
    safety decision from prose - which would be a worse test than the rail.
    """
    return {"refused_before_tools": 1.0 if inp.metadata.get("refused") else 0.0}


# ===========================================================================
# Tool calling, scored at the ARGUMENT level
# ===========================================================================
# Routing above asks whether the right tool ran. It cannot see a right tool
# called with wrong arguments, and it cannot see a second tool that should not
# have run at all. Both happened in pass 53: "how many cars were worked on
# yesterday" reached get_intake with days=7, and "how many cars are blocked"
# ran list_ros AND get_intake. Routing scored 30/30 through both.
#
# The expectations here are derived from the QUESTION, not from a gold table.
# A table of expected arguments is another thing to keep in step with the
# router, and the two would drift; the words in the question are the ground
# truth about what was asked.
_DAY = [
    (re.compile(r"\byesterday\b|\bovernight\b|\blast night\b", re.I), -1),
    (re.compile(r"\bday before yesterday\b|\btwo days ago\b", re.I), -2),
    (re.compile(r"\btoday\b|\bthis morning\b|\bthis afternoon\b|\btonight\b", re.I), 0),
]
_SHIFT = [
    (re.compile(r"\bafternoon\b|\bevening\b|\bovernight\b|\blast night\b", re.I), "AFTERNOON"),
    (re.compile(r"\bmorning\b", re.I), "MORNING"),
]
_WINDOW = [
    (re.compile(r"\blast (\d+) weeks?\b|\bpast (\d+) weeks?\b", re.I), None),
    (re.compile(r"\blast (\d+) days?\b|\bpast (\d+) days?\b", re.I), None),
    (re.compile(r"\bthis month\b|\blast month\b|\bmonthly\b", re.I), 30),
    (re.compile(r"\bthis week\b|\blast week\b|\bpast week\b|\bweekly\b|\bseven days\b", re.I), 7),
    (re.compile(r"\btoday\b|\bthis morning\b|\bthis afternoon\b", re.I), 1),
]
_VEHICLE_WORD = re.compile(r"\bcars?\b|\bvehicles?\b|\bmotors?\b|\bjobs?\b"
                           r"|\brepair orders?\b|\bros?\b", re.I)
_PEOPLE_WORD = re.compile(r"\bwho\b|\btechnicians?\b|\bstaff\b|\bteam\b|\bpeople\b", re.I)
_FILTER = [
    (re.compile(r"\bsafety|unsafe|dangerous|released?\b", re.I), "safety"),
    (re.compile(r"\bblocked|parts hold|waiting (on|for) parts|held up\b", re.I), "blocked"),
    (re.compile(r"\bat.risk|late|overdue|breach|promis|miss\w*\b", re.I), "at_risk"),
    (re.compile(r"\bwaiter|customers? waiting|waiting on site\b", re.I), "waiter"),
]


def _window_of(q: str):
    for rx, fixed in _WINDOW:
        m = rx.search(q)
        if not m:
            continue
        if fixed is not None:
            return fixed
        n = next((g for g in m.groups() if g), None)
        if n is None:
            return None
        return int(n) * (7 if "week" in m.group(0).lower() else 1)
    return None


def _arg_rules(question: str, call: dict):
    """Every expectation the QUESTION creates for this call: (name, ok)."""
    q, name, args = question, call.get("name"), call.get("args") or {}
    out = []
    if name == "get_intake":
        want = _window_of(q)
        out.append(("intake.days", args.get("days") == (want or 7)))
    if name == "get_shift_activity":
        day = next((v for rx, v in _DAY if rx.search(q)), 0)
        out.append(("activity.day_offset", int(args.get("day_offset", 0)) == day))
        sh = next((v for rx, v in _SHIFT if rx.search(q)), None)
        if sh:
            out.append(("activity.shift", str(args.get("shift", "")).upper() == sh))
        if _VEHICLE_WORD.search(q) and not _PEOPLE_WORD.search(q):
            out.append(("activity.view", args.get("view") == "vehicles"))
        elif _PEOPLE_WORD.search(q):
            out.append(("activity.view", args.get("view") == "people"))
        win = _window_of(q)
        if win and win > 1:
            out.append(("activity.days", int(args.get("days", 1)) == win))
    if name == "generate_handover":
        sh = next((v for rx, v in _SHIFT if rx.search(q)), None)
        if sh:
            out.append(("handover.shift", str(args.get("shift", "")).upper() == sh))
    if name == "list_ros":
        want = next((v for rx, v in _FILTER if rx.search(q)), None)
        if want:
            out.append(("list_ros.filter", args.get("filter") == want))
    return out


@benchmark(
    name="asoia_tool_calls",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="expected_plan",
    response_field="response",
)
def tool_calls(inp: ScorerInput) -> dict:
    """The whole call: the right tools, no others, with arguments the question asked for."""
    want = inp.target if isinstance(inp.target, list) else [inp.target]
    plan = list(inp.metadata.get("plan") or [])
    got = [c.get("name") for c in plan]
    checks = [ok for c in plan for _, ok in _arg_rules(inp.metadata.get("question", ""), c)]
    spurious = [n for n in got if n not in want]
    return {
        "plan_exact": 1.0 if got == list(want) else 0.0,
        "spurious_tools": float(len(spurious)),
        "arg_agreement": (sum(1.0 for c in checks if c) / len(checks)) if checks else 1.0,
        "arg_rules_checked": float(len(checks)),
    }


# ===========================================================================
# Accuracy against a number this scorer did not produce
# ===========================================================================
@benchmark(
    name="asoia_accuracy",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="truth",
    response_field="response",
)
def accuracy(inp: ScorerInput) -> dict:
    """Does the answer state the number, and state it FIRST?

    `truth` is computed in make_eval_dataset.py by direct SQL that never touches
    the agent's tools, so this is the one measure here that could catch a tool
    which is wrong in the same way its renderer is. Rows with no truth - the
    ones whose answer needs the event log folded - are scored 1.0 and counted
    separately, because a measure that silently skips rows reads as a pass.
    """
    truth = inp.target
    if truth is None or truth == "" or truth == []:
        return {"answer_accuracy": 1.0, "accuracy_scored": 0.0,
                "headline_correct": 1.0}
    # A list when one answer states several independently derived numbers. The
    # handover opens with "46 open repair orders: 14 with safety findings, 27 at
    # risk, 25 blocked" - four quantities, each derived separately in SQL, and
    # checking one of them would leave three unexamined in an answer that is
    # mostly numbers.
    wants = [str(int(v)) for v in (truth if isinstance(truth, list) else [truth])]
    want = wants[0]
    text = inp.response or ""
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    seen = NUM_RE.findall(text)
    present = all(w in seen for w in wants)
    # Not every correct answer leads with its number: the anomalies answer opens
    # with the window it covers and reports the count below. The dataset says
    # which, so this does not have to guess from the shape of the prose.
    leads = inp.metadata.get("truth_headline", True)
    return {
        "answer_accuracy": 1.0 if present else 0.0,
        "accuracy_scored": 1.0,
        # The pass-53 failure stated a real number from the wrong question. A
        # headline that leads with a figure that is not the answer is worse
        # than one that omits it.
        "headline_correct": (1.0 if (want in NUM_RE.findall(first)) else 0.0)
                            if leads else 1.0,
        "figures_per_row": float(len(wants)),
    }


# ===========================================================================
# Relevance: is this an answer to THIS question
# ===========================================================================
_META = re.compile(
    r"\bthe search returned\b|\bas per the guidelines?\b|\bthe passages?\b"
    r"|\bthe updates (provided|mention|also)\b|\bthe notes (provided|mention)\b"
    r"|\bI'?m sorry\b|\bI cannot\b|\bI am unable\b|\bas an AI\b"
    r"|\brepeat_call\b|\bper your instruction", re.I)
_RO = re.compile(r"\bRO-\d{2}-\d{4,5}\b", re.I)
_STAFF = re.compile(r"\b(EMP|ADV|FOR|PRT|MGR)\d{3}\b", re.I)
_COUNT_Q = re.compile(r"\bhow many\b|\bhow much\b|\bhow busy\b", re.I)
_OPEN_Q = re.compile(r"^\s*(which|what|who|where|when)\b", re.I)


# "This week" is answered by "the 7 days to 28 September". The entity is the
# window, not the word, so each one carries the forms that satisfy it - without
# this the scorer marked six correct answers down for being more precise than
# the question.
_ENTITY_FORMS = {
    "week": ("week", "7 days", "seven days"),
    "month": ("month", "30 days", "thirty days"),
    "morning": ("morning",),
    "afternoon": ("afternoon", "evening"),
    "yesterday": ("yesterday",),
    "safety": ("safety", "unsafe"),
    "part": ("part", "blocked"),
    "promis": ("promis", "late", "overdue"),
    "waiting": ("waiting", "waiter"),
}


def _covers(entity: str, text_up: str, text_low: str) -> bool:
    forms = _ENTITY_FORMS.get(entity)
    if forms:
        return any(f in text_low for f in forms)
    return entity.upper() in text_up


def _question_entities(q: str):
    """What the question is about, in terms an answer can be checked against."""
    ents = set(m.group(0).upper() for m in _RO.finditer(q))
    ents |= set(m.group(0).upper() for m in _STAFF.finditer(q))
    for rx, word in ((re.compile(r"\bsafety|unsafe|dangerous\b", re.I), "safety"),
                     (re.compile(r"\bblocked|parts\b", re.I), "part"),
                     (re.compile(r"\bpromis|late|overdue\b", re.I), "promis"),
                     (re.compile(r"\bwaiting|waiter\b", re.I), "waiting"),
                     (re.compile(r"\bmorning\b", re.I), "morning"),
                     (re.compile(r"\bafternoon\b", re.I), "afternoon"),
                     (re.compile(r"\byesterday\b", re.I), "yesterday"),
                     (re.compile(r"\bweek\b", re.I), "week"),
                     (re.compile(r"\bmonth\b", re.I), "month")):
        if rx.search(q):
            ents.add(word)
    return ents


@benchmark(
    name="asoia_relevance",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="question",
    response_field="response",
)
def relevance(inp: ScorerInput) -> dict:
    """An answer can be perfectly grounded and still not be an answer.

    Three things, each a coefficient in [0, 1] and each a failure this project
    has actually shipped:

      answers_the_form  a "how many" question whose first line carries no number
                        was the pass-53 regression; a "which" question with no
                        entity named is the search answer that listed three cars.
      entity_coverage   the share of what the question named that the answer
                        mentions. An answer about the wrong repair order scores
                        zero here while grounding scores one.
      free_of_meta      no "the search returned", no "as per the guidelines",
                        no apology. Prose about the machinery is not an answer,
                        and every one of these phrases was in a shipped reply.

    `relevance` is their mean, reported alongside the three so a middling score
    can be read rather than guessed at.
    """
    q = inp.target if isinstance(inp.target, str) else str(inp.target)
    text = (inp.response or "").strip()
    first = next((ln for ln in text.splitlines() if ln.strip()), "")

    if not text:
        form = 0.0
    elif _COUNT_Q.search(q):
        form = 1.0 if NUM_RE.findall(first) else 0.0
    elif _OPEN_Q.search(q):
        named = bool(_RO.search(text) or _STAFF.search(text)
                     or NUM_RE.findall(first))
        none_said = re.search(r"\bno\b|\bnone\b|\bnothing\b", first, re.I)
        form = 1.0 if (named or none_said) else 0.0
    else:
        form = 1.0 if text else 0.0

    ents = _question_entities(q)
    up, low = text.upper(), text.lower()
    hit = sum(1 for e in ents if _covers(e, up, low))
    coverage = (hit / len(ents)) if ents else 1.0
    meta = 0.0 if _META.search(text) else 1.0
    return {"relevance": round((form + coverage + meta) / 3, 4),
            "answers_the_form": form,
            "entity_coverage": round(coverage, 4),
            "free_of_meta": meta}
