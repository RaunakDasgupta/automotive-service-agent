#!/usr/bin/env python3
"""pass 57 - the handover questions, and the ceiling.

    .venv/bin/python patches/quality_pass57.py            apply
    .venv/bin/python patches/quality_pass57.py --check    verify, change nothing

Pass 56 left two question classes unscored for accuracy and named them: the two
handovers, "whose answer is five prioritised groups with no single headline
figure", and the two free-text searches.

The first half of that was wrong. The handover's second line is four figures:

    46 open repair orders: **14 with safety findings**, 27 at risk of missing
    their promise, 25 blocked, 35 operations still to do.

Every one of those is derivable in SQL, and three of them already were -
n_safety, n_at_risk and n_blocked were written in pass 56 for the list_ros
questions. Only `open` was missing, and it is a count of repair orders whose
last STATE_CHANGED is not INVOICED.

So the scorer now takes a LIST of expected figures rather than one. Checking a
single number from an answer that is mostly numbers leaves the rest
unexamined, and the handover asserts four at once. `figures_per_row` reports
the average so the strength of the measure is visible rather than assumed: 37
rows now carry 41 independently derived numbers.

The handover's groups do not depend on the shift - that word is a label on the
same open work - so both questions take the same four totals. This is also what
makes them a real check on pass 55's fix: if the shift argument went missing
again the heading would change and these four would not, which is why the
heading is scored by asoia_relevance and the figures by this one.

THE FLOOR IS A RATCHET

MIN_ACCURACY_COVERAGE goes 80% -> 90%. It was set at 80 when 89.2% had been
reached and it is raised now that 94.6% has been. A floor left below what has
already been achieved permits the next change to give it back quietly, which is
the failure mode every measure in this repository has had at least once.

94.6% is the ceiling, and it is worth saying that plainly rather than leaving a
gap that looks like unfinished work. The remaining two are "has anyone seen a
whistling noise on a Passat" and "any notes about a burning smell": narrated
prose over retrieved notes, where there is no correct number to check. They are
covered by grounding, traceability and relevance, which are the measures that
apply to prose. There is no 100% here, and a benchmark that claimed one would
be counting something other than accuracy.

    accuracy_scored   89.2%  ->  94.6%   (35 of 37, floor 90%)
    answer_accuracy  100.0%  -> 100.0%   over 41 figures rather than 33
    figures_per_row            ->   1.17
"""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = "--check" in sys.argv

