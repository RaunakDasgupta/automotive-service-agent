#!/usr/bin/env python3
"""Fifteenth pass: two ways resolve_op confidently returns the wrong operation.

Run from the project root:   python3 quality_pass15.py

Both found by running real dictated updates through the pipeline.

1. A MATCH THAT SHARES NOTHING BUT A GENERIC WORD SCORES HIGHEST.

       resolve_op("tyre replacement front")
       -> FILT-ENG-AIR  conf 0.81   "Engine air filter replacement"
          candidates: FILT-ENG-AIR 0.81, FILT-CABIN 0.74, TYR-MOUNT-BAL 0.69

   The only word shared is "replacement". "Tyre" appears nowhere in the winner,
   and the right answer - Mount & balance, per tyre - is third. token_set_ratio
   and WRatio both reward that one shared token heavily, and because the margin
   to second place is comfortable the ambiguity check does not fire either: it is
   returned at 0.81, well clear of the 0.62 acceptance threshold.

   Fix: a candidate must share at least one SPECIFIC word with the query. Words
   that appear across the whole catalogue - replacement, repair, inspection,
   service, front, rear, R&R - carry no information about which operation is
   meant, so a candidate whose only overlap is generic is demoted. This is the
   same principle as the existing front/rear demotion, one level up: there,
   naming the wrong end of the car is penalised; here, naming nothing in common.

2. THE AMBIGUITY GUARD HAS NEVER BLOCKED ANYTHING.

       resolve_op("lube oil and filter service")
       -> MAINT-15K  conf 0.70  "ambiguous between similar operations"
          candidates: MAINT-15K 0.80, MAINT-30K 0.80, FILT-CABIN 0.77

   A dead heat between a 15,000 and a 30,000 mile service. The code notices, says
   so in `reason`, and drops confidence to 0.70 - but Resolution.OP_THRESHOLD is
   0.62, so validate() accepts it anyway. The guard was dead code, and the
   difference between those two operations is real labour time on a customer's
   invoice.

   Fix: an ambiguous resolution lands BELOW the acceptance threshold, expressed in
   terms of that threshold so the two cannot drift apart again. It then becomes a
   clarifying question - "Which operation is this? Closest: MAINT-15K (15,000 mile
   service interval), MAINT-30K (30,000 mile service interval)" - which is the
   stance the rest of this pipeline already takes.

   Expect more updates to ask for clarification after this. That is the point.
   Guessing between two services silently is worse than asking once.
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
                 "      Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ================================================ 1. require a specific word in common
edit("app/pipeline/resolve.py",
     '''def _position(text: str) -> str | None:''',
     '''# Words that appear all over the catalogue. Sharing one of these with a candidate
# says nothing about WHICH operation is meant, so an overlap consisting only of
# these is no evidence at all.
_GENERIC = {
    "r", "rr", "and", "the", "a", "of", "per", "single", "both", "two", "four",
    "replacement", "replace", "repair", "remove", "refit", "renew", "fit",
    "fitted", "check", "checked", "inspection", "inspect", "measure", "service",
    "adjust", "adjustment", "clean", "set", "test", "tested", "assembly", "kit",
    "new", "done", "complete", "completed", "out", "full", "system",
    "front", "rear", "left", "right", "fr", "nsf", "osf", "nsr", "osr",
    "maintenance", "diagnostics", "diagnosis", "mile", "interval",
}


def _specific(text: str) -> set[str]:
    """The words in `text` that could identify one operation rather than another."""
    return {t for t in re.split(r"[^a-z0-9/]+", text.lower())
            if len(t) > 1 and t not in _GENERIC}


def _position(text: str) -> str | None:''',
     "resolve.py  _GENERIC and _specific",
     skip_if="_GENERIC = {")

edit("app/pipeline/resolve.py",
     '''    want = _position(text)
    if want:
        # Demote operations that name the opposite end of the car.
        for code in list(blended):
            got = _op_position(code)
            if got and got != want:
                blended[code] *= 0.55''',
     '''    want = _position(text)
    if want:
        # Demote operations that name the opposite end of the car.
        for code in list(blended):
            got = _op_position(code)
            if got and got != want:
                blended[code] *= 0.55
    # Demote a candidate whose only overlap with the query is catalogue-wide
    # vocabulary. "tyre replacement front" scored "Engine air filter replacement"
    # highest on the strength of the word "replacement" alone, and the fuzzy
    # scorers cannot tell that apart from a real match.
    q_specific = _specific(query)
    if q_specific:
        for code in list(blended):
            if not (q_specific & _specific(_OP_TEXTS.get(code, ""))):
                blended[code] *= 0.45''',
     "resolve.py  a match needs a specific word in common",
     skip_if="q_specific = _specific(query)")


# ================================================ 2. make the ambiguity guard guard
edit("app/pipeline/resolve.py",
     '''    if cands and cands[0][1] * 100 >= threshold:
        margin = cands[0][1] - (cands[1][1] if len(cands) > 1 else 0.0)
        if margin < 0.04:
            return Resolution(cands[0][0], 0.70, cands, "ambiguous between similar operations")''',
     '''    if cands and cands[0][1] * 100 >= threshold:
        margin = cands[0][1] - (cands[1][1] if len(cands) > 1 else 0.0)
        if margin < 0.04:
            # A tie in the fuzzy score is often an artefact. "front brake pads and
            # discs" scored BRK-FR-PAD 0.764 and BRK-PARK-ADJ 0.725 - a 0.039
            # margin - but the first shares brake, pads AND rotors with the query
            # while Parking brake adjustment shares only "brake". Break the tie on
            # how much of the query's distinctive vocabulary each one actually
            # covers, and only call it ambiguous when that is level too.
            near = [c for c in cands if cands[0][1] - c[1] < 0.04]
            def _overlap(code):
                return len(q_specific & _specific(_OP_TEXTS.get(code, "")))
            near.sort(key=lambda c: (-_overlap(c[0]), -c[1]))
            best = _overlap(near[0][0])
            rest = max((_overlap(c[0]) for c in near[1:]), default=-1)
            if best > rest:
                return Resolution(near[0][0], min(near[0][1], 0.99), cands,
                                  "lexical match, tie broken on shared vocabulary")
            # Genuinely level. Below the acceptance threshold on purpose, so
            # validate() asks instead of picking. Expressed against OP_THRESHOLD so
            # the two cannot drift apart again: at a flat 0.70 this branch was dead
            # code against a threshold of 0.62, and a dead heat between a 15,000 and
            # a 30,000 mile service was booked without anyone being asked.
            return Resolution(near[0][0], round(Resolution.OP_THRESHOLD - 0.05, 2),
                              cands, "ambiguous between similar operations")''',
     "resolve.py  an ambiguous match must not be accepted",
     skip_if="OP_THRESHOLD - 0.05")


# ================================================ verify
print("Quality pass 15:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/pipeline/resolve.py").read_text())
print("\nresolve.py parses cleanly.")

sys.path.insert(0, ".")
try:
    import importlib
    import app.pipeline.resolve as R
    importlib.reload(R)
except Exception as e:
    print(f"\nCould not import the resolver to test it ({type(e).__name__}: {e}).")
    print("Run with the project venv:  .venv/bin/python quality_pass15.py")
    raise SystemExit(1)

from app.data.catalog import OP_BY_CODE

bad = 0
print("\nresolution (threshold for acceptance is "
      f"{R.Resolution.OP_THRESHOLD}):")
CASES = [
    # (query, expected op code or None, must it be accepted?)
    ("tyre replacement front",          "TYR-MOUNT-BAL", None),
    ("two front tyres",                 "TYR-MOUNT-BAL", True),
    # the ones that already worked and must keep working
    ("front brake pads and rotors R&R", "BRK-FR-PAD",    True),
    ("rear brake inspection and measure", "BRK-RR-INSP", True),
    ("brake fluid flush and bleed",     "FLUID-BRK-FLUSH", True),
    ("system scan and code retrieval",  "DIAG-SCAN",     True),
    ("four wheel alignment",            "ALN-4WHEEL",    True),
    ("vehicle health check",            None,            None),
    # a dead heat must now ask rather than pick
    # the phrase the existing test suite uses - a tie on score, not on meaning
    ("front brake pads and discs",       "BRK-FR-PAD",   True),
    ("lube oil and filter service",     "LOF-SYN",       True),
    # nonsense must not resolve
    ("sorted the thing out at the front", None,          False),
]
for q, want, must_accept in CASES:
    r = R.resolve_op(q)
    ok = True
    if want is not None and r.value != want:
        ok = False
    if must_accept is True and not r.is_certain(R.Resolution.OP_THRESHOLD):
        ok = False
    if must_accept is False and r.is_certain(R.Resolution.OP_THRESHOLD):
        ok = False
    bad += (not ok)
    desc = OP_BY_CODE[r.value].description if r.value in OP_BY_CODE else "-"
    verdict = "accepted" if r.is_certain(R.Resolution.OP_THRESHOLD) else "ASKS"
    print(f"  {'ok     ' if ok else 'WRONG  '} {q!r}")
    print(f"           -> {r.value}  {r.confidence:.2f}  {verdict}  [{r.reason}]"
          f"  {desc}")
    if not ok:
        print(f"           expected {want}, accept={must_accept}")

print(f"\n{bad} check(s) unexpected" if bad
      else "\nAll pass-15 checks behaved as expected.")
print("\nNext:  .venv/bin/python -m pytest tests/ -q")
print("Then:  .venv/bin/python scripts/test_voice_update.py 3 --no-llm")
