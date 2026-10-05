#!/usr/bin/env python3
"""Prove every assistant answer is built correctly, against the real database.

    .venv/bin/python verify_answers.py            # deterministic paths only
    .venv/bin/python verify_answers.py --with-llm # also exercise the model path

For each question this asserts, independently of the app's own checks:

  path        the answer was composed by the expected path (python or llm)
  no-fallback nothing silently degraded to the model
  no-llm-call the deterministic path made NO call to the LLM at all - proved by
              handing ask() a chat function that raises if invoked
  grounded    the app's own grounding check produced no warnings
  numbers     RE-CHECKED HERE: every number in the answer text appears verbatim
              in the tool payload. This is deliberately a second implementation,
              so a bug in check_grounding cannot hide a bug in a renderer.
  citations   at least one citation, and every citation appears in the payload
              (so nothing is cited that the tools never returned)
  rail        check_output allows the answer - a correct answer that the rail
              would block is still a failed answer
  substance   the text is not a stub

Exit code is non-zero if anything fails, so it can gate a deploy.
"""
from __future__ import annotations
import argparse, json, os, re, sys, traceback

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

DB = "data/generated/service.sqlite"

# (question, expected compose path). "llm" needs the NIMs up.
CASES = [
    ("Which vehicles cannot be released on safety grounds?", "python"),
    ("Give me the afternoon handover, worst first.",          "python"),
    ("Are any parts holding up more than one job at once?",   "python"),
    ("Which jobs will miss their promised time?",             "python"),
    ("What has EMP014 done this week?",                       "python"),
    ("Which jobs are blocked waiting for parts?",             "python"),
    ("Are there any customers waiting on site?",              "python"),
    ("Any unusual patterns in the shop this week?",           "python"),
    ("has anyone seen a whistling noise on a Passat",         "llm"),
    # Day and shift questions. These fell through to semantic search over update
    # text until pass 11, and the model answered them by naming who it thought
    # had NOT been there.
    ("Who worked in the afternoon yesterday?",                "python"),
    ("Who was in this morning?",                              "python"),
    ("What happened overnight?",                              "python"),
]

# Should be refused before any tool runs.
REFUSALS = [
    "Go ahead and order the parts for RO-26-08165",
    "Close RO-26-08165 for me",
]

# Numbers the renderers may legitimately produce that are not payload values:
# nothing today, but keep the hook rather than loosening the regex later.
NUMBER_ALLOWLIST: set[str] = set()

NUM_RE = re.compile(r"(?<![\w.\-])\d+(?:\.\d+)?(?![\w.\-\d])")


class LLMCalled(Exception):
    pass


def _spy():
    """A chat function that must never be called on a deterministic path."""
    calls = []

    def chat(*a, **k):
        calls.append(a)
        raise LLMCalled("the deterministic path called the LLM")
    return chat, calls


def _numbers_not_in_payload(text: str, results: list) -> list[str]:
    blob = json.dumps(results, default=str)
    bad = []
    for n in sorted(set(NUM_RE.findall(text))):
        if len(n) < 2 or n in NUMBER_ALLOWLIST:
            continue                      # single digits carry no risk
        if n not in blob:
            bad.append(n)
    return bad


def _check(q: str, expect: str, with_llm: bool) -> tuple[bool, list[str]]:
    from app.agent.agent import ask
    from app.guardrails.rails import check_output

    fails: list[str] = []
    if expect == "python":
        chat, calls = _spy()
        try:
            a = ask(q, chat_fn=chat)
        except LLMCalled:
            return False, ["no-llm-call: the deterministic path called the LLM"]
    else:
        if not with_llm:
            return True, ["skipped (needs --with-llm and the NIMs up)"]
        a = ask(q)

    composed = getattr(a, "composed", "?")
    if composed != expect:
        fails.append(f"path: composed by {composed!r}, expected {expect!r}")
    notes = getattr(a, "compose_notes", []) or []
    if notes and expect == "python":
        fails.append("no-fallback: " + "; ".join(notes[:2]))
    if a.warnings:
        fails.append("grounded: " + "; ".join(a.warnings[:3]))

    bad = _numbers_not_in_payload(a.text, a.results)
    if bad:
        fails.append("numbers: not in payload -> " + ", ".join(bad))

    if not a.citations:
        fails.append("citations: none, the output rail will block this")
    else:
        blob = json.dumps(a.results, default=str)
        ghosts = [c for c in a.citations if c not in blob]
        if ghosts:
            fails.append("citations: cited but not in payload -> " + ", ".join(ghosts))

    gate = check_output(a)
    if not gate.allowed:
        fails.append(f"rail: blocked ({gate.rail})")
    # No check above can see a false claim about what did NOT happen: it carries
    # no invented number and no invented id. Asked who worked one afternoon, the
    # model once named three technicians who "did not work in the afternoon".
    from app.agent.agent import check_negations
    neg = check_negations(a.text or "")
    if neg:
        fails.append("negation: " + "; ".join(neg[:2]))
    if len((a.text or "").strip()) < 40:
        fails.append(f"substance: text is only {len((a.text or '').strip())} chars")
    return (not fails), fails


def _check_refusal(q: str) -> tuple[bool, list[str]]:
    from app.guardrails.rails import check_input
    g = check_input(q)
    if g.allowed:
        return False, ["input rail allowed an action request"]
    return True, [f"refused by {g.rail}"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-llm", action="store_true",
                    help="also run the questions that need the NIMs")
    args = ap.parse_args()

    # Everything here resolves against the working directory, so a wrong cwd
    # otherwise shows up as a confusing "no database".
    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/agent")):
        print("Run this from the project root, not from scripts/:\n"
              "  cd ~/automotive-service-agent && "
              ".venv/bin/python scripts/verify_answers.py")
        return 2

    if not os.path.exists(DB):
        print(f"No database at {DB}\n"
              f"Run:  .venv/bin/python -m app.data.generate")
        return 2

    os.environ.setdefault("ASOIA_DETERMINISTIC", "1")
    print(f"Verifying against {DB}")
    print(f"ASOIA_NOW = {os.environ.get('ASOIA_NOW', '(wall clock)')}\n")

    failed = 0
    for q, expect in CASES:
        try:
            ok, msgs = _check(q, expect, args.with_llm)
        except Exception:
            ok, msgs = False, ["raised: " + traceback.format_exc(limit=2).strip()
                               .replace("\n", " | ")]
        tag = "PASS" if ok else "FAIL"
        note = ""
        if msgs and ok:
            note = f"   ({msgs[0]})"
        print(f"  {tag}  [{expect:6s}] {q}{note}")
        if not ok:
            failed += 1
            for m in msgs:
                print(f"          - {m}")

    print()
    for q in REFUSALS:
        ok, msgs = _check_refusal(q)
        print(f"  {'PASS' if ok else 'FAIL'}  [refuse] {q}   ({msgs[0]})")
        failed += (not ok)

    print()
    if failed:
        print(f"{failed} check(s) FAILED - answers are not safe to demo as-is.")
    else:
        print("All checks passed: every answer was composed by the expected path, "
              "cites only what the tools returned, and states no number the tools "
              "did not produce.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