EDITS = [
    ('evals/truth.py', [
        ('               if w == "WAITER" and st.get(ro, "CHECKED_IN") != "INVOICED")\n\n\ndef n_arrived(con, now, days) -> int:\n    since = (now - timedelta(days=days)).isoformat()\n    return con.execute("SELECT count(*) FROM ros WHERE checked_in_at >= ? "',
         '               if w == "WAITER" and st.get(ro, "CHECKED_IN") != "INVOICED")\n\n\ndef n_open(con) -> int:\n    """Repair orders not yet invoiced.\n\n    A repair order with no STATE_CHANGED at all has never left CHECKED_IN, so\n    it is open - which is why this counts from the ros table and looks the\n    state up, rather than counting rows in the state query.\n    """\n    st = _states(con)\n    return sum(1 for (ro,) in con.execute("SELECT ro_number FROM ros")\n               if st.get(ro, "CHECKED_IN") != "INVOICED")\n\n\ndef n_arrived(con, now, days) -> int:\n    since = (now - timedelta(days=days)).isoformat()\n    return con.execute("SELECT count(*) FROM ros WHERE checked_in_at >= ? "'),
    ]),
    ('evals/asoia_byob.py', [
        ('    separately, because a measure that silently skips rows reads as a pass.\n    """\n    truth = inp.target\n    if truth is None or truth == "":\n        return {"answer_accuracy": 1.0, "accuracy_scored": 0.0,\n                "headline_correct": 1.0}\n    want = str(int(truth)) if str(truth).isdigit() or isinstance(truth, int) else str(truth)\n    text = inp.response or ""\n    first = next((ln for ln in text.splitlines() if ln.strip()), "")\n    present = want in NUM_RE.findall(text)\n    # Not every correct answer leads with its number: the anomalies answer opens\n    # with the window it covers and reports the count below. The dataset says\n    # which, so this does not have to guess from the shape of the prose.',
         '    separately, because a measure that silently skips rows reads as a pass.\n    """\n    truth = inp.target\n    if truth is None or truth == "" or truth == []:\n        return {"answer_accuracy": 1.0, "accuracy_scored": 0.0,\n                "headline_correct": 1.0}\n    # A list when one answer states several independently derived numbers. The\n    # handover opens with "46 open repair orders: 14 with safety findings, 27 at\n    # risk, 25 blocked" - four quantities, each derived separately in SQL, and\n    # checking one of them would leave three unexamined in an answer that is\n    # mostly numbers.\n    wants = [str(int(v)) for v in (truth if isinstance(truth, list) else [truth])]\n    want = wants[0]\n    text = inp.response or ""\n    first = next((ln for ln in text.splitlines() if ln.strip()), "")\n    seen = NUM_RE.findall(text)\n    present = all(w in seen for w in wants)\n    # Not every correct answer leads with its number: the anomalies answer opens\n    # with the window it covers and reports the count below. The dataset says\n    # which, so this does not have to guess from the shape of the prose.'),
        ('        # than one that omits it.\n        "headline_correct": (1.0 if (want in NUM_RE.findall(first)) else 0.0)\n                            if leads else 1.0,\n    }\n\n',
         '        # than one that omits it.\n        "headline_correct": (1.0 if (want in NUM_RE.findall(first)) else 0.0)\n                            if leads else 1.0,\n        "figures_per_row": float(len(wants)),\n    }\n\n'),
    ]),
    ('scripts/make_eval_dataset.py', [
        ('# that carry no truth are named here rather than left to be inferred from a\n# gap:\n#\n#   the two handover questions  - the answer is five prioritised groups with no\n#                                 single headline figure to check\n#   the two free-text searches  - narrated prose over retrieved notes; there is\n#                                 no correct number for "has anyone seen a\n#                                 whistling noise"\n#\n# Adding a deterministic question without adding its truth here lowers coverage\n# and fails the run. That is the mechanism that keeps this number moving.',
         '# that carry no truth are named here rather than left to be inferred from a\n# gap:\n#\n#   the two free-text searches  - narrated prose over retrieved notes; there is\n#                                 no correct number for "has anyone seen a\n#                                 whistling noise". These two are the ceiling:\n#                                 35 of 37 is 94.6% and there is no 100%.\n#\n# Adding a deterministic question without adding its truth here lowers coverage\n# and fails the run. That is the mechanism that keeps this number moving.'),
        ('        "Any unusual patterns in the shop this week?":          anywhere(shared),\n        "Are any parts holding up more than one job at once?":  anywhere(shared),\n        "Is the same part blocking several jobs?":              anywhere(shared),\n        "What has EMP014 done this week?":      lead(T.n_ops_by(con, "EMP014", now)),\n        "How has EMP021 been getting on?":      lead(T.n_ops_by(con, "EMP021", now)),\n        "Who worked in the afternoon yesterday?":',
         '        "Any unusual patterns in the shop this week?":          anywhere(shared),\n        "Are any parts holding up more than one job at once?":  anywhere(shared),\n        "Is the same part blocking several jobs?":              anywhere(shared),\n        # The handover states four totals on its own second line, and its\n        # groups do not depend on the shift - that word is a label. Checking\n        # all four is the whole of what this answer asserts numerically.\n        "Give me the afternoon handover, worst first.":\n            anywhere([T.n_open(con), safety, at_risk, blocked]),\n        "Hand over to the morning shift.":\n            anywhere([T.n_open(con), safety, at_risk, blocked]),\n        "What has EMP014 done this week?":      lead(T.n_ops_by(con, "EMP014", now)),\n        "How has EMP021 been getting on?":      lead(T.n_ops_by(con, "EMP021", now)),\n        "Who worked in the afternoon yesterday?":'),
    ]),
    ('scripts/eval_standard.py', [
        ('\n\n\nMIN_ACCURACY_COVERAGE = 0.80\n# A benchmark that scores 10 of 37 rows and reports 100% is reporting the rows\n# it chose. accuracy_scored is the share of questions carrying an independently\n# derived number, and it is gated: add a deterministic question without adding',
         '\n\n\n# Ratcheted. 80% when 89.2% was reached, 90% now that the two handover\n# questions are scored and 94.6% is - which is the ceiling, because the two\n# free-text searches have no correct number. The floor is raised deliberately\n# each time coverage rises: a floor left below what has been achieved permits\n# the next change to give it back.\nMIN_ACCURACY_COVERAGE = 0.90\n# A benchmark that scores 10 of 37 rows and reports 100% is reporting the rows\n# it chose. accuracy_scored is the share of questions carrying an independently\n# derived number, and it is gated: add a deterministic question without adding'),
    ]),
]

done = 0
for rel, pairs in EDITS:
    p = ROOT / rel
    if not p.exists():
        print(f"FAIL: {rel} is missing. Run passes 1-56 first.")
        sys.exit(1)
    t = p.read_text()
    if all(new in t for _, new in pairs):
        print(f"  already   {rel}")
        done += 1
        continue
    for old, new in pairs:
        if t.count(old) != 1:
            print(f"FAIL: {rel}  anchor found {t.count(old)} times, expected 1.")
            print("      Run passes 1-56 first. Stopping without changes.")
            sys.exit(1)
    if not CHECK:
        for old, new in pairs:
            t = t.replace(old, new, 1)
        p.write_text(t)
    print(f"  {'would patch' if CHECK else 'patched  '} {rel}  ({len(pairs)} hunk(s))")

if done == len(EDITS):
    print("  nothing to do - pass 57 is already applied")
