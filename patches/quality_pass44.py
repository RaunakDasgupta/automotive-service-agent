#!/usr/bin/env python
"""Pass 44 - the shadow rails were measured by their vocabulary, not their verdict.

`ASOIA_NEMO_RAILS=shadow` has been on since pass 21 so the colang rails could be
compared against the hand-written patterns before anyone trusted them. The
comparison was wrong, and it was wrong in the direction that matters: it scored
real blocks as allows.

`verdict()` decided "the rail fired" by looking for refusal wording in the
answer. A colang input rail that matches never produces wording. It returns a
`stop` decision, the pipeline halts, and `generate()` returns `content=''`.
Measured here on "Close RO-26-08165 for me":

    activated_rails: [input 'refuse out of scope', stop=True, ['stop']]
    llm_calls: 0        input_rails_duration: 0.98ms
    response: [{'role': 'assistant', 'content': ''}]

The rail blocked it in a millisecond without calling a model, and the matcher
recorded that as permission to proceed. Driving `evaluate.REFUSALS` through
/ask produced four `builtin_only_block` - which reads as "colang missed what
the patterns caught" when the truth was the exact opposite. On that evidence
anyone would have concluded the colang rails were inert and left them in shadow
forever, which is precisely what the shadow period was supposed to prevent.

This reads `activated_rails` instead. Matching on structure rather than on
phrasing is the same correction this project has now made eight times.

The prediction this pass makes, and the check that tests it: re-running the four
adversarial questions must now record `agree_block`, not `builtin_only_block`,
and the legitimate set must keep recording `agree_allow`.

Enforcement is untouched. This changes only what the shadow comparison reports;
`ASOIA_NEMO_RAILS` stays on whatever it was.

Idempotent. Re-running changes nothing and says so.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not (ROOT / "scripts").is_dir():
    ROOT = ROOT.parent


def note(s: str) -> None:
    print("  " + s)


VERDICT = 'def verdict(question: str) -> bool | None:\n    """Would the colang rails allow this? True/False, or None for no opinion.\n\n    Reads the rails\' own structured decision, not the text they return.\n\n    The text heuristic this replaces could not work, and the shadow numbers it\n    produced were worse than no numbers. A colang input rail that matches does\n    not emit its `bot refuse ...` message: it returns a `stop` decision, the\n    pipeline halts, and `generate()` hands back `content=\'\'`. So there is no\n    refusal wording to match on, and every real block was scored as an allow.\n\n    Measured on this box, "Close RO-26-08165 for me":\n\n        activated_rails: [input \'refuse out of scope\', stop=True, [\'stop\']]\n        llm_calls: 0        input_rails_duration: 0.98ms\n        response: [{\'role\': \'assistant\', \'content\': \'\'}]\n\n    The rail fired, in a millisecond, without calling a model - and the old\n    matcher called that permission to proceed. Four action requests were\n    recorded as `builtin_only_block`, which reads as "colang missed what the\n    patterns caught" when the truth was the exact opposite.\n\n    An empty answer is also not an allow decision, so when no log comes back the\n    fall-back refuses to guess and returns None rather than True.\n    """\n    rails = _get()\n    if rails is None:\n        return None\n    try:\n        res = rails.generate(\n            messages=[{"role": "user", "content": question}],\n            options={"log": {"activated_rails": True}},\n        )\n    except Exception:\n        return None\n    try:\n        log = getattr(res, "log", None)\n        rails_log = getattr(log, "activated_rails", None) if log is not None else None\n        if rails_log:\n            for r in rails_log:\n                if getattr(r, "stop", False):\n                    return False\n                if "stop" in (getattr(r, "decisions", None) or []):\n                    return False\n            return True\n\n        # No structured log. Keep the old reading as a fall-back, because a\n        # future version may stop returning one - but an empty answer means the\n        # pipeline was halted or produced nothing, and neither is an allow.\n        resp = getattr(res, "response", res)\n        if isinstance(resp, list):\n            resp = resp[0] if resp else {}\n        text = (resp.get("content") if isinstance(resp, dict) else str(resp)) or ""\n        low = text.strip().lower()\n        if not low:\n            return None\n        return not any(low.startswith(r) or r in low[:120] for r in _REFUSALS)\n    except Exception:\n        return None\n'


