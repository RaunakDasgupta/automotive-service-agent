#!/usr/bin/env python3
"""Ninth pass: natural phrasings reach the waiter filter.

Run from the project root:   python3 quality_pass9.py

The `waiter` filter exists and works, but the only phrasings that reached it were
"waiter" and the exact words "waiting customer". A service manager asks "are
there any customers waiting on site?", which matched nothing and fell through to
the catch-all semantic search - answered by the LLM, from update text, instead of
by the filter that knows the answer.

Found by verify_answers.py disagreeing with its own expectation, which is what
the harness is for.
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
                 "      Run passes 1-8 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


edit("app/agent/agent.py",
     '''    (r"\\bwaiter|waiting customer\\b", "list_ros", {"filter": "waiter"}),''',
     '''    (r"\\bwaiter|waiting customer|customers? waiting|waiting on site|"
     r"wait(ing)? in reception\\b", "list_ros", {"filter": "waiter"}),''',
     "agent.py  waiter filter reached by natural phrasings",
     skip_if="customers? waiting")

print("Quality pass 9:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/agent/agent.py").read_text())
print("\nagent.py parses cleanly.")

# Prove the routing, and prove nothing else moved.
import re
src = (ROOT / "app/agent/agent.py").read_text()
ns = {"re": re,
      "RO_RE": re.compile(r"\bRO[- ]?\d{2}[- ]?\d{4,5}\b", re.I),
      "ID_RE": re.compile(r"\b(EMP|ADV|FOR|PRT|MGR)\d{3}\b", re.I)}
exec(src[src.index("KEYWORDS = ["):src.index("RO_RE = re.compile")], ns)
s = src.index("def plan_keyword"); e = src.index("\ndef ", s + 5)
exec(src[s:e], ns)

EXPECT = [
    ("Are there any customers waiting on site?",      "list_ros"),
    ("Any waiters in today?",                         "list_ros"),
    ("Which jobs are blocked waiting for parts?",     "list_ros"),
    ("Which vehicles cannot be released on safety grounds?", "list_ros"),
    ("Give me the afternoon handover, worst first.",  "generate_handover"),
    ("What has EMP014 done this week?",               "get_technician_activity"),
    ("Any unusual patterns in the shop this week?",   "detect_anomalies"),
    ("has anyone seen a whistling noise on a Passat", "search_updates"),
]
print("\nrouting:")
bad = 0
for q, want in EXPECT:
    tools = [c["name"] for c in ns["plan_keyword"](q)]
    ok = want in tools
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {tools}  <- {q}")
print(f"\n{bad} unexpected" if bad else "\nall routings as expected")
print("Next:  .venv/bin/python verify_answers.py")
