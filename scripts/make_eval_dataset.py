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
# Computed with direct SQL that does not touch app.agent.tools. A benchmark
# scored against the thing it is testing is not a benchmark, so the number an
# answer is checked against has to come from somewhere else.
#
# Only the questions whose truth is a straightforward query are here. A count of
# blocked or unsafe repair orders is derived by folding the event log, and a
# second fold written here would be the same code twice rather than independent
# evidence - which is the mistake the rail harness made in section 13. Those
# questions carry no truth and are not scored for accuracy, and saying which
# ones are unscored is part of the measure.
def _truths(now):
    import sqlite3, os
    from datetime import timedelta
    db = os.environ.get("ASOIA_DB", "data/generated/service.sqlite")
    con = sqlite3.connect(db)

    def one(sql, *args):
        return con.execute(sql, args).fetchone()[0]

    def arrived(days):
        since = (now - timedelta(days=days)).isoformat()
        return one("SELECT count(*) FROM ros WHERE checked_in_at >= ? "
                   "AND checked_in_at <= ?", since, now.isoformat())

    def touched(day_offset, days=1):
        last = (now + timedelta(days=day_offset)).date().isoformat()
        first = (now + timedelta(days=day_offset - days + 1)).date().isoformat()
        return one(
            "SELECT count(*) FROM (SELECT ro_number FROM updates "
            "WHERE date(at) BETWEEN ? AND ? UNION "
            "SELECT ro_number FROM events WHERE date(at) BETWEEN ? AND ? "
            "AND actor_id IS NOT NULL)", first, last, first, last)

    return {
        "How many cars came into the shop this week?":     arrived(7),
        "How many vehicles came in today?":                arrived(1),
        "How busy were we this month?":                    arrived(30),
        "How much work came in over the last 3 days?":     arrived(3),
        "How many new jobs did we take in?":               arrived(7),
        "What was our intake this week?":                  arrived(7),
        "how many cars were worked on yesterday?":         touched(-1),
        "what are the cars being worked on this week?":    touched(0, 7),
        "What cars were worked on today?":                 touched(0),
        "Which vehicles came through yesterday?":          touched(-1),
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
                "truth": TRUTH.get(q),
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
                "expected_plan": plan, "plan": [], "truth": TRUTH.get(q),
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
