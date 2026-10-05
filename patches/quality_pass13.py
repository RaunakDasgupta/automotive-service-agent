#!/usr/bin/env python3
"""Thirteenth pass: a designed path is not a degradation, and attribute the 2.6s.

Run from the project root:   python3 quality_pass13.py

TWO THINGS THE TIMING RUN EXPOSED

1. `search_updates` has no renderer ON PURPOSE - summarising free-text technician
   notes is genuine language work, which is the one job the model is actually
   better at. But _summarise treats every missing renderer the same way, so the
   intended path prints

       [compose] falling back to the model: no renderer for search_updates

   on stderr, once per question, and the UI footer says "Fell back to the model".
   That is my own pass-8 observability crying wolf: a warning that fires on
   correct behaviour is a warning nobody will read on the day it matters, and to
   a demo audience the footer reads as a malfunction.

   `_NARRATED` now names the tools that are narrated by design. They compose
   through the model with no note and no warning. Every OTHER missing renderer,
   every renderer crash and every empty render still warns exactly as before -
   which is what caught the dict-slicing bug and the citation regression.

2. 2641ms for the one remaining model question, and no idea which part of it. The
   path is embed -> rerank -> narrate, and those have very different fixes: a
   slow rerank means the candidate pool is too wide, slow generation means the
   answer is too long. Guessing which would be a waste of a GPU hour.

   scripts/timings.py now instruments the three client calls and reports the
   split, so the next decision is made on a number.
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
                 "      Run passes 1-12 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ============================================ 1. narrated by design, not by failure
edit("app/agent/agent.py",
     '''def _summarise(results: list[dict], notes: list | None = None) -> str | None:
    """Compose the answer in Python when every tool in the plan has a renderer.

    If any tool does not, return None so the LLM narrates the whole payload
    rather than the answer silently losing part of it.

    Every reason for falling back is recorded in `notes` and warned on stderr.
    A silent fallback once hid a renderer crash for an entire release; it should
    never be possible to degrade to narration without a trace.
    """
    def note(msg: str):
        if notes is not None:
            notes.append(msg)
        print(f"[compose] falling back to the model: {msg}", file=_sys.stderr)

    blocks = []
    for r in results:
        tool = r.get("tool")
        fn = _RENDERERS.get(tool)
        if fn is None:
            note(f"no renderer for {tool}")
            return None''',
     '''# Tools with no renderer BY DESIGN. Summarising what technicians wrote in prose
# is genuine language work - the one job the model does better than a renderer
# could. Reaching the model through these is the intended path, so it must not
# raise a warning: an alarm that fires on correct behaviour is an alarm nobody
# reads on the day it means something.
_NARRATED = {"search_updates"}


def _summarise(results: list[dict], notes: list | None = None) -> str | None:
    """Compose the answer in Python when every tool in the plan has a renderer.

    If any tool does not, return None so the LLM narrates the whole payload
    rather than the answer silently losing part of it.

    Every UNINTENDED reason for falling back is recorded in `notes` and warned on
    stderr. A silent fallback once hid a renderer crash for an entire release; it
    should never be possible to degrade to narration without a trace. The tools
    in `_NARRATED` are the exception, and only because they were never meant to
    have a renderer.
    """
    def note(msg: str):
        if notes is not None:
            notes.append(msg)
        print(f"[compose] falling back to the model: {msg}", file=_sys.stderr)

    blocks = []
    for r in results:
        tool = r.get("tool")
        fn = _RENDERERS.get(tool)
        if fn is None:
            if tool not in _NARRATED:
                note(f"no renderer for {tool}")
            return None''',
     "agent.py  _NARRATED: designed paths do not warn",
     skip_if="_NARRATED = {")


# ============================================ 2. the footer says which, and why
edit("app/ui/gradio_app.py",
     '''def _footer(a) -> str:
    """The provenance line under an answer: which tools, which path, what sources."""
    how = ("computed from the records"
           if getattr(a, "composed", "") == "python" else "narrated by the model")''',
     '''def _footer(a) -> str:
    """The provenance line under an answer: which tools, which path, what sources.

    "Narrated by the model" needs its reason attached. On a free-text search that
    is the design; anywhere else it means a renderer was missing or broke, and the
    two should not read the same to someone deciding whether to trust the answer.
    """
    from app.agent.agent import _NARRATED
    tools = {c["name"] for c in a.tool_calls}
    if getattr(a, "composed", "") == "python":
        how = "computed from the records"
    elif tools and tools <= _NARRATED:
        how = "narrated by the model - free-text search, as designed"
    else:
        how = "narrated by the model"''',
     "gradio_app.py  footer distinguishes design from degradation",
     skip_if="as designed")


# ============================================ 3. attribute the time
p = ROOT / "scripts/timings.py"
p.parent.mkdir(exist_ok=True)
NEW = '''#!/usr/bin/env python3
"""Time each stage of the pipeline, per question class.

    .venv/bin/python scripts/timings.py
    .venv/bin/python scripts/timings.py --repeat 3

