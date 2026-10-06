#!/usr/bin/env python3
"""Run the answer-level measures as NeMo Evaluator benchmarks, and keep the run.

    .venv/bin/python scripts/eval_standard.py
    .venv/bin/python scripts/eval_standard.py --no-build --no-cross-check
    .venv/bin/python scripts/eval_standard.py --history

What this adds over `scripts/evaluate.py`, which prints better numbers than this
one: a run that still exists tomorrow. Each run appends a record to
run/evals/history.jsonl with the scores AND the provenance - which store, which
models, how many rows - and prints the delta against the previous run. Six numbers
in a terminal cannot tell you whether a change helped; two runs can.

NO PLUGIN IS INSTALLED

`nemo-evaluator-byob` compiles a module into a pip-installable plugin, and
`nemo-evaluator run_eval` then drives it. Two reasons not to do that here:

  * the generated plugin's output.py reads `<output_dir>/byob_results.json` while
    the runner writes `<output_dir>/<benchmark>/byob_results.json`, so run_eval
    fails with FileNotFoundError after a successful evaluation;
  * installing it writes a `nemo_evaluator_byob.pth` that raises NameError on
    every interpreter start in this venv, printing a traceback before any command
    in the project runs.

The runner itself takes `--benchmark-module <path>` and needs no installation, so
this calls it directly - the same command the generated framework.yml would have
run - and reads the results file where it is actually written. Both upstream bugs
are worth knowing about rather than working around silently, which is why they are
named here.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

MODULE = "evals/asoia_byob.py"
HISTORY = pathlib.Path("run/evals/history.jsonl")
BENCHMARKS = {
    "asoia_routing": "evals/data/answers.jsonl",
    "asoia_grounding": "evals/data/answers.jsonl",
    "asoia_traceability": "evals/data/answers.jsonl",
    "asoia_refusal": "evals/data/refusals.jsonl",
    # Added after routing scored 30/30 through a pass that called the right
    # tool with the wrong arguments, and through another that ran two tools
    # where one was asked for.
    "asoia_tool_calls": "evals/data/answers.jsonl",
    "asoia_accuracy": "evals/data/answers.jsonl",
    "asoia_relevance": "evals/data/answers.jsonl",
}


def provenance() -> dict:
    """What produced these answers. A score without this is not comparable."""
    out: dict = {}
    try:
        from app.retrieval.backend import backend
        b = backend()
        st = b.stats()
        out["store"] = {"backend": st.get("backend"), "mode": st.get("mode"),
                        "uri": st.get("uri"), "dim": b.dim(), "rows": b.count()}
    except Exception as e:
        out["store"] = {"error": type(e).__name__}
    try:
        from app.nim.client import resolve
        out["models"] = {s: {"mode": m, "model": mdl}
                         for s in ("llm", "embed", "rerank")
                         for _b, mdl, m in [resolve(s)]}
    except Exception as e:
        out["models"] = {"error": type(e).__name__}
    return out


def run_one(name: str, dataset: str, out_dir: pathlib.Path) -> dict:
    """-> {metric: value}. Invokes the official runner, reads the official file."""
    try:
        from app.nim.client import resolve
        base, model, _mode = resolve("llm")
        url = base.rstrip("/") + "/chat/completions"
    except Exception:
        url, model = "http://localhost:8000/v1/chat/completions", "unused"
    cmd = [sys.executable, "-m", "nemo_evaluator.contrib.byob.runner",
           "--benchmark-module", MODULE, "--benchmark-name", name,
           "--dataset", dataset, "--output-dir", str(out_dir),
           "--model-url", url, "--model-id", model, "--model-type", "chat"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    res = out_dir / name / "byob_results.json"
    if not res.exists():
        tail = (r.stderr or r.stdout or "")[-400:].replace("\n", " | ")
        return {"_error": f"rc={r.returncode} {tail}"}
    raw = json.loads(res.read_text())
    scores = (raw.get("tasks", {}).get(name, {}).get("metrics", {})
                 .get("pass@1", {}).get("scores", {}))
    flat = {}
    for metric, body in scores.items():
        flat[metric] = body.get("value")
        st = body.get("stats") or {}
        if "count" in st:
            flat[metric + "__n"] = st["count"]
    return flat


def cross_check(scores: dict) -> list[str]:
    """Do the two implementations of the shared measures agree?

    plan_exact and traceability are defined identically in evaluate.py and in
    evals/asoia_byob.py, and computed from different inputs by different code.
    plan_exact and not routing_accuracy: evaluate.py scores the whole plan, so
    comparing it against the benchmark that asks only whether the right tool is
    somewhere in the plan was comparing two different questions and calling
    agreement.
    Agreement is real evidence. Disagreement means one of them is wrong, and the
    point of having two is to be told so rather than to average them.
    """
    problems = []
    tmp = pathlib.Path("run/evals/.cross.json")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, "scripts/evaluate.py", "--json", str(tmp)],
                       capture_output=True, text=True, timeout=1800)
    if not tmp.exists():
        return [f"evaluate.py produced no json (rc={r.returncode})"]
    ev = json.loads(tmp.read_text()).get("scores", {})
    for ours, theirs in (("plan_exact", "routing"),
                         ("traceability", "traceability")):
        a = scores.get(ours)
        b = ev.get(theirs)
        if a is None or b is None:
            problems.append(f"{ours}: missing ({a} vs {b})")
            continue
        # evaluate.py reports percent, the benchmark reports a 0-1 mean.
        if abs(a * 100.0 - b) > 0.1:
            problems.append(f"{ours}={a * 100:.1f}% but evaluate.py says "
                            f"{theirs}={b}%")
    return problems



# Ratcheted. 80% when 89.2% was reached, 90% now that the two handover
# questions are scored and 94.6% is - which is the ceiling, because the two
# free-text searches have no correct number. The floor is raised deliberately
# each time coverage rises: a floor left below what has been achieved permits
# the next change to give it back.
MIN_ACCURACY_COVERAGE = 0.90
# A benchmark that scores 10 of 37 rows and reports 100% is reporting the rows
# it chose. accuracy_scored is the share of questions carrying an independently
# derived number, and it is gated: add a deterministic question without adding
# its truth to make_eval_dataset.py and this run fails. Without a floor the
# coverage only ever falls, because the cheapest way to add a question is to
# add one nothing checks.
def check_coverage(scores: dict) -> list[str]:
    got = scores.get("accuracy_scored")
    if got is None:
        return ["accuracy_scored is missing - the accuracy benchmark did not run"]
    if got + 1e-9 < MIN_ACCURACY_COVERAGE:
        return [f"accuracy coverage {got * 100:.1f}% is below the "
                f"{MIN_ACCURACY_COVERAGE * 100:.0f}% floor - a question was added "
                f"without a truth value in make_eval_dataset.py"]
    return []

def show_history(n: int = 10) -> int:
    if not HISTORY.exists():
        print("No runs recorded yet.")
        return 0
    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
    print(f"{len(rows)} run(s) recorded; last {min(n, len(rows))}:\n")
    keys = ["plan_exact", "arg_agreement", "answer_accuracy", "relevance",
            "routing_accuracy", "figures_supported", "traceability",
            "refused_before_tools"]
    print("  " + "when".ljust(21) + "".join(k[:18].rjust(20) for k in keys))
    for r in rows[-n:]:
        s = r.get("scores", {})
        line = "  " + str(r.get("at", "?"))[:19].ljust(21)
        for k in keys:
            v = s.get(k)
            line += ("-" if v is None else f"{v * 100:.1f}%").rjust(20)
        print(line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true",
                    help="score the existing datasets instead of regenerating")
    ap.add_argument("--no-cross-check", action="store_true",
                    help="skip agreeing with scripts/evaluate.py")
    ap.add_argument("--history", action="store_true", help="show past runs and exit")
    args = ap.parse_args()

    if args.history:
        return show_history()

    if not args.no_build:
        print("building the datasets from the agent's own answers:")
        r = subprocess.run([sys.executable, "scripts/make_eval_dataset.py"],
                           timeout=1800)
        if r.returncode != 0:
            print("dataset build failed.")
            return 2
        print()

    missing = [d for d in set(BENCHMARKS.values()) if not pathlib.Path(d).exists()]
    if missing:
        print("missing dataset(s): " + ", ".join(missing))
        print("drop --no-build, or run scripts/make_eval_dataset.py")
        return 2

    stamp = time.strftime("%Y%m%dT%H%M%S")
    out_dir = pathlib.Path("run/evals") / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    prov = provenance()
    st = prov.get("store", {})
    print(f"store    {st.get('backend')}/{st.get('mode')} {st.get('uri')}"
          f"   dim={st.get('dim')}  rows={st.get('rows')}")
    for s, m in (prov.get("models") or {}).items():
        if isinstance(m, dict) and "model" in m:
            print(f"{s:8s} {m.get('mode', '?'):7s} {m.get('model')}")
    print()

    scores: dict = {}
    failed = []
    for name, dataset in BENCHMARKS.items():
        got = run_one(name, dataset, out_dir)
        if "_error" in got:
            failed.append(f"{name}: {got['_error']}")
            print(f"  FAILED  {name}  {got['_error'][:120]}")
            continue
        for k, v in got.items():
            if not k.endswith("__n"):
                scores[k] = v
        shown = ", ".join(f"{k}={v}" for k, v in got.items() if not k.endswith("__n"))
        n = next((v for k, v in got.items() if k.endswith("__n")), "?")
        print(f"  ok      {name:22s} n={n}  {shown}")

    print()
    prev = None
    if HISTORY.exists():
        rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
        prev = rows[-1] if rows else None

    print("=" * 62)
    for k in sorted(scores):
        v = scores[k]
        if v is None:
            continue
        line = f"  {k:24s} {v * 100:6.1f}%" if v <= 1.0 else f"  {k:24s} {v:6.1f}"
        if prev:
            old = (prev.get("scores") or {}).get(k)
            if old is not None and v is not None:
                d = (v - old) * 100.0
                line += f"   {'=' if abs(d) < 0.05 else f'{d:+.1f}pt vs last run'}"
        print(line)

    problems = [] if args.no_cross_check else cross_check(scores)
    shortfall = check_coverage(scores)
    if shortfall:
        print("\nACCURACY COVERAGE:")
        for s in shortfall:
            print("  " + s)
    else:
        print(f"\n  accuracy coverage {scores.get('accuracy_scored', 0) * 100:.1f}% "
              f"(floor {MIN_ACCURACY_COVERAGE * 100:.0f}%)")
    problems += shortfall
    if problems:
        print("\nTHE TWO IMPLEMENTATIONS DISAGREE:")
        for p in problems:
            print("  " + p)
    if not problems and not args.no_cross_check:
        print("  routing and traceability agree with scripts/evaluate.py")

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as fh:
        fh.write(json.dumps({
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "scores": {k: v for k, v in scores.items() if v is not None},
            "provenance": prov,
            "results_dir": str(out_dir),
            "cross_check": "skipped" if args.no_cross_check else
                           ("agree" if not problems else problems),
        }) + "\n")
    print(f"\n  recorded in {HISTORY}   ({out_dir})")

    if failed or problems:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
