#!/usr/bin/env python
"""The improvement loop: a sandbox proposes, this box decides.

NemoClaw's coding agent cannot run this project's full suite. The box it runs
on is CPU-only - `nemoclaw-asoia` is an n2d-standard-4 with `gpu: "-"` - so it
can serve neither the chat NIM nor the embedding model. What it CAN run is the
model-free half of the measurement, and that half was already written:
`scripts/evaluate.py` without --with-llm scores routing, grounding,
traceability and refusal, and skips retrieval, rerank and narration.

Three properties make a score from that sandbox comparable to a score from
here, rather than merely similar:

  * the dataset is seeded (`app.data.generate`, seed 20260924), so a sandbox
    that rebuilds it gets the same rows, not a fresh random shop;
  * the clock anchors to the newest event in the log rather than the wall
    clock (app/clock.py), so "this week" means the same week in both places
    without anyone remembering to pin ASOIA_NOW;
  * eval_grounding's spy RAISES if a deterministic path calls the model, so a
    passing grounding score is evidence the run needed no model, not a claim
    that it didn't.

So the loop is:

    sandbox    agent_loop.py fast      model-free, run on every edit
    GitHub     push a branch           the transport; no gateway, no SSH
    this box   agent_loop.py gate      the full suite; the only number that counts

WHY THE LOCK EXISTS. An agent optimising against a scorer will eventually edit
the scorer, and it will not mention that it did. `fast` and `gate` both refuse
to report any score while a measuring file differs from the lock, because a
number produced by a modified measure is not comparable to the baseline it is
being compared against. Changing the measure is allowed - it happened in eight
separate passes here - but it takes `relock`, which is a deliberate act with a
human behind it, and which resets the baseline rather than inheriting it.

Verbs:
    fast     integrity, then the model-free subset, against the baseline
    gate     integrity, then the full suite, against the baseline
    status   what the baseline is, and whether the measure is intact
    accept   adopt the latest gated run as the new baseline
    relock   re-lock the measure after deliberately changing it
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The measure. Not "the eval files": these five are what turns behaviour into a
# number, and the whole point of the lock is that a proposal cannot touch them.
HARNESS = (
    "evals/truth.py",
    "evals/asoia_byob.py",
    "scripts/make_eval_dataset.py",
    "scripts/eval_standard.py",
    "scripts/evaluate.py",
    # Added when latency became gated. It feeds `perf`, so an agent that can
    # edit it can report whatever milliseconds it likes.
    "scripts/timings.py",
)
LOCK = ROOT / "evals/harness.lock"
BASELINE = ROOT / "evals/baseline.json"
HISTORY = ROOT / "run/evals/history.jsonl"
DB = ROOT / "data/generated/service.sqlite"

# Three of these are counts, not rates, and one of those is not a quality claim.
# arg_rules_checked and figures_per_row say how much the measure looks at, so
# they are gated upward: letting them fall is how a suite keeps a green run while
# checking less. citations is a total that moves with the dataset, so it is
# printed and never gated - a floor on it would only invite padding.
LOWER_IS_BETTER = {"spurious_tools", "unresolved_citations", "unsupported_figures"}
# Every perf metric is lower-is-better, so they are matched by suffix rather
# than listed - a new question in timings.py should not silently arrive ungated.
PERF_SUFFIXES = ("_ms", "_tokens", "_calls")
COUNTS = {"citations", "arg_rules_checked", "figures_per_row"}
INFORMATIONAL = {"citations"}


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*a: str) -> str:
    try:
        return subprocess.run(("git",) + a, cwd=ROOT, capture_output=True,
                              text=True, timeout=60).stdout.strip()
    except Exception:
        return ""


def harness_digests() -> tuple[dict, list[str]]:
    cur, missing = {}, []
    for rel in HARNESS:
        p = ROOT / rel
        if p.exists():
            cur[rel] = sha(p)
        else:
            missing.append(rel)
    return cur, missing


def integrity() -> list[str]:
    """Empty exactly when the measure is the one the baseline was taken with."""
    cur, missing = harness_digests()
    out = [f"{m} is missing" for m in missing]
    if not LOCK.exists():
        out.append(f"{LOCK.relative_to(ROOT)} does not exist - run: "
                   f"agent_loop.py relock --i-am-changing-the-measure")
        return out
    want = (json.loads(LOCK.read_text()) or {}).get("files", {})
    for rel in sorted(set(want) | set(cur)):
        if rel not in want:
            out.append(f"{rel} is not in the lock")
        elif rel in cur and want[rel] != cur[rel]:
            out.append(f"{rel} has changed since the lock was taken")
    return out


def baseline() -> dict:
    if not BASELINE.exists():
        raise SystemExit(f"no baseline. Run a full suite, then:  "
                         f"{sys.executable} scripts/agent_loop.py accept")
    return json.loads(BASELINE.read_text())


def newest_run() -> dict | None:
    if not HISTORY.exists():
        return None
    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
    return rows[-1] if rows else None


# ------------------------------------------------------------------ comparing
def _fmt(kind: str, k: str, v: float) -> str:
    if kind == "perf":
        return f"{v:8.0f}ms" if k.endswith("_ms") else f"{v:8.0f}  "  # counts
    if kind == "fast":
        return f"{v:6.1f}%"
    return f"{v:6.2f}" if k in COUNTS else f"{v * 100:6.1f}%"


def _delta(kind: str, k: str, v: float, old: float) -> float:
    if kind in ("fast", "perf") or k in COUNTS:
        return v - old
    return (v - old) * 100.0


def _tol(kind: str, k: str, old: float = 0.0) -> float:
    if kind == "perf":
        # Measured over three consecutive runs on an idle L40S: the model path
        # varied 0% (1797/1799/1795), prompt and completion tokens 0%, and the
        # Python paths 1-2% above 6ms. The 2ms question swings 20% relatively,
        # which is a fraction of a millisecond absolutely - hence the 5ms floor,
        # so a sub-millisecond wobble cannot fail a run.
        #
        # 15% is therefore about ten times the observed noise. It is deliberately
        # loose: a latency gate that cries wolf gets switched off, and the thing
        # worth catching is a change that doubles a stage, not one that costs 3%.
        if k.endswith("_calls"):
            # A call count is a small integer and exactly reproducible, so any
            # increase is a real change rather than noise.
            return 0.0
        if k.endswith("_tokens"):
            return max(old * 0.10, 1.0)
        return max(old * 0.15, 5.0)
    if kind == "fast":
        return 0.05
    return 0.005 if k in COUNTS else 0.0005


def compare(kind: str, got: dict, base: dict) -> tuple[list[str], list[str]]:
    """(regressions, printable lines). Absent-from-baseline is new, not a win."""
    regressions, lines = [], []
    for k in sorted(set(got) | set(base)):
        v, old = got.get(k), base.get(k)
        if v is None:
            regressions.append(f"{k} is gone - the baseline had "
                               f"{_fmt(kind, k, old)}")
            continue
        if old is None:
            lines.append(f"  {k:24s} {_fmt(kind, k, v)}   (new)")
            continue
        d = _delta(kind, k, v, old)
        tol = _tol(kind, k, old)
        inverted = k in LOWER_IS_BETTER or (
            kind == "perf" and k.endswith(PERF_SUFFIXES))
        worse = (v > old + tol) if inverted else (v < old - tol)
        if worse and k not in INFORMATIONAL:
            regressions.append(f"{k} {_fmt(kind, k, old).strip()} -> "
                               f"{_fmt(kind, k, v).strip()} ({d:+.2f})")
        mark = "=" if abs(d) <= tol else f"{d:+.2f}"
        if k in INFORMATIONAL and abs(d) > tol:
            mark += " (not gated)"
        lines.append(f"  {k:24s} {_fmt(kind, k, v)}   {mark}")
    return regressions, lines


def _verdict(title: str, regressions: list[str], lines: list[str]) -> None:
    print("\n" + "=" * 62)
    print(f"{title}  (vs baseline)")
    for l in lines:
        print(l)
    if regressions:
        print("\nREGRESSIONS - this proposal is not an improvement:")
        for r in regressions:
            print("  " + r)
    else:
        print("\n  nothing regressed")


# --------------------------------------------------------------------- verbs
def ensure_db(quiet: bool = False) -> None:
    if DB.exists():
        return
    if not quiet:
        # flush: the subprocess writes straight to the terminal, so an
        # unflushed print lands AFTER its output and reads as though the
        # database had been generated after being scored.
        print("no database yet - generating it (seeded 20260924, so this is "
              "the same shop the gate will score)", flush=True)
    r = subprocess.run([sys.executable, "-m", "app.data.generate"], cwd=ROOT)
    if r.returncode != 0 or not DB.exists():
        raise SystemExit("could not generate the dataset")


PERF_JSON = ROOT / "run/evals/.perf.json"


def run_perf(repeat: int = 3) -> dict:
    """The latency profile, flattened to a handful of gated numbers.

    Per-question keys were the obvious choice and are not used: six questions
    times three numbers is eighteen gates that all move together, and a gate
    nobody reads is a gate nobody maintains. These six say the things that have
    different fixes - a slow Python path is SQL, a slow model stage is
    generation length, and a grown prompt is retrieval pulling more than it
    needs.
    """
    if PERF_JSON.exists():
        PERF_JSON.unlink()
    print("timing the pipeline (needs the NIMs up):", flush=True)
    subprocess.run([sys.executable, "scripts/timings.py", "--repeat",
                    str(repeat), "--json", str(PERF_JSON)],
                   cwd=ROOT, timeout=3600)
    if not PERF_JSON.exists():
        return {}
    qs = (json.loads(PERF_JSON.read_text()) or {}).get("questions", [])
    py = [q for q in qs if q.get("path") == "python"]
    llm = [q for q in qs if q.get("path") == "llm"]
    out: dict = {}
    if py:
        out["worst_python_ms"] = max(q["best_ms"] for q in py)
    if llm:
        out["llm_best_ms"] = max(q["best_ms"] for q in llm)
        out["llm_model_ms"] = max(q.get("stages_ms", {}).get("model", 0.0)
                                  for q in llm)
        for field, key in (("prompt_tokens", "llm_prompt_tokens"),
                           ("completion_tokens", "llm_completion_tokens")):
            vals = [q.get(field) for q in llm if q.get(field)]
            if vals:
                out[key] = float(max(vals))
    if llm:
        # SUMMED, not maxed. The retry fires on one answer today; the thing
        # worth catching is a second answer starting to retry, and a maximum
        # would stay at 2 while that happened.
        calls = [q.get("model_calls") for q in llm if q.get("model_calls")]
        if calls:
            out["llm_model_calls"] = float(sum(calls))
    if qs:
        out["total_best_ms"] = sum(q["best_ms"] for q in qs)
    # A truncated answer is a correctness problem wearing a latency costume:
    # it is fast because it stopped early. Surfaced here because timings.py is
    # the only thing that sees finish_reason.
    if any(q.get("finish_reason") == "length" for q in qs):
        print("  WARNING: an answer hit max_tokens - it is short, not fast")
    return out


def cmd_fast(args: argparse.Namespace) -> int:
    problems = integrity()
    if problems:
        print("THE MEASURE HAS CHANGED - refusing to report a score:")
        for p in problems:
            print("  " + p)
        print("\nA number from an edited scorer is not comparable to the "
              "baseline.\nRevert the file, or relock deliberately if the change "
              "to the measure\nis the point.")
        return 2
    ensure_db()
    out = ROOT / "run/evals/.fast.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    rc = subprocess.run([sys.executable, "scripts/evaluate.py",
                         "--json", str(out)], cwd=ROOT, timeout=3600).returncode
    if not out.exists():
        print(f"evaluate.py wrote no json (rc={rc})")
        return 2
    got = (json.loads(out.read_text()) or {}).get("scores", {})
    base = baseline()
    regressions, lines = compare("fast", got, base.get("fast", {}))
    _verdict("MODEL-FREE SUBSET", regressions, lines)
    print(f"\n  baseline taken {base.get('recorded_at', '?')} at "
          f"{str(base.get('commit', '?'))[:12]}")
    print("  this is the fast signal, not the verdict. The full suite needs the "
          "NIMs:\n    agent_loop.py gate   (on the GPU box)")
    if rc != 0:
        print(f"\n  note: evaluate.py itself exited {rc} - it has its own "
              f"floors, and one of them was missed")
    return 1 if (regressions or rc != 0) else 0


def cmd_gate(args: argparse.Namespace) -> int:
    problems = integrity()
    if problems:
        print("THE MEASURE HAS CHANGED - refusing to gate:")
        for p in problems:
            print("  " + p)
        return 2
    ensure_db()
    before = newest_run()
    cmd = [sys.executable, "scripts/eval_standard.py"]
    if args.no_build:
        cmd.append("--no-build")
    rc = subprocess.run(cmd, cwd=ROOT, timeout=7200).returncode
    row = newest_run()
    if row is None or (before is not None and row.get("at") == before.get("at")):
        print("\nthe suite recorded no new run - nothing to gate")
        return 2
    base = baseline()
    regressions, lines = compare("full", row.get("scores", {}),
                                 base.get("full", {}))
    _verdict("FULL SUITE", regressions, lines)
    perf_regressions: list[str] = []
    if not args.no_perf:
        print()
        got_perf = run_perf(args.repeat)
        if not got_perf:
            perf_regressions.append("timings.py produced no profile")
        else:
            perf_regressions, perf_lines = compare("perf", got_perf,
                                                   baseline().get("perf", {}))
            _verdict("LATENCY", perf_regressions, perf_lines)
    regressions += perf_regressions

    cc = row.get("cross_check")
    print(f"\n  cross-check: {cc}")
    print(f"  suite exit:  {rc}")
    if rc == 0 and not regressions and cc == "agree":
        print("\n  ACCEPTABLE. To make this the new baseline:\n"
              "    agent_loop.py accept")
        return 0
    print("\n  NOT ACCEPTABLE. The suite's own verdict, the cross-check and the "
          "baseline\n  comparison all have to pass; this run failed at least one.")
    return 1


def cmd_accept(args: argparse.Namespace) -> int:
    problems = integrity()
    if problems:
        print("the measure has changed - relock before accepting:")
        for p in problems:
            print("  " + p)
        return 2
    row = newest_run()
    if row is None:
        print("no recorded run to accept")
        return 2
    if row.get("cross_check") != "agree" and not args.force:
        print(f"the newest run's cross-check is {row.get('cross_check')!r}, not "
              f"'agree'.\nA baseline taken from a run whose two implementations "
              f"disagree is a\nbaseline nobody can trust. Fix it, or --force.")
        return 2
    print("taking the model-free subset for the fast baseline:", flush=True)
    ensure_db()
    out = ROOT / "run/evals/.fast.json"
    if out.exists():
        out.unlink()
    subprocess.run([sys.executable, "scripts/evaluate.py", "--json", str(out)],
                   cwd=ROOT, timeout=3600)
    fast = (json.loads(out.read_text()) or {}).get("scores", {}) \
        if out.exists() else {}
    perf = {} if args.no_perf else run_perf(args.repeat)
    BASELINE.write_text(json.dumps({
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "commit": git("rev-parse", "HEAD"),
        "from_run": row.get("at"),
        "results_dir": row.get("results_dir"),
        "full": {k: v for k, v in (row.get("scores") or {}).items()
                 if v is not None},
        "fast": fast,
        "perf": perf,
    }, indent=2, sort_keys=True) + "\n")
    print(f"\n  wrote {BASELINE.relative_to(ROOT)}  "
          f"({len(row.get('scores') or {})} full, {len(fast)} fast, "
          f"{len(perf)} perf)")
    return 0


def cmd_relock(args: argparse.Namespace) -> int:
    if not args.i_am_changing_the_measure:
        print("relock rewrites what counts as a valid measure. It is not part "
              "of the\nloop - it is the thing the loop is protected against. "
              "If you mean it:\n"
              "  agent_loop.py relock --i-am-changing-the-measure")
        return 2
    cur, missing = harness_digests()
    if missing:
        print("refusing to lock an incomplete measure:")
        for m in missing:
            print("  " + m)
        return 2
    old = (json.loads(LOCK.read_text()) or {}).get("files", {}) \
        if LOCK.exists() else {}
    LOCK.write_text(json.dumps({
        "locked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "commit": git("rev-parse", "HEAD"),
        "files": cur,
    }, indent=2, sort_keys=True) + "\n")
    changed = [r for r in cur if old.get(r) and old[r] != cur[r]]
    print(f"locked {len(cur)} files in {LOCK.relative_to(ROOT)}")
    for r in changed:
        print(f"  changed: {r}")
    if changed or not old:
        print("\nThe baseline was measured with the OLD scorer, so it no longer "
              "compares.\nRun the full suite and `accept` before trusting a "
              "delta again.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    problems = integrity()
    print("MEASURE")
    if problems:
        for p in problems:
            print("  " + p)
    else:
        lk = json.loads(LOCK.read_text())
        print(f"  intact - {len(lk.get('files', {}))} files, locked "
              f"{lk.get('locked_at')} at {str(lk.get('commit', ''))[:12]}")
    print("\nBASELINE")
    if not BASELINE.exists():
        print("  none yet - run the full suite, then `accept`")
        return 0 if not problems else 2
    b = baseline()
    print(f"  taken {b.get('recorded_at')} at {str(b.get('commit', ''))[:12]} "
          f"from run {b.get('from_run')}")
    for kind in ("fast", "full", "perf"):
        blk = b.get(kind) or {}
        if blk:
            print(f"\n  {kind} ({len(blk)} metrics)")
            for k in sorted(blk):
                print(f"    {k:24s} {_fmt(kind, k, blk[k])}")
    print(f"\nDATA\n  {'present' if DB.exists() else 'absent - will be generated'}"
          f"  {DB.relative_to(ROOT)}")
    return 0 if not problems else 2


def main() -> int:
    ap = argparse.ArgumentParser(
        description="the sandbox proposes, the GPU box decides")
    sub = ap.add_subparsers(dest="verb", required=True)
    f = sub.add_parser("fast", help="model-free subset vs baseline (sandbox)")
    f.set_defaults(fn=cmd_fast)
    g = sub.add_parser("gate", help="full suite vs baseline (GPU box)")
    g.add_argument("--no-build", action="store_true",
                   help="score the existing answers instead of regenerating")
    g.add_argument("--no-perf", action="store_true",
                   help="skip the latency profile (correctness only)")
    g.add_argument("--repeat", type=int, default=3,
                   help="timing runs per question")
    g.set_defaults(fn=cmd_gate)
    a = sub.add_parser("accept", help="adopt the latest run as the baseline")
    a.add_argument("--force", action="store_true",
                   help="accept even if the cross-check disagreed")
    a.add_argument("--no-perf", action="store_true",
                   help="do not record a latency baseline")
    a.add_argument("--repeat", type=int, default=3,
                   help="timing runs per question")
    a.set_defaults(fn=cmd_accept)
    r = sub.add_parser("relock", help="re-lock after changing the measure")
    r.add_argument("--i-am-changing-the-measure", action="store_true")
    r.set_defaults(fn=cmd_relock)
    s = sub.add_parser("status", help="baseline and lock state")
    s.set_defaults(fn=cmd_status)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
