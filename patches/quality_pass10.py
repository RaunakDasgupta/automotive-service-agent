#!/usr/bin/env python3
"""Tenth pass: fix the citation collector regression introduced in pass 8.

Run from the project root:   python3 quality_pass10.py

WHAT BROKE
Pass 8 added "ros" to the list-valued keys that _collect_citations harvests,
because detect_anomalies stores repair-order numbers as
`shared_part_holds[].ros` - a list of STRINGS.

But list_ros returns a top-level `ros` key holding a list of DICTS, one per
repair order. `cits.extend(str(x) for x in v)` therefore stringified each whole
record into the citations list, so every list_ros answer carried a dozen
pretty-printed dicts as its "citations" instead of repair-order numbers. In the
UI that is a wall of raw dict text in the footer.

THE FIX
Harvest those list keys only when every element is a string. Otherwise fall
through to walk(), which finds the nested `ro_number` of each record exactly as
it did before pass 8. Both shapes now work:

  {"ros": ["RO-26-08167", "RO-26-08201"]}          -> harvested directly
  {"ros": [{"ro_number": "RO-26-08316", ...}, ...]} -> walked, ro_number found

Caught by verify_answers.py, which is the point of having it: the citations were
never checked against the payload before, so this would have shipped.
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
     '''                # `ros` matters: detect_anomalies puts its repair order
                # numbers there, and without it a correct shared-part or
                # repeat-visit answer cites nothing and the rail blocks it.
                if k in ("citations", "event_ids", "ros", "ro_numbers") \\
                        and isinstance(v, list):
                    cits.extend(str(x) for x in v)''',
     '''                # `ros` matters: detect_anomalies puts its repair order
                # numbers there, and without it a correct shared-part or
                # repeat-visit answer cites nothing and the rail blocks it.
                # But list_ros ALSO has a top-level `ros`, holding whole records
                # rather than ids - so only harvest when the list really is ids,
                # and otherwise walk into it for the nested ro_number.
                if (k in ("citations", "event_ids", "ros", "ro_numbers")
                        and isinstance(v, list)
                        and all(isinstance(x, str) for x in v)):
                    cits.extend(v)''',
     "agent.py  only harvest id lists, walk record lists",
     skip_if="all(isinstance(x, str) for x in v)")

print("Quality pass 10:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/agent/agent.py").read_text())
print("\nagent.py parses cleanly.")

# ---------------------------------------------------------------- prove it
import json as _json
src = (ROOT / "app/agent/agent.py").read_text()
ns: dict = {}
s = src.index("def _collect_citations"); e = src.index("\ndef ", s + 5)
exec(src[s:e], ns)
f = ns["_collect_citations"]

SHAPES = {
    "list_ros (records under `ros`)": {
        "filter": "safety", "count": 2, "shown": 2,
        "ros": [{"ro_number": "RO-26-08316", "vehicle": "2017 Volkswagen Golf",
                 "safety": True, "safety_detail": ["tyre_tread_nsf 1.5mm below minimum 1.6mm"],
                 "pending": ["CV axle shaft R&R"]},
                {"ro_number": "RO-26-08062", "vehicle": "2018 Mercedes C-Class",
                 "safety": True, "safety_detail": ["pad_thickness 2.4mm below minimum 3.0mm"],
                 "pending": ["Rear brake pads & rotors R&R"]}]},
    "detect_anomalies (ids under `ros`)": {
        "window_days": 7,
        "shared_part_holds": [{"part_no": "87103-G4M-B40", "ro_count": 2,
                               "ros": ["RO-26-08167", "RO-26-08201"]}],
        "repeat_visits": [{"vin": "WVW1", "visits": 2,
                           "ros": ["RO-26-08001", "RO-26-08144"]}],
        "stalled_ros": [], "authorisation_delays": [], "comebacks": []},
    "get_ro_state (event ids)": {
        "found": True, "ro_number": "RO-26-08316", "citations": ["EV-7", "EV-8"]},
}
print("\ncitations by payload shape:")
ok = True
for name, res in SHAPES.items():
    results = [{"tool": "t", "args": {}, "result": res}]
    cits = f(results)
    blob = _json.dumps(results, default=str)
    ghosts = [c for c in cits if c not in blob]
    clean = bool(cits) and not ghosts and all(len(c) < 40 for c in cits)
    ok = ok and clean
    print(f"  {'ok     ' if clean else 'BROKEN '} {name}")
    print(f"           {cits}")
    if ghosts:
        print(f"           not in payload: {ghosts}")
print("\nall shapes produce clean id citations" if ok else "\nSTILL BROKEN")
print("Next:  python3 quality_pass9.py   (if not yet applied)")
print("Then:  .venv/bin/python scripts/verify_answers.py")