Reports which tools ran, whether the answer was composed in Python or narrated,
the wall time, and - for anything that touches a model - how that time splits
between embedding, reranking and generation.

That split is the point. "The search question takes 2.6 seconds" is not
actionable; "2.6 seconds, of which 1.4 is reranking eighteen candidates" is. A
slow rerank means the candidate pool is too wide for what it buys. Slow
generation means the answer is too long. They have opposite fixes, and guessing
wrong costs a GPU hour.

Run it twice: the second run shows what the query-embedding cache is worth.
"""
from __future__ import annotations
import argparse, os, statistics, sys, time

sys.path.insert(0, ".")

QUESTIONS = [
    "Which vehicles cannot be released on safety grounds?",
    "Give me the afternoon handover, worst first.",
    "What has EMP014 done this week?",
    "Who worked in the afternoon yesterday?",
    "Any unusual patterns in the shop this week?",
    "has anyone seen a whistling noise on a Passat",
]

STAGES: dict[str, list[float]] = {}


def _timed(label, fn):
    def wrapper(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            STAGES.setdefault(label, []).append((time.perf_counter() - t) * 1000)
    return wrapper


def _instrument():
    """Wrap the three model calls where they are actually looked up.

    index.py imported the embedder and reranker by name, so patching
    app.nim.client would not reach them - the bound names in app.retrieval.index
    are the ones that get called.
    """
    from app.retrieval import index as I
    from app.nim import client as C
    I.nim_embed_query = _timed("embed", I.nim_embed_query)
    I.nim_rerank = _timed("rerank", I.nim_rerank)
    return _timed("model", C.chat)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=2)
    args = ap.parse_args()

    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/agent")):
        print("Run from the project root:\\n"
              "  cd ~/automotive-service-agent && "
              ".venv/bin/python scripts/timings.py")
        return 2

    from app.agent.agent import ask
    try:
        chat_fn = _instrument()
    except Exception as e:
        print(f"(stage timing unavailable: {type(e).__name__}) ")
        chat_fn = None

    print(f"ASOIA_NOW = {os.environ.get('ASOIA_NOW', '(wall clock)')}")
    print(f"{args.repeat} runs each; the first pays cold start and a cold cache.\\n")
    print(f"{'path':7s} {'best':>8s} {'median':>8s}  question")
    print("-" * 78)
    slow = []
    for q in QUESTIONS:
        times, a, last_stages = [], None, {}
        for _ in range(args.repeat):
            STAGES.clear()
            t = time.perf_counter()
            try:
                a = ask(q, chat_fn=chat_fn) if chat_fn else ask(q)
            except Exception as e:
                print(f"{'ERROR':7s} {'':>8s} {'':>8s}  {q}\\n"
                      f"        {type(e).__name__}: {str(e)[:90]}")
                a = None
                break
            times.append((time.perf_counter() - t) * 1000)
            last_stages = {k: sum(v) for k, v in STAGES.items()}
        if not times or a is None:
            continue
        path = getattr(a, "composed", "?")
        best, med = min(times), statistics.median(times)
        print(f"{path:7s} {best:7.0f}ms {med:7.0f}ms  {q}")
        print(f"{'':7s} {'':>8s} {'':>8s}  tools: "
              f"{', '.join(c['name'] for c in a.tool_calls)}")
        if last_stages:
            split = ", ".join(f"{k} {v:.0f}ms" for k, v in
                              sorted(last_stages.items(), key=lambda x: -x[1]))
            # last_stages is the final run's, so compare it with that run's total.
            other = times[-1] - sum(last_stages.values())
            print(f"{'':7s} {'':>8s} {'':>8s}  of which: {split}"
                  f", the rest {other:.0f}ms (SQL, fold, rendering)")
        if best > 1500:
            slow.append((best, q, last_stages))
    print()
    if slow:
        print("Over 1.5s, so still making model calls:")
        for ms, q, st in sorted(slow, reverse=True):
            print(f"  {ms:6.0f}ms  {q}")
            if st:
                worst = max(st.items(), key=lambda x: x[1])
                print(f"           biggest single stage: {worst[0]} at {worst[1]:.0f}ms")
                if worst[0] == "rerank":
                    print("           -> the candidate pool is the lever: "
                          "search_updates retrieves 18 to keep 6.")
                elif worst[0] == "model":
                    print("           -> generation length is the lever: "
                          "max_tokens is 400, and streaming already hides most "
                          "of this from the reader.")
    else:
        print("Every question under 1.5s.")
    print("\\nA 'python' path makes no model call at all - if one of those is slow, "
          "the time is SQL or the event fold, not the GPU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
if p.exists() and "of which:" in p.read_text():
    CHANGES.append("  skip  scripts/timings.py  (stage split already present)")
else:
    p.write_text(NEW)
    CHANGES.append("  ok    scripts/timings.py  attribute the time by stage")


# ============================================ verify
print("Quality pass 13:")
for c in CHANGES:
    print(c)
for f in ("app/agent/agent.py", "app/ui/gradio_app.py", "scripts/timings.py"):
    ast.parse((ROOT / f).read_text())
print("\nagent.py, gradio_app.py and timings.py parse cleanly.")

# A designed path must be silent; a broken one must still shout.
import io, re, contextlib
src = (ROOT / "app/agent/agent.py").read_text()
ns: dict = {"_sys": sys}
exec(src[src.index("_NARRATED = {"):src.index("\ndef ask(")], ns)
ns["_RENDERERS"] = {"list_ros": lambda d: "rendered"}
_summarise = ns["_summarise"]

CASES = [
    ("search_updates narrates silently", [{"tool": "search_updates", "result": {}}],
     None, False),
    ("a genuinely missing renderer still warns",
     [{"tool": "get_op_code_info", "result": {}}], None, True),
    ("a renderer that works composes",
     [{"tool": "list_ros", "result": {"ros": []}}], "rendered", False),
]
print("\ncompose notes:")
bad = 0
for name, results, want_text, want_warn in CASES:
    notes: list = []
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        out = _summarise(results, notes)
    warned = bool(notes) or bool(buf.getvalue().strip())
    ok = (out == want_text) and (warned == want_warn)
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")
    print(f"           composed={out!r}  notes={notes}")

# The footer must not call the designed path a fallback.
gsrc = (ROOT / "app/ui/gradio_app.py").read_text()
for name, ok in [("footer names the design", "free-text search, as designed" in gsrc),
                 ("footer still has a plain narrated case",
                  'how = "narrated by the model"' in gsrc)]:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll pass-13 checks behaved as expected.")
print("\nNext:  .venv/bin/python scripts/verify_answers.py")
print("Then:  .venv/bin/python scripts/timings.py --repeat 3   (now shows the split)")
print("Then:  restart Gradio")