def patch_nemo() -> None:
    rel = "app/guardrails/nemo.py"
    p = ROOT / rel
    txt = p.read_text()
    if "activated_rails" in txt:
        note(f"{rel}: already reads the structured verdict, skipped")
        return
    # Replace exactly the verdict() function, from its def to the next
    # top-level def. Anchored on both ends so a changed file refuses rather
    # than getting a second copy appended.
    m = re.search(r"^def verdict\(question: str\) -> bool \| None:\n", txt, re.M)
    if not m:
        raise RuntimeError(f"pass 44 refused: no verdict() in {rel}")
    nxt = re.search(r"^def (?!verdict)", txt[m.end():], re.M)
    if not nxt:
        raise RuntimeError(f"pass 44 refused: no function follows verdict() in {rel}")
    end = m.end() + nxt.start()
    old = txt[m.start():end]
    if "_REFUSALS" not in old:
        raise RuntimeError(
            "pass 44 refused: the verdict() found does not use _REFUSALS, so it "
            "is not the text-matching version this pass was written against")
    txt = txt[:m.start()] + VERDICT.rstrip("\n") + "\n\n\n" + txt[end:]
    p.write_text(txt)
    note(f"{rel}: verdict() now reads activated_rails "
         f"({len(old.splitlines())} lines -> {len(VERDICT.splitlines())})")


def readme_row() -> None:
    rel = "patches/README.md"
    p = ROOT / rel
    txt = p.read_text()
    if "quality_pass44.py" in txt:
        note(f"{rel}: row already present, skipped")
        return
    m = re.search(r"^\| `quality_pass43\.py`.*$", txt, re.M)
    if not m:
        note(f"{rel}: no row 43 to insert after, skipped")
        return
    row = ("| `quality_pass44.py` | the shadow rail comparison matched refusal "
           "wording, but a colang `stop` emits no wording at all - so every real "
           "block was recorded as an allow, and the colang rails looked inert "
           "when they were firing in 1ms with no model call |")
    p.write_text(txt[:m.end()] + "\n" + row + txt[m.end():])
    note(f"{rel}: row added after quality_pass43.py")


def checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def ck(n: str, ok: bool, d: str = "") -> None:
        out.append((n, bool(ok), d))

    rel = ROOT / "app/guardrails/nemo.py"
    body = rel.read_text()

    import ast
    try:
        ast.parse(body)
        ck("nemo.py parses", True)
    except SyntaxError as e:
        ck("nemo.py parses", False, str(e))
        return out

    ck("verdict reads activated_rails", "activated_rails" in body)
    ck("verdict asks for the log", '"log"' in body and "activated_rails" in body)
    # A stop decision must mean False. Checked as syntax, not prose.
    ck("a stop decision returns False",
       bool(re.search(r"stop[^\n]*\n\s*return False|return False", body)))
    # The fall-back must not call an empty answer an allow - that was the bug.
    ck("an empty answer is not an allow", "if not low:" in body and
       re.search(r"if not low:\s*\n\s*return None", body) is not None)
    # Enforcement must be untouched: exactly one definition of each entry point.
    for fn in ("def enforce", "def observe", "def mode", "def available"):
        ck(f"{fn}() still defined once", body.count(fn + "(") == 1,
           f"{body.count(fn + '(')} occurrences")
    ck("only one verdict()", body.count("def verdict(") == 1,
       f"{body.count('def verdict(')} occurrences")

    r = subprocess.run([str(ROOT / ".venv/bin/python"), "-c",
                        "import sys; sys.path.insert(0,'.'); sys.path.insert(0,'scripts');"
                        "import _env; _env.load();"
                        "from app.guardrails import nemo; print(nemo.mode(), nemo.available())"],
                       capture_output=True, text=True, cwd=str(ROOT))
    ck("module still imports and reports mode", r.returncode == 0,
       (r.stderr or r.stdout).strip().splitlines()[-1][:120] if r.returncode else "")

    txt = (ROOT / "patches/README.md").read_text()
    rows = re.findall(r"^\| `([^`]+\.py)`", txt, re.M)
    files = sorted(x.name for x in (ROOT / "patches").glob("quality_pass*.py"))
    ck("README has a row 44", "quality_pass44.py" in rows)
    ck("README rows match script files", sorted(rows) == files,
       f"{len(rows)} rows vs {len(files)} files")
    return out


def main() -> int:
    print("pass 44: read the rails' verdict, not their vocabulary\n")
    patch_nemo()
    readme_row()
    print("\nchecks")
    bad = 0
    for n, ok, d in checks():
        print(f"  [{'ok' if ok else 'FAIL'}] {n}" + (f"  -- {d}" if d and not ok else ""))
        bad += 0 if ok else 1
    print()
    if bad:
        print(f"{bad} check(s) failed")
        return 1
    print("all checks passed")
    print("\nthe prediction to verify, with the API restarted:")
    print("  the four evaluate.REFUSALS must now record agree_block,")
    print("  where they previously recorded builtin_only_block.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
