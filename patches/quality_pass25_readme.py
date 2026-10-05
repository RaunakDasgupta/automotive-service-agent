#!/usr/bin/env python3
"""Pass 25, the README half - the part that could not use an exact anchor.

    .venv/bin/python quality_pass25_readme.py          # apply
    .venv/bin/python quality_pass25_readme.py --show   # just print what it sees

WHY THIS IS A SEPARATE FILE

quality_pass25.py stopped on its seventeenth edit:

    FAIL: README.md  the launch no longer exports a date:
          anchor found 0 times in README.md, expected 1.
          Run passes 1-24 first. Stopping without changes.

That last line is wrong, and it is wrong in every pass in this project, because
`edit()` writes each change as it goes: the sixteen CODE edits had already been
applied and only the three README edits had not. Nothing was half-written - the
code is complete and correct - but the message says the opposite of the truth at
the exact moment someone most needs to know where they stand.

The anchor missed because a README is prose. It gets edited by hand, reflowed,
and copied between machines, and a four-line exact match is a bad way to find a
paragraph. So this matches on structure - a line that STARTS WITH something, a
row in a table - rather than on four lines of exact text, and where it cannot
find its target it says so and moves on instead of taking the file down with it.

It is idempotent, it never fails the run over documentation, and --show prints
the three regions so a mismatch can be read rather than guessed at.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

README = Path("README.md")

# `export ASOIA_NOW=`, `export  ASOIA_NOW =`, with or without leading indent. The
# first version of this matched one exact spelling, missed a two-space variant,
# and then its own verification - which used the same narrow pattern - reported
# "no exported date is left" about a file that still had one. The detector and
# the check have to be the same expression, and it has to be a forgiving one.
EXPORT_RE = re.compile(r"^\s*export\s+ASOIA_NOW\s*=", re.M)

PARA = """There is nothing to pin and nothing to generate by hand. Both used to be
required, and both were easy to get wrong.

**The clock follows the data.** Every derived state — promise risk, at-risk,
"this week", which shift someone worked — is computed against "now", and the
dataset is generated relative to a moment and then stops moving. On the wall
clock, five days is enough to fail four of the fourteen answer checks: every
time-window question returns nothing, cites nothing, and is blocked by the output
rail. So "now" defaults to the newest event in the log instead. The shop is
always live and a dataset never goes stale. `ASOIA_NOW` still pins it when you
want a fixed clock, and `ASOIA_CLOCK=wall` restores the old behaviour.

**The dataset generates itself if there is none.** 400 repair orders, 10,715
events, 1,882 updates in about 0.1 seconds, with a window ending now. It fires
only when the database is empty, so it cannot overwrite anything;
`ASOIA_AUTOGEN=0` turns it off and `.venv/bin/python -m app.data.generate` still
works by hand.

It does **not** build the vector index — that means embedding every update
through a NIM, which is not a startup cost. Build it once:

```bash
.venv/bin/python -c 'from app.retrieval.index import build; print(build())'
```

and if the data is ever regenerated without rebuilding it, `/health`, the review
Overview and any affected answer all say so, because a stale index otherwise
produces confident, well-formed answers citing records that no longer exist."""

ROWS = [
    "| `ASOIA_NOW` | newest event | pins \"now\"; unset, the clock follows the data |",
    "| `ASOIA_CLOCK` | — | `wall` uses the wall clock, as it did before |",
    "| `ASOIA_AUTOGEN` | `1` | `0` never generates a dataset on start |",
    "| `ASOIA_GEN_ROS` / `ASOIA_GEN_DAYS` | `400` / `14` | size of a generated dataset |",
    "| `ASOIA_LOG_ANSWERS` | `1` | `0` stops recording what each answer cited |",
]

DONE, SKIP, MISS = [], [], []


def show(lines: list[str]) -> None:
    print("What this file sees in README.md:\n")
    for label, pred in [
            ("a launch line exporting ASOIA_NOW",
             lambda l: EXPORT_RE.match(l)),
            ("the '# 4.' launch comment", lambda l: l.strip().startswith("# 4.")),
            ("the ASOIA_NOW explanation",
             lambda l: "ASOIA_NOW` matters" in l or "There is nothing to pin" in l),
            ("an ASOIA_NOW table row",
             lambda l: l.strip().startswith("| `ASOIA_NOW`")),
            ("an ASOIA_DB table row",
             lambda l: l.strip().startswith("| `ASOIA_DB`")),
            ("the gradio launch command",
             lambda l: "app.ui.gradio_app" in l)]:
        hits = [(i + 1, l) for i, l in enumerate(lines) if pred(l)]
        if hits:
            for n, l in hits:
                print(f"  line {n:4d}  {label}\n            {l.rstrip()}")
        else:
            print(f"  ------    {label}: NOT FOUND")
    print()


def drop_export(lines: list[str]) -> list[str]:
    """Remove the exported date, and say in the comment above why there isn't one."""
    if any("No date to pin" in l for l in lines):
        SKIP.append("the launch already says there is no date to pin")
        return lines
    idx = [i for i, l in enumerate(lines) if EXPORT_RE.match(l)]
    if not idx:
        SKIP.append("no `export ASOIA_NOW=` line to remove")
    out = [l for i, l in enumerate(lines) if i not in set(idx)]
    if idx:
        DONE.append(f"removed the exported date (line {idx[0] + 1})")
    # Upgrade the step-4 comment wherever it is, so the reason is recorded.
    for i, l in enumerate(out):
        if l.strip().startswith("# 4.") and "launch" in l:
            out[i] = ("# 4. Prove the answers are built correctly, then launch. "
                      "No date to pin: the")
            out.insert(i + 1, "#    clock follows the newest event in the log, "
                              "and ASOIA_NOW still overrides it.")
            DONE.append("explained in the launch comment why there is no date")
            break
    else:
        MISS.append("could not find the '# 4. ... launch' comment to annotate")
    return out


