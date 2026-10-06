#!/usr/bin/env python3
"""pass 60 - a negative result, written down so it is not repeated.

    .venv/bin/python patches/quality_pass60.py            apply
    .venv/bin/python patches/quality_pass60.py --check    verify, change nothing

No code changes. Five attempts to shorten the narration prompt and reduce
generation length were built and measured, and every one was worse, so the
agent is exactly as it was. What this pass adds is the record - ENGINEERING.md
section 50 with the numbers, and a paragraph in AGENT_LOOP.md telling the
sandbox agent not to spend its afternoon rediscovering it.

The result in one line: a 9.4% shorter prompt produced a 27% LONGER answer and
a 20% slower turn, because the verbosity being removed from SYSTEM_SEARCH was
what suppressed note-by-note listing. Changing only the sentence budget - "two
to four" to "two or three" - took one answer from 48 words to 83. Instructing
this 8B model to be shorter makes it longer.

Two gaps in the measure fell out of it, and they are worth more than the failed
optimisation:

  * all 19 correctness metrics stayed FLAT on a variant whose answer lists four
    notes one by one and attributes a Kia's symptom to a Passat. Only the
    latency gate from pass 59 failed the run, four hours after being written;
  * `free_of_meta` scores 100% on the committed baseline's answer that opens
    "Notes indicate air conditioning concerns on four vehicles", which is the
    phrasing SYSTEM_SEARCH explicitly bans. Measured on the gated baseline, so
    it is a live gap rather than a property of a variant.

ANCHORS RATHER THAN DIGESTS

Pass 59 pinned whole files by sha256, which is a stronger check and composes
worse: any later edit to one of those files makes pass 59 refuse. That is safe -
it fails loudly instead of overwriting - but it means passes must be run in
order from a clean checkout, which the instructions say anyway. This pass uses
anchors so that it does not add the same constraint on top.
"""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = "--check" in sys.argv

