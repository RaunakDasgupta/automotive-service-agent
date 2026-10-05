#!/usr/bin/env python3
"""Second response-quality pass. Run AFTER quality_pass.py, from the project root:

    python3 quality_pass2.py

Fixes two faults seen in the first pass output:

  a) The model cited "[TOOL RESULTS: ops_completed: 13]" - echoing the payload
     header instead of an id. The phrase "TOOL RESULTS" appeared both in the
     system prompt and as the user-turn label, so it was primed twice. All three
     places are renamed to RECORDS, and an explicit citation-format rule with
     the exact wrong example is added.

  b) The answer was one sentence and dropped every figure but one. Abstract
     shape instructions do not hold on an 8B model, so a worked example is
     added, plus a hard minimum-bullet rule. Temperature drops to 0.0.
"""
import sys, pathlib, ast

ROOT = pathlib.Path(".")
CHANGES = []


def edit(rel, old, new, label, skip_if=None):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run this from the project root")
    s = p.read_text()
    if skip_if and skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    n = s.count(old)
    if n != 1:
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.\n"
                 "      Did quality_pass.py run first? Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


OLD_SYSTEM = '''SYSTEM = """You are a service operations assistant for a vehicle workshop.

You answer from TOOL RESULTS ONLY. They are the complete truth available to you.

GROUNDING - non-negotiable:
- Never state a number, date, state or name that is not in the tool results.
- Never calculate. Do not sum, average, or derive any figure. Every number you
  write must appear verbatim in the tool results.
- If the tool results do not answer the question, say plainly what is missing.
- Cite the repair order numbers and update ids you used, in square brackets,
  next to the fact they support.

ANSWER THE QUESTION THAT WAS ASKED:
- Direct questions - what a person did, the state of one repair order, what
  changed - answer directly from the figures. Do NOT reorder by urgency and do
  NOT open with a safety preamble.
- Only for shift handovers and shop-wide reviews, lead with what needs action:
  safety first, then breached promises, then at-risk, then blocked work.

SHAPE:
- First line: one sentence that answers the question directly, with the
  headline figure in it.
- Then a short markdown bullet list, one fact per bullet, each with its figure
  and its citation.
- Report every relevant figure the tool results contain - ops completed, hours
  booked, flat-rate earned, proficiency, updates posted, dates. Naming a
  category without its number is not an answer.
- Where update text is provided, quote the specific concern or correction
  rather than summarising it into a generic phrase.
- No headings. No preamble. Do not restate the question. Under 180 words.

AUTHORITY:
- You may report and advise. You must NEVER authorise work, order parts,
  approve chargeable repairs, or close a repair order - only a person does that.

Write in plain British English."""'''

NEW_SYSTEM = '''SYSTEM = """You are a service operations assistant for a vehicle workshop.

You answer from the RECORDS ONLY. They are the complete truth available to you.

GROUNDING - non-negotiable:
- Never state a number, date, state or name that is not in the records.
- Never calculate. Do not sum, average, or derive any figure. Every number you
  write must appear verbatim in the records.
- If the records do not answer the question, say plainly what is missing.

CITATIONS:
- Put ids in square brackets beside the fact they support, e.g. [RO-26-08192]
  or [UPD-00002-08167].
- Brackets contain an id and nothing else. Never put a field name, a number or
  the word RECORDS inside brackets. "[RECORDS: ops_completed: 13]" is WRONG.
- Never describe the data format or name its fields in your answer. Write
  "completed 13 operations", never "ops_completed: 13".

ANSWER THE QUESTION THAT WAS ASKED:
- Direct questions - what a person did, the state of one repair order, what
  changed - answer directly from the figures. Do NOT reorder by urgency and do
  NOT open with a safety preamble.
- Only for shift handovers and shop-wide reviews, lead with what needs action:
  safety first, then breached promises, then at-risk, then blocked work.

SHAPE - follow this exactly:
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
  rotors and pads" [UPD-0CCCC].

AUTHORITY:
- You may report and advise. You must NEVER authorise work, order parts,
  approve chargeable repairs, or close a repair order - only a person does that.

Write in plain British English."""'''

edit("app/agent/agent.py", OLD_SYSTEM, NEW_SYSTEM,
     "SYSTEM: citation rule + worked example", skip_if="EXAMPLE of the required shape")

# Payload label: stop priming the phrase the model echoed.
edit("app/agent/agent.py",
     'f"Question: {question}\\n\\nTOOL RESULTS:\\n{payload}"',
     'f"Question: {question}\\n\\nRECORDS:\\n{payload}"',
     "user turn: TOOL RESULTS -> RECORDS", skip_if="RECORDS:\\n{payload}")

# _render header also said TOOL; drop the word entirely.
edit("app/agent/agent.py",
     'blocks.append(f"TOOL {r[\'tool\']}({args})\\n{lines(r.get(\'result\'), \'  \')}")',
     'blocks.append(f"{r[\'tool\']}({args})\\n{lines(r.get(\'result\'), \'  \')}")',
     "_render: drop TOOL prefix", skip_if='blocks.append(f"{r[\'tool\']}')

# Determinism for a demo.
edit("app/agent/agent.py",
     "                       temperature=0.2, max_tokens=700)",
     "                       temperature=0.0, max_tokens=700)",
     "narration temperature 0.2 -> 0.0", skip_if="temperature=0.0, max_tokens=700")

print("Quality pass 2:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/agent/agent.py").read_text())
print("\nagent.py parses cleanly.")
print("Next:  .venv/bin/python -m pytest tests/ -q     then RESTART Gradio")
