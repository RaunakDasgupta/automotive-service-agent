# Plan: a fuller problem statement for the demo video's opening

Status: **proposal, nothing built.** "Points 3-5" is read as beats P3, P4 and P5 of the current opening (answers are chased, hours are lost, critical issues stay buried).

## 1. What a problem statement is (and is not)

A problem statement says **what is wrong, for whom, why, and at what cost, without mentioning the solution.** It earns the right to propose one. Five parts:

| part | question it answers | rule |
|---|---|---|
| Who | whose work is affected | name roles, not "users" |
| What | what goes wrong, observably | something you could film |
| Why | the root cause | one cause, upstream of the symptoms |
| Cost | what it costs | delay, rework, safety, hours; qualitative unless a number is sourced |
| Gap | why current ways fail | the thing people do today and why it does not hold |

Not a problem statement: a feature list, a missing tool ("they lack AI"), or a number nobody can source. The demo has no measured "before" figure, so the video **claims no statistics about the problem**; its own figures (12 of 32 flagged, 0.1 s, 905 / 905) describe the solution only.

## 2. The comprehensive statement, built from P1-P5

The current beats are three symptoms. A statement needs the cause that links them.

- **Cause (P1-P2):** knowledge is created in the field and **lost at handover**.
- **What (P3):** so answers sit in notes, calls and separate systems; managers must **hunt** for each one.
- **Cost, time (P4):** every hunt is hours spent asking, searching and re-typing, **not doing the work**.
- **Cost, risk (P5):** the issues that matter most (safety, out of spec, blocked) **stay buried** until they become delay, rework or harm.
- **Gap:** notes, calls and screens each hold a piece; nothing keeps one current, checkable record that a manager can ask.

One-sentence form: *In service operations, the detail that matters is lost at handover, so answers are scattered, hours go to chasing them, and the riskiest issues stay buried until they cause delay, rework or harm.*

The chain is the point: **lost detail → scattered answers → lost hours → buried risk → delay, rework, harm.** The video should show it as a chain, not as three unrelated complaints.

## 3. Infographics

All in the existing style (dark grid, white and green, red for the problem), built as scenes in `problem.html` / `intro.html`, no new dependencies.

| id | infographic | shows | beat |
|---|---|---|---|
| A | **Where an answer lives** | the question "Is it safe to sign off?" at the centre, six sources around it (notes, calls, chat, spreadsheet, work-order system, someone's memory); lines are drawn to each one in turn and a hop counter ticks up | P3 |
| B | **A shift, broken up** | one shift as a timeline: blocks of real work (green) cut up by chase blocks (red: asking, searching, re-typing). No numbers, only the shape | P4 |
| C | **Buried** | a pile of notes; the one stamped SAFETY is at the bottom; a ladder on the right climbs *delay → rework → safety incident* as the pile is searched | P5 |
| D | **The chain** | the five-link cascade above, lighting up link by link, each link carrying its icon from A-C | new P6 |
| E | **Sector map** | see section 4 | new P7 |

## 4. The solution as one of several sectors

Replace the current "example use case" tile row with a **sector map**: a ring of service sectors around the problem chain, all lit as "same pattern", then one lifts and glows.

- Sectors shown: **automotive service (the demo)**, field service and equipment maintenance, facilities management, aviation maintenance, healthcare equipment, utilities and energy field work. Only automotive is highlighted; the rest are dimmed and unlabelled beyond their name.
- Line under it: *Shown in automotive. Same pattern wherever work is handed over and safety matters.*
- **What carries over and what does not**, grounded in the code, so the claim is honest: the event log, the fold into current state, the grounded answers and the checks are generic (`app/state/engine.py`, `app/agent/agent.py`). What is per sector is the **catalogue and rules**: operation codes, specification limits, the lifecycle table (`app/state/transitions.py`). The video says automotive is the only one demonstrated; it does not say the others have been built.

## 5. Narration (proposal, about 30 s for the opening)

| id | line |
|---|---|
| P1 | Vehicles, equipment, facilities: all of it runs on handovers. |
| P2 | At every shift change, the detail that matters is lost. |
| P3 | So answers end up scattered across notes, calls and systems, and managers chase them by hand. |
| P4 | Every chase costs hours that never reach the work. |
| P5 | Meanwhile the critical issues stay buried until they cause delay, rework or harm. |
| P6 | One break at handover, three costs: scattered answers, lost time, buried risk. |
| P7 | The pattern runs across service sectors. We show it in one: automotive. |

Then the Deloitte and NVIDIA card and the solution, as now.

## 6. Length, and the decision it forces

The opening is 22 s today and the video 2:34.5. This version is about 31 s, so **about 2:43** unless something else gives. Options:

1. **Trim the middle by about 8 s** to stay under 2:35: merge B3 and B4 (about 2 s), fold the business-value section into the summary (about 8 s, since the summary repeats its figures). Recommended.
2. Accept 2:43.
3. Keep the video as is and ship the problem and sector infographics as a separate 45-second opener.

## 7. Work, in order

1. Narration and beat table (`docs/DEMO_VIDEO.md`): P3-P5 reworded, P6 and P7 added.
2. Infographics A-E as scenes; cascade and sector map are the two that need new layout.
3. Scene plans and the `PIECES` list; edit sheet, README, subtitles regenerated.
4. Rebuild, sample frames of each new scene, check length against the choice in section 6.

Risk: the sector list is positioning, not something the repo demonstrates. If a client asks "does it work for aviation", the honest answer is "the pattern does, the catalogue and rules are rebuilt". Worth your sign-off on which sectors to name.
