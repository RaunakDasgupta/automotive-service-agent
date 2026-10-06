#!/usr/bin/env python3
"""pass 61 - the two gaps pass 60 found, closed.

    .venv/bin/python patches/quality_pass61.py            apply
    .venv/bin/python patches/quality_pass61.py --check    verify, change nothing

Pass 60 failed to optimise the prompt and found two holes in the measure on the
way past. Both are in `evals/asoia_byob.py`; no application code changes.

GAP 1 - free_of_meta could not see a violation in front of it

`SYSTEM_SEARCH` bans five nouns as referents. The patterns enforcing it were
each written against one shipped phrasing, so they required BOTH an article and
one of two verbs:

    \bthe updates (provided|mention|also)\b
    \bthe notes (provided|mention)\b

`Notes indicate air conditioning concerns on four vehicles` is an article and a
verb away from both, so the gated baseline scored free_of_meta 100% on an answer
that opens by talking about the records. The referent is now matched generally:
the five nouns with or without an article, any reporting verb, the bare
`the <noun>` form, `according to the notes`, and the existential
`There are four notes about ...`.

That last one is not hypothetical. It is what the model produced the moment the
article-and-verb forms were closed off, during an attempt to fix this from the
prompt side. Closing one phrasing and not its neighbour is how this check came
to report 100% in the first place.

QUOTED TEXT IS STRIPPED BEFORE MATCHING

`SYSTEM_SEARCH` also tells the model to quote the technician's own words, and
those words contain the banned nouns - `Notes on the RO.` appears verbatim in
the corpus. Matching inside a quotation would fail an answer for obeying a
different rule. That is the real reason the original patterns were so narrow,
and the fix is to know what is quoted rather than to match less.

MEASURED BEFORE ADOPTION, TWICE

The first version of the count pattern flagged `12 updates`, `34 updates`,
`143 updates` - seven Python-composed answers reporting updates posted as a
figure. A count of records is meta only when it counts what MATCHED the
question, so the count now has to be followed by a referring word. After that
narrowing: 1 of 37 answers flagged, which is the one real violation, with the
quoted-text and legitimate-verb cases both clean.

GAP 2 - traceability passed an answer with no citations at all

`traceability` asks whether the citations RESOLVE, so an answer carrying none
scored 1.0 vacuously: an empty list has no unresolved member. Two variants in
pass 60 produced exactly that - a confident narration of four passages with no
citation anywhere - and this benchmark would have called them perfectly
traceable.

`cited` is the floor. An answer built from a payload must point at it. A trivial
payload is exempt, because there is then nothing to cite and demanding one would
fail an honest "nothing on record" answer. Measured at adoption: 0 of 37 answers
carry no citation, so it holds today, and the point of a floor is that it keeps
holding.

WHAT THIS COSTS, HONESTLY

    free_of_meta   100.0%  ->  97.3%    36 of 37
    relevance      100.0%  ->  99.1%    it is the mean of three
    cited             new  -> 100.0%
    traceability   100.0%  -> 100.0%
    everything else                     flat, latency included

free_of_meta did not regress; it became honest. The 100% was an artefact of a
check that could not see the violation, and 97.3% is the first real measurement
of it. The baseline was retaken at the lower number rather than the metric being
quietly left where it was.

THE UNDERLYING DEFECT IS OPEN

The answer to `any notes about a burning smell` still opens by referring to the
records. Five fixes were measured and all failed: broadening the prompt rule
produced `There are four notes about a burning smell` with four notes then
listed one by one; and three payload headers - `RECORDS:`, `---`,
`WHAT THE TECHNICIANS WROTE:` - gave `Notes indicate`, `There is one note
about`, and `The notes on the repair order (RO) mention`. The question's own
vocabulary drives it, and pass 60 already records that prompt edits here
backfire. So the measure is correct and the defect is recorded rather than
hidden, which is the right order to leave them in.
"""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = "--check" in sys.argv

