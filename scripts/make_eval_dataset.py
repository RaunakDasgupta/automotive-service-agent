#!/usr/bin/env python3
"""Run the agent over the versioned question sets and record what it answered.

    .venv/bin/python scripts/make_eval_dataset.py

Writes two JSONL datasets for evals/asoia_byob.py:

    evals/data/answers.jsonl   one row per labelled question
    evals/data/refusals.jsonl  one row per action request

The questions come from `scripts/evaluate.py` - ROUTING and REFUSALS - imported
rather than copied, so there is one place where the labelled set lives and the
benchmark cannot drift from the evaluator that shares it.

WHAT A ROW CARRIES, AND WHY

    question        the prompt, which is also the benchmark's rendered prompt
    expected_tool   the label
    response        what the agent said
    payload         json.dumps of the tool results the answer was built from
    citations       the ids the answer carried
    tools           the tools that actually ran
    composed        "python" or "llm" - which path wrote the words
    route           which router decided

`payload` is the interesting one. It makes every row self-contained: a scorer can
check "is this figure in the evidence" without the database, the index, the NIMs or
the project, which is what lets the benchmark be shipped, containerised or handed
to someone else. The dataset is the evidence, not a pointer to it.

THE QUESTIONS ARE FIXED, THE RESPONSES ARE THE MEASUREMENT

Regenerate this before every run. The point is not a frozen corpus - it is the same
questions asked of a changed system, which is the only comparison that means
anything between releases.
"""
from __future__ import annotations
import json
import pathlib
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

OUT = pathlib.Path("evals/data")



# --- independent ground truth ----------------------------------------------
# Every value comes from evals/truth.py, which derives it in SQL from the raw
# event log and never imports `app`. Two implementations in two languages that
# agree is evidence; one implementation checked against itself is not.
#
# Coverage is a measure in its own right. asoia_accuracy reports
# accuracy_scored, eval_standard.py fails below 80%, and the four questions
# that carry no truth are named here rather than left to be inferred from a
# gap:
#
#   the two handover questions  - the answer is five prioritised groups with no
#                                 single headline figure to check
#   the two free-text searches  - narrated prose over retrieved notes; there is
#                                 no correct number for "has anyone seen a
#                                 whistling noise"
#
# Adding a deterministic question without adding its truth here lowers coverage
# and fails the run. That is the mechanism that keeps this number moving.
def _truths(now):
    import sqlite3, os, sys
    sys.path.insert(0, ".")
    from evals import truth as T
    db = os.environ.get("ASOIA_DB", "data/generated/service.sqlite")
    con = sqlite3.connect(db)

    safety = T.n_safety(con)
    blocked = T.n_blocked(con)
    at_risk = T.n_at_risk(con, now)
    waiter = T.n_waiter(con)
    shared = T.n_shared_part_holds(con, now)

    def lead(v):
        return (v, True)

    def anywhere(v):
        return (v, False)

    return {
        "Which vehicles cannot be released on safety grounds?": lead(safety),
        "Anything dangerous out there?":                        lead(safety),
        "What is unsafe to release?":                           lead(safety),
        "how many vehicles are unsafe to release?":             lead(safety),
        "Which jobs are blocked waiting for parts?":            lead(blocked),
        "What is held up on parts?":                            lead(blocked),
        "how many cars are blocked waiting for parts?":         lead(blocked),
        "Which jobs will miss their promised time?":            lead(at_risk),
        "What is running late?":                                lead(at_risk),
        "how many jobs will miss their promised time?":         lead(at_risk),
        "Are there any customers waiting on site?":             lead(waiter),
        "Any waiters in today?":                                lead(waiter),
        "how many customers are waiting on site?":              lead(waiter),
        # The anomalies answer leads with its window, not with a count.
        "Any unusual patterns in the shop this week?":          anywhere(shared),
        "Are any parts holding up more than one job at once?":  anywhere(shared),
        "Is the same part blocking several jobs?":              anywhere(shared),
        "What has EMP014 done this week?":      lead(T.n_ops_by(con, "EMP014", now)),
        "How has EMP021 been getting on?":      lead(T.n_ops_by(con, "EMP021", now)),
        "Who worked in the afternoon yesterday?":
            lead(T.n_people(con, now, -1, shift="AFTERNOON")),
        "Who was in this morning?":   lead(T.n_people(con, now, 0, shift="MORNING")),
        "who came in this morning?":  lead(T.n_people(con, now, 0, shift="MORNING")),
        "What happened overnight?":
            lead(T.n_people(con, now, -1, shift="AFTERNOON")),
        "Which technicians were on duty today?": lead(T.n_people(con, now, 0)),
        "What cars were worked on today?":       lead(T.n_touched(con, now, 0)),
        "Which vehicles came through yesterday?": lead(T.n_touched(con, now, -1)),
        "how many cars were worked on yesterday?": lead(T.n_touched(con, now, -1)),
        "what are the cars being worked on this week?":
            lead(T.n_touched(con, now, 0, 7)),
        "How many cars came into the shop this week?": lead(T.n_arrived(con, now, 7)),
        "How many vehicles came in today?":            lead(T.n_arrived(con, now, 1)),
        "How busy were we this month?":                lead(T.n_arrived(con, now, 30)),
        "How much work came in over the last 3 days?": lead(T.n_arrived(con, now, 3)),
        "How many new jobs did we take in?":           lead(T.n_arrived(con, now, 7)),
        "What was our intake this week?":              lead(T.n_arrived(con, now, 7)),
    }


