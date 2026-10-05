#!/usr/bin/env python3
"""Does a real answer leave a usable trace?

    .venv/bin/python scripts/test_trace.py

Asserts what a flywheel needs, and one thing it must NOT do:

  a deterministic question  -> TOOL spans, and no LLM span at all
  a narrated question       -> both
  every start has an end    -> counts and names agree per category
  the traced tool names     -> are the tools the answer actually recorded using
  ASOIA_TRACE unset         -> nothing is written, in a separate process

That last one matters as much as the rest. Tracing that cannot be turned off is a
liability, and a default that writes to disk on every answer is one too.

The deterministic case is the interesting half. Five of this project's six question
classes make no model call, so a trace that shows an LLM span there would mean the
agent had quietly started asking a model to do arithmetic Python was doing.
"""
from __future__ import annotations
import json
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

DETERMINISTIC = "which repair orders are blocked"
NARRATED = "has anyone seen a whistling noise on a Passat"

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'FAILED '} {name}" + (f"  ({detail})" if detail else ""))


def read(p: str) -> list[dict]:
    out = []
    f = pathlib.Path(p)
    if not f.exists():
        return out
    for line in f.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def spans(recs, category):
    starts = [r for r in recs if r.get("category") == category
              and r.get("scope_category") == "start"]
    ends = [r for r in recs if r.get("category") == category
            and r.get("scope_category") == "end"]
    return starts, ends


def main() -> int:
    d = tempfile.mkdtemp(prefix="asoia-trace-")
    os.environ["ASOIA_TRACE"] = "file"
    os.environ["ASOIA_TRACE_DIR"] = d

    from app.obs import trace
    from app.agent.agent import ask

    print("tracing:", trace.mode(), "->", d)

    print("\na deterministic question (no model call expected):")
    a1 = ask(DETERMINISTIC)
    trace.flush()
    p = trace.path()
    chk("a trace file was created", bool(p) and pathlib.Path(p).exists(), str(p))
    if not p or not pathlib.Path(p).exists():
        print("\nnothing to check against. Is nemo-relay installed?",
              trace.why_off() or "")
        return 1
    recs = read(p)
    ts, te = spans(recs, "tool")
    ls, le = spans(recs, "llm")
    chk("tool spans were recorded", len(ts) > 0, f"{len(ts)} start(s)")
    chk("every tool start has an end", len(ts) == len(te), f"{len(ts)} vs {len(te)}")
    chk("no model was called on this path", len(ls) == 0,
        f"{len(ls)} llm span(s); composed={getattr(a1, 'composed', '?')}")
    # The trace must agree with what the answer itself says it did. If these drift,
    # the trace is describing a different execution from the one that answered.
    traced = sorted({r.get("name") for r in ts})
    claimed = sorted({c.get("name") for c in (a1.tool_calls or []) if c.get("name")})
    chk("traced tools match the answer's own tool_calls",
        traced == claimed, f"traced={traced} claimed={claimed}")

    print("\na narrated question (the model composes):")
    before = len(recs)
    a2 = ask(NARRATED)
    trace.flush()
    recs2 = read(p)
    chk("more spans were appended", len(recs2) > before, f"{before} -> {len(recs2)}")
    ls2, le2 = spans(recs2, "llm")
    if getattr(a2, "composed", "") == "python":
        print("         note: this answer fell back to Python composition, so no")
        print("         LLM span is expected. The NIMs are probably down.")
    else:
        chk("an llm span was recorded", len(ls2) > 0, f"{len(ls2)}")
        chk("every llm start has an end", len(ls2) == len(le2), f"{len(ls2)} vs {len(le2)}")
        models = sorted({r.get("name") for r in ls2})
        chk("the llm span is named", all(models), str(models))

    print("\nthe payload is actually in there, not just the shape:")
    any_args = [r for r in ts if r.get("data")]
    chk("tool starts carry their arguments", len(any_args) > 0,
        str(any_args[0].get("data"))[:70] if any_args else "none")
    any_res = [r for r in te if r.get("data") is not None]
    chk("tool ends carry a result", len(any_res) > 0,
        str(any_res[0].get("data"))[:70] if any_res else "none")
    chk("records are ATOF", all(r.get("atof_version") for r in recs2))

    print("\nand with ASOIA_TRACE unset, in a clean process:")
    d2 = tempfile.mkdtemp(prefix="asoia-notrace-")
    env = {k: v for k, v in os.environ.items() if k != "ASOIA_TRACE"}
    env["ASOIA_TRACE_DIR"] = d2
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "from app.agent.agent import ask;"
         "a = ask('which repair orders are blocked');"
         "print('answered', bool(a.text))"],
        capture_output=True, text=True, timeout=600, env=env)
    wrote = sorted(x.name for x in pathlib.Path(d2).iterdir())
    chk("the answer still worked", r.returncode == 0,
        (r.stdout or r.stderr or "")[-120:].replace("\n", " "))
    chk("nothing was written", wrote == [], str(wrote))

    print()
    if bad:
        print(f"{bad} assertion(s) FAILED.")
    else:
        print("The trace describes the execution that produced the answer.")
    print("\n  trace: " + str(p))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