EDITS = [
    ('evals/asoia_byob.py', [
        ('    cites = list(inp.metadata.get("citations") or [])\n    unresolved = [c for c in cites if c not in blob]\n    return {"traceability": 1.0 if not unresolved else 0.0,\n            "citations": float(len(cites)),\n            "unresolved_citations": float(len(unresolved))}\n',
         '    cites = list(inp.metadata.get("citations") or [])\n    unresolved = [c for c in cites if c not in blob]\n    # `traceability` asks whether the citations RESOLVE, so an answer carrying\n    # none scored 1.0 - vacuously, because an empty list has no unresolved\n    # member. Two variants in pass 60 produced exactly that: a confident\n    # narration of four passages with no citation at all, which this benchmark\n    # would have called perfectly traceable.\n    #\n    # `cited` is the floor. An answer built from a payload must point at it.\n    # A trivial payload is exempt because there is then nothing to cite and\n    # demanding a citation would fail an honest "nothing on record" answer.\n    # Measured at adoption: 0 of 37 answers carry no citation, so this holds\n    # today and the point of a floor is that it keeps holding.\n    has_payload = len(blob.strip()) > 2\n    return {"traceability": 1.0 if not unresolved else 0.0,\n            "cited": 1.0 if (cites or not has_payload) else 0.0,\n            "citations": float(len(cites)),\n            "unresolved_citations": float(len(unresolved))}\n'),
        ('# Relevance: is this an answer to THIS question\n# ===========================================================================\n_META = re.compile(\n    r"\\bthe search returned\\b|\\bas per the guidelines?\\b|\\bthe passages?\\b"\n    r"|\\bthe updates (provided|mention|also)\\b|\\bthe notes (provided|mention)\\b"\n    r"|\\bI\'?m sorry\\b|\\bI cannot\\b|\\bI am unable\\b|\\bas an AI\\b"\n    r"|\\brepeat_call\\b|\\bper your instruction", re.I)\n_RO = re.compile(r"\\bRO-\\d{2}-\\d{4,5}\\b", re.I)\n_STAFF = re.compile(r"\\b(EMP|ADV|FOR|PRT|MGR)\\d{3}\\b", re.I)\n',
         '# Relevance: is this an answer to THIS question\n# ===========================================================================\n# SYSTEM_SEARCH bans five nouns as referents - "the updates", "the notes",\n# "the passages", "the records", "the reports". The patterns that enforced it\n# were each written against one shipped phrasing, so they required BOTH the\n# article and one of two verbs, and `Notes indicate air conditioning concerns\n# on four vehicles` walked straight through while free_of_meta scored 100%.\n# Pass 60 found that on the gated baseline, not on a variant.\n#\n# So the referent is matched generally instead: the five nouns with or without\n# an article, followed by any reporting verb, plus the bare "the <noun>" form\n# the prompt names, plus "according to the notes". Measured against all 37\n# answers before being adopted - it catches exactly one, the burning-smell\n# answer, and nothing else. A check that fires on an answer it should not is\n# worse than the gap it closes.\n#\n# `posted` is deliberately absent from the verbs: the figures block appended to\n# narrated answers carries the label "Updates posted", which is a count and not\n# a reference to the records.\n_META_NOUNS = r"(?:updates?|notes?|passages?|records?|reports?)"\n_META_VERBS = (r"(?:indicate|show|mention|provide|say|state|suggest|confirm|"\n               r"describe|cover|reveal|detail|reference|list|contain|include|"\n               r"highlight|point)")\n_META = re.compile(\n    r"\\bthe search returned\\b|\\bas per the guidelines?\\b"\n    r"|\\bI\'?m sorry\\b|\\bI cannot\\b|\\bI am unable\\b|\\bas an AI\\b"\n    r"|\\brepeat_call\\b|\\bper your instruction"\n    rf"|\\b(?:the|these|those)?\\s*{_META_NOUNS}\\s+{_META_VERBS}s?\\b"\n    rf"|\\bthe\\s+{_META_NOUNS}\\b"\n    rf"|\\b(?:according to|based on|from)\\s+(?:the\\s+)?{_META_NOUNS}\\b"\n    # The existential form, which is what the model reached for the moment the\n    # article-and-verb forms were closed off: "There are four notes about a\n    # burning smell". Closing one phrasing and not its neighbour is how this\n    # check came to report 100% on a violation in the first place.\n    rf"|\\bthere (?:are|is|were|was)\\s+(?:\\w+\\s+){{0,2}}{_META_NOUNS}\\b"\n    # A COUNT of records is meta only when it counts what matched the question.\n    # "12 updates posted" is a figure seven Python-composed answers state as\n    # fact, so the count must be followed by a referring word to flag. The\n    # first version of this pattern lacked that and failed all seven.\n    rf"|\\b(?:\\d+|one|two|three|four|five|six|several|some|many|multiple|a few)"\n    rf"\\s+{_META_NOUNS}\\s+(?:about|mention|cover|match|refer|relating|"\n    rf"regarding|describing|concerning)", re.I)\n\n# Quoted spans are stripped before matching. SYSTEM_SEARCH tells the model to\n# quote the technician\'s own words, and those words contain the banned nouns -\n# "Notes on the RO." appears verbatim in the corpus. Matching inside a quotation\n# would fail an answer for obeying a different rule, which is why the original\n# patterns were narrow enough to let a real violation through: the fix is to\n# know what is quoted, not to match less.\n_QUOTED = re.compile(r\'"[^"]*"|\\u201c[^\\u201d]*\\u201d\')\n\n\ndef _meta_free(text: str) -> float:\n    return 0.0 if _META.search(_QUOTED.sub(" ", text)) else 1.0\n_RO = re.compile(r"\\bRO-\\d{2}-\\d{4,5}\\b", re.I)\n_STAFF = re.compile(r"\\b(EMP|ADV|FOR|PRT|MGR)\\d{3}\\b", re.I)\n'),
        ('    hit = sum(1 for e in ents if _covers(e, up, low))\n    coverage = (hit / len(ents)) if ents else 1.0\n    meta = 0.0 if _META.search(text) else 1.0\n    return {"relevance": round((form + coverage + meta) / 3, 4),\n            "answers_the_form": form,\n',
         '    hit = sum(1 for e in ents if _covers(e, up, low))\n    coverage = (hit / len(ents)) if ents else 1.0\n    meta = _meta_free(text)\n    return {"relevance": round((form + coverage + meta) / 3, 4),\n            "answers_the_form": form,\n'),
    ]),
]