def main() -> int:
    import evaluate as EV                      # the labelled sets, one source
    from app.agent.agent import ask
    from app.guardrails.rails import check_input

    OUT.mkdir(parents=True, exist_ok=True)
    answers = OUT / "answers.jsonl"
    refusals = OUT / "refusals.jsonl"

    print(f"{len(EV.ROUTING)} labelled questions, {len(EV.REFUSALS)} action requests")

    from app.agent.tools import _now as _clock
    TRUTH = _truths(_clock())

    rows = []
    for i, (q, want) in enumerate(EV.ROUTING):
        plan = list(want) if isinstance(want, (list, tuple)) else [want]
        try:
            a = ask(q)
            rows.append({
                "id": i,
                "question": q,
                # The primary tool, for the scorer that asks only that, and the
                # whole plan for the one that scores the arguments too. Pass 54
                # made this field a tuple and the routing scorer, which does
                # `target in tools`, quietly started failing every row.
                "expected_tool": plan[0],
                "expected_plan": plan,
                "plan": [{"name": c.get("name"), "args": c.get("args") or {}}
                         for c in (a.tool_calls or []) if c.get("name")],
                "truth": (TRUTH.get(q) or (None, True))[0],
                "truth_headline": (TRUTH.get(q) or (None, True))[1],
                "response": a.text or "",
                "payload": json.dumps(a.results, default=str),
                "citations": list(a.citations or []),
                "tools": [c.get("name") for c in (a.tool_calls or []) if c.get("name")],
                "composed": getattr(a, "composed", ""),
                "route": getattr(a, "route", ""),
                "warnings": list(a.warnings or []),
            })
        except Exception as e:
            # A question that raises is a data point, not a reason to stop. It
            # scores zero on every measure, which is the honest outcome.
            rows.append({
                "id": i, "question": q, "expected_tool": plan[0],
                "expected_plan": plan, "plan": [],
                "truth": (TRUTH.get(q) or (None, True))[0],
                "truth_headline": (TRUTH.get(q) or (None, True))[1],
                "response": "", "payload": "{}", "citations": [], "tools": [],
                "composed": "", "route": "",
                "error": f"{type(e).__name__}: {str(e)[:160]}",
            })
            print(f"  raised  {q!r}: {type(e).__name__}")

    answers.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"  wrote {answers}  ({len(rows)} rows)")

    rrows = []
    for i, q in enumerate(EV.REFUSALS):
        g = check_input(q)
        rrows.append({
            "id": i,
            "question": q,
            "expected": "refuse",
            # The rail's replacement text, which is what a user would see. Empty
            # when it allowed the question through - and that is the failure.
            "response": (g.text or "") if not g.allowed else "",
            "refused": (not g.allowed),
            "rail": g.rail or "",
        })
    refusals.write_text("".join(json.dumps(r) + "\n" for r in rrows))
    print(f"  wrote {refusals}  ({len(rrows)} rows)")

    n_py = sum(1 for r in rows if r.get("composed") == "python")
    print(f"\n  {n_py} of {len(rows)} answers were composed in Python "
          f"(no model call)")
    print(f"  {sum(1 for r in rrows if r['refused'])} of {len(rrows)} "
          f"action requests were refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