def replace_paragraph(text: str) -> str:
    """Swap the old ASOIA_NOW explanation, or insert the new one after the block."""
    if "There is nothing to pin" in text:
        SKIP.append("the clock/bootstrap explanation is already there")
        return text
    # The old paragraph runs from its first sentence to the next blank line pair.
    m = re.search(r"`ASOIA_NOW` matters more than it looks\..*?(?=\n\n)", text,
                  re.S)
    if m:
        DONE.append("replaced the ASOIA_NOW paragraph")
        return text[:m.start()] + PARA + text[m.end():]
    # No old paragraph: put the new one after the fenced block that launches the UI.
    for fence in re.finditer(r"```.*?```", text, re.S):
        if "app.ui.gradio_app" in fence.group(0):
            DONE.append("inserted the clock/bootstrap explanation after the "
                        "launch block")
            return (text[:fence.end()] + "\n\n" + PARA + text[fence.end():])
    MISS.append("could not place the clock/bootstrap explanation - paste it in "
                "by hand from ENGINEERING-append-25.md")
    return text


def fix_table(lines: list[str]) -> list[str]:
    """Replace the ASOIA_NOW row and add the new ones, wherever the table is."""
    if any(l.strip().startswith("| `ASOIA_CLOCK`") for l in lines):
        SKIP.append("the environment table already lists the new variables")
        return lines
    for i, l in enumerate(lines):
        if l.strip().startswith("| `ASOIA_NOW`"):
            DONE.append(f"rewrote the ASOIA_NOW row and added "
                        f"{len(ROWS) - 1} more (line {i + 1})")
            return lines[:i] + ROWS + lines[i + 1:]
    for i, l in enumerate(lines):
        if l.strip().startswith("| `ASOIA_DB`"):
            DONE.append(f"added {len(ROWS)} environment rows above ASOIA_DB "
                        f"(line {i + 1})")
            return lines[:i] + ROWS + lines[i:]
    MISS.append("could not find the environment table - add these rows by hand:\n"
                + "\n".join("        " + r for r in ROWS))
    return lines


def main() -> int:
    if not README.exists():
        print("No README.md here. Run from the project root:\n"
              "  cd ~/automotive-service-agent && "
              ".venv/bin/python quality_pass25_readme.py")
        return 2
    text = README.read_text()
    lines = text.split("\n")

    if "--show" in sys.argv:
        show(lines)
        return 0

    lines = drop_export(lines)
    lines = fix_table(lines)
    text = replace_paragraph("\n".join(lines))

    if text != README.read_text():
        README.write_text(text)

    print("Pass 25, README:")
    for d in DONE:
        print(f"  ok    {d}")
    for s in SKIP:
        print(f"  skip  {s}")
    for m in MISS:
        print(f"  MISS  {m}")

    final = README.read_text()
    print()
    checks = [
        ("no exported date is left", not EXPORT_RE.search(final)),
        ("the new variables are documented", "`ASOIA_CLOCK`" in final),
        ("the clock and the bootstrap are explained",
         "There is nothing to pin" in final),
    ]
    bad = 0
    for name, ok in checks:
        bad += (not ok)
        print(f"  {'ok     ' if ok else 'WRONG  '} {name}")
    if bad:
        print("\nWhat it could not do is listed above. Run with --show to see the "
              "three regions it looks for; the text to paste is in "
              "ENGINEERING-append-25.md.")
    else:
        print("\nREADME is consistent with pass 25. Nothing else to do - the "
              "sixteen code edits applied when quality_pass25.py ran.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