done = 0
for rel, hunks in EDITS:
    p = ROOT / rel
    if not p.exists():
        print(f"FAIL: {rel} is missing. Run passes 1-60 first.")
        sys.exit(1)
    t = p.read_text()
    if all(new in t for _, new in hunks):
        print(f"  already   {rel}")
        done += 1
        continue
    for old, new in hunks:
        if t.count(old) != 1:
            print(f"FAIL: {rel}  anchor found {t.count(old)} times, expected 1.")
            print("      Run passes 1-60 first. Stopping without changes.")
            sys.exit(1)
    if not CHECK:
        for old, new in hunks:
            t = t.replace(old, new, 1)
        p.write_text(t)
    print(f"  {'would patch' if CHECK else 'patched  '} {rel}  "
          f"({len(hunks)} hunk(s))")

if done == len(EDITS):
    print("  nothing to do - pass 61 is already applied")
else:
    print("\n  the measure changed, so the lock and the baseline must be retaken:")
    print("    .venv/bin/python scripts/agent_loop.py relock "
          "--i-am-changing-the-measure")
    print("    .venv/bin/python scripts/agent_loop.py gate")
    print("    .venv/bin/python scripts/agent_loop.py accept")
    print("\n  expect free_of_meta 97.3% and relevance 99.1%: that is the")
    print("  honest value, not a regression.")