ENG_ANCHOR = '    narration grounded        100.0%   (2/2, both reached the model)\n'
ENG_ADDED = '    narration grounded        100.0%   (2/2, both reached the model)\n\n## 50. Five ways to shorten the narration prompt, all worse\n\nAsked to optimise the prompt and reduce generation length, with section 49\'s\nprofile pointing at generation as the largest stage. Five variants were built\nand measured. **Every one of them was worse, and the code is unchanged.** This\nsection exists so the next person - or the sandbox agent - does not spend the\nafternoon rediscovering it.\n\nFirst, where the tokens actually were, measured with the model\'s own tokenizer\nrather than estimated:\n\n    system prompt         511   46%\n    payload + question    598   54%\n    chat template          37\n    total                1146\n\nSo the instructions were nearly half the prompt, which is what made compressing\nthem look obvious.\n\n### The variants\n\n    A  committed baseline      1146 tok   Q1 4 cites / 48 words   Q2 1 cite / 70 words\n    B  payload: drop score,\n       query, count            1084 tok   Q1 0 CITES / 23 words\n    C  system prompt\n       compressed to 465       1100 tok   Q1 cites bunched at the end, and it\n                                          calls UPD-00001-08022 a Passat when\n                                          that note is a Kia Sportage\n    D  B and C together        1038 tok   gate REJECTED - see below\n    E  payload: drop score\n       only                    1106 tok   Q1 0 CITES / 68 words\n                               1008 tok   Q2 4 cites / 63 words\n    F  budget line only,\n       "two or three ... four\n       at most"                1146 tok   Q1 4 cites / 83 words, with\n                                          "it is not the whole story as ..."\n                               1047 tok   Q2 opens "There is one note about"\n\n### What D measured, and what caught it\n\n    llm_prompt_tokens      1146 -> 1038     -9.4%   the intended win\n    llm_completion_tokens    99 ->  126    +27.3%\n    llm_model_ms           1453 -> 1838    +26.5%\n    llm_best_ms            1800 -> 2162    +20.1%\n    total_best_ms          1995 -> 2358    +18.2%\n\n    all 19 correctness metrics        FLAT\n    cross-check                       agree\n    gate                              RC=1, four latency regressions\n\n**A 9.4% shorter prompt produced a 27% longer answer and a 20% slower one.**\nThe direction is the finding. The verbosity being removed was load-bearing: the\nrestatement in SYSTEM_SEARCH is what suppresses note-by-note listing, and\nwithout it the model enumerates each passage with a quote - which is both longer\nand the exact thing the prompt\'s remaining text still forbids.\n\nF is the sharpest version of the same lesson. It changes *one line* - the\nsentence budget, from "two to four, six at most" to "two or three, four at\nmost" - and Q1 goes from 48 words to 83, acquiring meta-commentary about what\nthe notes do and do not cover. Instructing this 8B model to be shorter made it\nlonger. Generation length here is a property of the model\'s behaviour on a\ngiven prompt, not a dial the instruction turns.\n\n### Two gaps in the measure, found by accident\n\nWorth more than the failed optimisation.\n\n**The correctness suite did not notice.** All 19 metrics were flat on a variant\nwhose answer lists four notes one by one and attributes a Kia\'s symptom to a\nPassat. `relevance`, `answers_the_form`, `entity_coverage` and `free_of_meta`\nall scored 100% on it. Only the latency gate from section 49 failed the run -\nwhich is the first time that gate has earned itself, four hours after being\nwritten.\n\n**`free_of_meta` passes "Notes indicate".** The committed baseline\'s answer to\nthe burning-smell question opens `Notes indicate air conditioning concerns on\nfour vehicles`, and later `[UPD-00001-08061] provides the most detailed\ninformation, stating that ...`. SYSTEM_SEARCH bans exactly this - "Do not write\n\'the updates\', \'the notes\', \'the passages\'" - and the benchmark scores it 100%.\nThis is measured on the gated baseline, not on a variant, so it is a live gap.\n\nA zero-citation answer also appeared twice, in B and E. Whether the suite would\nfail one was NOT measured, because the variant that reached the gate had four\ncitations. That is worth closing before it matters.\n\n### What is left\n\nNot the prompt. Generation is 1838 ms of a 2162 ms answer at 69 tok/s, and the\ninstruction does not shorten it. The remaining options are a different model, or\naccepting the latency on the grounds that streaming already hides it from the\nreader - five of six questions never reach a model at all, so this is one path\nin six.\n'
MD_ANCHOR = '### The measured profile, so you optimise the right thing'
MD_ADDED = '### Do not try to shorten the narration prompt\n\nFive variants were measured and every one was worse; section 50 of\n`ENGINEERING.md` has the numbers. The short version: the system prompt is 46% of\nthe narration prompt and compressing it made the answer 27% LONGER and the turn\n20% slower, because the restatement being removed is what stops the model\nlisting each note with a quote. Changing only the sentence budget - one line,\n"two to four" to "two or three" - took one answer from 48 words to 83.\n\nInstructing this 8B model to be shorter makes it longer. If you have a new idea\nhere, measure it on both search questions before you believe it, and expect the\nlatency gate rather than the correctness suite to be the thing that fails you.\n\n'

# The "already applied" marker must be text that exists ONLY afterwards. A slice
# of the replacement is not: ENG_ADDED begins with the anchor it replaces, so a
# derived marker matched before the edit and the patch reported success without
# doing anything.
EDITS = [
    ("ENGINEERING.md", ENG_ANCHOR, ENG_ADDED,
     "## 50. Five ways to shorten the narration prompt"),
    ("AGENT_LOOP.md", MD_ANCHOR, MD_ADDED + MD_ANCHOR,
     "### Do not try to shorten the narration prompt"),
]

done = 0
for rel, old, new, marker in EDITS:
    p = ROOT / rel
    if not p.exists():
        print(f"FAIL: {rel} is missing. Run passes 1-59 first.")
        sys.exit(1)
    t = p.read_text()
    if marker in t:
        print(f"  already   {rel}")
        done += 1
        continue
    if t.count(old) != 1:
        print(f"FAIL: {rel}  anchor found {t.count(old)} times, expected 1.")
        print("      Run passes 1-59 first. Stopping without changes.")
        sys.exit(1)
    if not CHECK:
        p.write_text(t.replace(old, new, 1))
    print(f"  {'would patch' if CHECK else 'patched  '} {rel}")

if done == len(EDITS):
    print("  nothing to do - pass 60 is already applied")
else:
    print("\n  no code changed, so no re-measurement is needed.")
