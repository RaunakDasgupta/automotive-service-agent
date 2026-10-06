#!/usr/bin/env python3
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
import argparse, json, os, pathlib, statistics, sys, time

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

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


USAGE: dict = {}


def _instrument():
    """Wrap the three model calls where they are actually looked up.

    index.py imported the embedder and reranker by name, so patching
    app.nim.client would not reach them - the bound names in app.retrieval.index
    are the ones that get called.

    The chat wrapper also collects the token counts, so 2.5 seconds of generation
    can be read as a long answer or a slow one. Those have different fixes.
    """
    from app.retrieval import index as I
    from app.nim import client as C
    I.nim_embed_query = _timed("embed", I.nim_embed_query)
    I.nim_rerank = _timed("rerank", I.nim_rerank)
    timed_chat = _timed("model", C.chat)

    def chat_with_usage(*a, **k):
        m: dict = {}
        k["meta"] = m
        try:
            return timed_chat(*a, **k)
        finally:
            USAGE.clear()
            USAGE.update({x: y for x, y in m.items() if y is not None})
    return chat_with_usage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=2)
    # The gate reads this. Latency is the one thing in this project that was
    # measured and reported but never gated, which means an agent told to make
    # the agent faster could trade correctness for milliseconds and nothing
    # would fail.
    ap.add_argument("--json", metavar="PATH", help="write the profile as JSON")
    args = ap.parse_args()

    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/agent")):
        print("Run from the project root:\n"
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
    print(f"{args.repeat} runs each; the first pays cold start and a cold cache.\n")
    print(f"{'path':7s} {'best':>8s} {'median':>8s}  question")
    print("-" * 78)
    slow = []
    records: list[dict] = []
    for q in QUESTIONS:
        times, a, last_stages, last_usage = [], None, {}, {}
        for _ in range(args.repeat):
            STAGES.clear()
            t = time.perf_counter()
            try:
                a = ask(q, chat_fn=chat_fn) if chat_fn else ask(q)
            except Exception as e:
                print(f"{'ERROR':7s} {'':>8s} {'':>8s}  {q}\n"
                      f"        {type(e).__name__}: {str(e)[:90]}")
                a = None
                break
            times.append((time.perf_counter() - t) * 1000)
            last_stages = {k: sum(v) for k, v in STAGES.items()}
            last_usage = dict(USAGE)
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
            if last_usage:
                out = last_usage.get("completion_tokens")
                gen = last_stages.get("model")
                rate = (f", {out / (gen / 1000):.0f} tok/s"
                        if out and gen else "")
                print(f"{'':7s} {'':>8s} {'':>8s}  prompt "
                      f"{last_usage.get('prompt_tokens')} tokens -> "
                      f"{out} generated{rate}"
                      + ("   ** TRUNCATED at max_tokens **"
                         if last_usage.get("finish_reason") == "length" else ""))
        records.append({
            "q": q, "path": path, "best_ms": round(best, 1),
            "median_ms": round(med, 1),
            "tools": [c["name"] for c in a.tool_calls],
            "stages_ms": {k: round(v, 1) for k, v in last_stages.items()},
            "prompt_tokens": last_usage.get("prompt_tokens"),
            "completion_tokens": last_usage.get("completion_tokens"),
            "finish_reason": last_usage.get("finish_reason"),
        })
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
    print("\nA 'python' path makes no model call at all - if one of those is slow, "
          "the time is SQL or the event fold, not the GPU.")
    if args.json:
        pathlib.Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.json).write_text(json.dumps({
            "asoia_now": os.environ.get("ASOIA_NOW"),
            "repeat": args.repeat,
            "questions": records,
        }, indent=2) + "\n")
        print(f"  wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
