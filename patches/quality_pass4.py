#!/usr/bin/env python3
"""Fourth pass: stop the model copying figures out of the prompt's own example.

Run AFTER quality_pass3.py, from the project root:

    python3 quality_pass4.py

WHAT WENT WRONG
The worked example added in pass 2 contained concrete figures (3.5, 3.8, 1.09,
2.4, 1.1, 22.8, 23.0). The ids in it were deliberately fake, but the numbers
were not - and the model copied 2.4 into a real answer, where check_grounding
correctly flagged it as a figure absent from the records.

THE FIX
 1. The example now contains NO digits at all - only placeholders (H.H, N, P.PP)
    that cannot satisfy the decimal or multi-digit regexes in check_grounding,
    so a copied placeholder can never trip the rail.
 2. The prompt now tells the model that a Figures list is appended
    automatically, so it does not need to enumerate numbers. Fewer digits
    emitted means fewer chances to emit a wrong one.
 3. An explicit instruction to omit any figure it is not certain about.
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
                 "      Run passes 1-3 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


OLD_BLOCK = '''SHAPE - follow this exactly:
- One opening sentence that answers the question and carries the headline figure.
- Then a markdown bullet list, one fact per bullet.
- Report EVERY relevant figure the records hold: operations completed, repair
  orders touched, hours booked, flat-rate earned, proficiency, updates posted,
  categories worked, dates.
- If the records hold four or more figures you MUST write four or more bullets.
  A single-sentence answer is incomplete and unacceptable.
- Where update text is given, quote the specific concern or correction in its
  own bullet. Do not flatten it into a generic phrase like "focusing on
  diagnostics".
- No headings. No preamble. Do not restate the question. Under 200 words.

EXAMPLE of the required shape. Its figures and ids are illustrative only -
never reuse them, always use the figures in the records you are given:

EMP0XX booked 3.5 hours across 2 repair orders this week, earning 3.8 flat-rate
hours - a proficiency of 1.09.
- Completed 2 operations: front rotors and pads on [RO-26-0AAAA] at 2.4 hours,
  and a DTC diagnosis on [RO-26-0BBBB] at 1.1 hours.
- Posted 4 updates over the 7-day window.
- Work split across brakes and diagnostics, 1 operation each.
- Most recent note: "LF rotor 22.8mm, below 23.0mm minimum - R&R both front
  rotors and pads" [UPD-0CCCC].'''

NEW_BLOCK = '''DIGITS - read this twice:
- Every digit you write must be copied verbatim from the records.
- If you are not certain a figure is in the records, LEAVE IT OUT. An answer
  missing a number is fine. An invented number is a failure.
- A "Figures" list is appended to your answer automatically after you finish,
  listing every figure from the records. You therefore do NOT need to enumerate
  numbers. Give at most the one or two headline figures, and keep your bullets
  qualitative.

SHAPE - follow this exactly:
- One opening sentence that answers the question directly.
- Then two to four markdown bullets describing the work in words: what kind of
  jobs, on which repair orders, and what the most recent note actually said.
- Where update text is given, quote the specific concern or correction. Do not
  flatten it into a generic phrase like "focusing on diagnostics".
- Cite ids in brackets beside the fact they support.
- No headings. No preamble. Do not restate the question. Keep it short.

EXAMPLE - this is a SHAPE ONLY. It deliberately contains no digits. The letters
H.H, N, F.F and P.PP are placeholders: replace each with the real figure from
the records, or omit it. Never copy a number out of this example.

EMP0XX booked H.H hours across N repair orders this week, a proficiency of P.PP.
- Mostly brake work, including front rotors and pads on [RO-26-0AAAA].
- One diagnostic job, a DTC investigation on [RO-26-0BBBB].
- Most recent note: "LF rotor below minimum thickness - R&R both front rotors
  and pads" [UPD-0CCCC].'''

edit("app/agent/agent.py", OLD_BLOCK, NEW_BLOCK,
     "SYSTEM: digit-free example + omit-if-unsure rule",
     skip_if="DIGITS - read this twice")

# The pass-2 citation rules used "13" as their counter-example. That digit is
# just as copyable as the ones in the worked example, so it goes too.
edit("app/agent/agent.py",
     '''- Brackets contain an id and nothing else. Never put a field name, a number or
  the word RECORDS inside brackets. "[RECORDS: ops_completed: 13]" is WRONG.
- Never describe the data format or name its fields in your answer. Write
  "completed 13 operations", never "ops_completed: 13".''',
     '''- Brackets contain an id and nothing else. Never put a field name, a number or
  the word RECORDS inside brackets. "[RECORDS: ops_completed: N]" is WRONG.
- Never describe the data format or name its fields in your answer. Write
  "completed N operations", never "ops_completed: N".''',
     "SYSTEM: digits removed from citation rules",
     skip_if='ops_completed: N]" is WRONG')

print("Quality pass 4:")
for c in CHANGES:
    print(c)

src = (ROOT / "app/agent/agent.py").read_text()
ast.parse(src)
print("\nagent.py parses cleanly.")

# Prove the prompt can no longer leak a figure: run the real check_grounding
# regexes over the SYSTEM prompt itself.
import re
start = src.index('SYSTEM = """') + len('SYSTEM = """')
system = src[start:src.index('"""', start)]
decimals = set(re.findall(r"(?<![\w.-])\d+\.\d+(?![\w.-])", system))
bigints = {n for n in re.findall(r"(?<![\w.-])\d{2,}(?![\w.\-\d])", system)
           if n not in ("24", "26")}
print(f"\nGroundable digits left in SYSTEM: decimals={sorted(decimals)} "
      f"multi-digit={sorted(bigints)}")
if decimals or bigints:
    print("WARNING: a figure in the prompt could still be copied and flagged.")
else:
    print("OK - no copyable figure remains in the prompt.")
print("\nNext:  .venv/bin/python -m pytest tests/ -q     then RESTART Gradio")
