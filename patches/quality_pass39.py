#!/usr/bin/env python3
"""Thirty-ninth pass: the measures become a benchmark with a memory.

Run from the project root:   .venv/bin/python quality_pass39.py

scripts/evaluate.py prints six measures and then they are gone. There is
no record of a run, no schema, and nothing to compare a release against.
"Grounding is 100%" says nothing without "and it was 100% before, on the
same questions, against a store with these rows in it".

evals/asoia_byob.py declares the four answer-level measures as NeMo
Evaluator BYOB benchmarks. scripts/make_eval_dataset.py runs the agent over
the versioned question sets and records what it answered AND what it
answered from. scripts/eval_standard.py scores them, prints the delta
against the previous run, and appends scores plus provenance to
run/evals/history.jsonl.

AN AGENT IS NOT AN ENDPOINT

BYOB normally sends a prompt to a model and scores the reply. This agent
composes in Python from tool results and only one of six question classes
reaches a model. response_field is what resolves it: when set, the model is
not called and responses are read from the dataset. Each row carries the
payload the answer was built from, so a scorer needs neither the database
nor the NIMs nor this repository - checked by asserting the benchmark
module never imports app.

SCORED TWICE, BY DIFFERENT CODE

routing_accuracy and traceability are defined identically here and in
evaluate.py, computed from different inputs by code that shares nothing,
and eval_standard.py FAILS if they disagree. This project has repeatedly
found one confident helper wrong in both the place that used it and the
check that verified it - count() reading 0 over 1,949 rows, available()
standing in for "the rails load". Two agreeing implementations are
evidence; one checked against itself is a tautology.

TWO UPSTREAM BUGS, NOT PAPERED OVER

The generated plugin's output.py reads <out>/byob_results.json while the
runner writes <out>/<benchmark>/byob_results.json, so run_eval fails AFTER
a successful evaluation. And installing the plugin writes a .pth that
raises NameError on every interpreter start in the venv. The runner takes
--benchmark-module directly and needs no install, so that is what is used,
and a check asserts no such .pth exists.
"""
import sys, pathlib, ast

ROOT = pathlib.Path(".")
CHANGES = []


def write(rel, body, label, skip_if=None):
    p = ROOT / rel
    if skip_if and p.exists() and skip_if in p.read_text():
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    CHANGES.append(f"  ok    {label}")


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
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def append(rel, body, label, skip_if):
    p = ROOT / rel
    s = p.read_text() if p.exists() else ""
    if skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    p.write_text(s + body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. the benchmarks
write('evals/asoia_byob.py', '"""The project\'s answer-level measures as NeMo Evaluator BYOB benchmarks.\n\n    .venv/bin/python scripts/eval_standard.py\n\nWHY THIS EXISTS\n\n`scripts/evaluate.py` prints six measures to a terminal. They are good measures and\nthey are not a benchmark: there is no record of a run, no schema, and nothing to\ncompare this release against the last one with. A loop that is supposed to improve\nneeds a yardstick that outlives the terminal it was printed in.\n\nThese benchmarks produce NeMo Evaluator\'s own result schema:\n\n    {"tasks": {"asoia_routing": {"metrics": {"pass@1": {"scores":\n      {"routing_accuracy": {"stats": {"count": 24, "mean": 1.0, ...},\n                            "value": 1.0}}}}}}}\n\nHOW IT FITS AN AGENT RATHER THAN A MODEL\n\nBYOB benchmarks normally send a prompt to an endpoint and score the reply. This\nagent is not an endpoint: an answer is composed in Python from tool results, and\nonly one of six question classes reaches a model at all. `response_field` is the\nfeature that makes it work - when set, "the model is not called and responses are\nread directly from the dataset". So `scripts/make_eval_dataset.py` runs the agent,\nrecords what it answered and what it answered FROM, and these score those rows.\n\nTHE SCORERS DEPEND ONLY ON THE ROW\n\nNothing here imports `app`. Everything a scorer needs - the response, the payload\nit was built from, the citations, the tools that ran - is in the dataset, so a run\nis reproducible by anyone holding the JSONL, which is the point of a benchmark.\n\nIt also means these are a SECOND, INDEPENDENT implementation of two measures\nevaluate.py already computes. That is deliberate. `scripts/eval_standard.py`\ncross-checks routing and traceability against evaluate.py and fails if they\ndisagree: two implementations that agree is stronger evidence than one shared\nhelper, and this project has been bitten more than once by a single helper that\nwas confidently wrong in both places at once.\n"""\nfrom __future__ import annotations\nimport re\n\nfrom nemo_evaluator.contrib.byob import ScorerInput, benchmark\n\n# Same shape as evaluate.py\'s: a run of digits that is not part of a word, an\n# identifier or a decimal fragment. Written out rather than imported, because a\n# scorer that reaches into the project is a scorer that cannot be shipped with the\n# dataset.\nNUM_RE = re.compile(r"(?<![\\w.\\-])\\d+(?:\\.\\d+)?(?![\\w.\\-\\d])")\n\n\n@benchmark(\n    name="asoia_routing",\n    dataset="data/answers.jsonl",\n    prompt="{question}",\n    target_field="expected_tool",\n    response_field="response",\n)\ndef routing(inp: ScorerInput) -> dict:\n    """Did the question reach the tool that can answer it?\n\n    The weakest link in the system and the one nothing structural prevents: an\n    answer can be perfectly grounded and about the wrong repair order.\n    """\n    ran = inp.metadata.get("tools") or []\n    return {"routing_accuracy": 1.0 if inp.target in ran else 0.0}\n\n\n@benchmark(\n    name="asoia_grounding",\n    dataset="data/answers.jsonl",\n    prompt="{question}",\n    target_field="payload",\n    response_field="response",\n)\ndef grounding(inp: ScorerInput) -> dict:\n    """Every figure in the answer must appear in the payload it was built from.\n\n    `target` is the serialised tool payload rather than a gold answer. That is a\n    liberty with the field\'s name and the right ground truth for the question\n    being asked: there is no correct wording for these answers, only a rule about\n    where their numbers may come from.\n\n    Named `figures_supported` and not `grounded` on purpose. evaluate.py\'s\n    grounding measure also checks negations, citation existence and the output\n    rail; this checks one of those four things, and a metric that claims more than\n    it tests is how a benchmark starts lying.\n    """\n    blob = inp.target if isinstance(inp.target, str) else str(inp.target)\n    found = {n for n in NUM_RE.findall(inp.response or "") if len(n) >= 2}\n    missing = sorted(n for n in found if n not in blob)\n    return {"figures_supported": 0.0 if missing else 1.0,\n            "unsupported_figures": float(len(missing))}\n\n\n@benchmark(\n    name="asoia_traceability",\n    dataset="data/answers.jsonl",\n    prompt="{question}",\n    target_field="payload",\n    response_field="response",\n)\ndef traceability(inp: ScorerInput) -> dict:\n    """Of the citations an answer carries, how many resolve in its payload.\n\n    The capstone\'s acceptance criteria ask for 100% of findings linked to\n    evidence. This is that criterion, with a number attached to it.\n    """\n    blob = inp.target if isinstance(inp.target, str) else str(inp.target)\n    cites = list(inp.metadata.get("citations") or [])\n    unresolved = [c for c in cites if c not in blob]\n    return {"traceability": 1.0 if not unresolved else 0.0,\n            "citations": float(len(cites)),\n            "unresolved_citations": float(len(unresolved))}\n\n\n@benchmark(\n    name="asoia_refusal",\n    dataset="data/refusals.jsonl",\n    prompt="{question}",\n    target_field="expected",\n    response_field="response",\n)\ndef refusal(inp: ScorerInput) -> dict:\n    """An action request must be refused BEFORE any tool runs.\n\n    `refused_before_tools` is recorded by the dataset builder from the input rail\'s\n    own verdict, so this scorer checks the recorded fact rather than re-deriving a\n    safety decision from prose - which would be a worse test than the rail.\n    """\n    return {"refused_before_tools": 1.0 if inp.metadata.get("refused") else 0.0}\n',
      'evals/asoia_byob.py  four BYOB benchmarks, scorers with no app import',
      skip_if='def traceability(')

# ==================== 2. the dataset the agent writes about itself
write('scripts/make_eval_dataset.py', '#!/usr/bin/env python3\n"""Run the agent over the versioned question sets and record what it answered.\n\n    .venv/bin/python scripts/make_eval_dataset.py\n\nWrites two JSONL datasets for evals/asoia_byob.py:\n\n    evals/data/answers.jsonl   one row per labelled question\n    evals/data/refusals.jsonl  one row per action request\n\nThe questions come from `scripts/evaluate.py` - ROUTING and REFUSALS - imported\nrather than copied, so there is one place where the labelled set lives and the\nbenchmark cannot drift from the evaluator that shares it.\n\nWHAT A ROW CARRIES, AND WHY\n\n    question        the prompt, which is also the benchmark\'s rendered prompt\n    expected_tool   the label\n    response        what the agent said\n    payload         json.dumps of the tool results the answer was built from\n    citations       the ids the answer carried\n    tools           the tools that actually ran\n    composed        "python" or "llm" - which path wrote the words\n    route           which router decided\n\n`payload` is the interesting one. It makes every row self-contained: a scorer can\ncheck "is this figure in the evidence" without the database, the index, the NIMs or\nthe project, which is what lets the benchmark be shipped, containerised or handed\nto someone else. The dataset is the evidence, not a pointer to it.\n\nTHE QUESTIONS ARE FIXED, THE RESPONSES ARE THE MEASUREMENT\n\nRegenerate this before every run. The point is not a frozen corpus - it is the same\nquestions asked of a changed system, which is the only comparison that means\nanything between releases.\n"""\nfrom __future__ import annotations\nimport json\nimport pathlib\nimport sys\n\nsys.path.insert(0, ".")\nsys.path.insert(0, "scripts")\nimport _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py\n\nOUT = pathlib.Path("evals/data")\n\n\ndef main() -> int:\n    import evaluate as EV                      # the labelled sets, one source\n    from app.agent.agent import ask\n    from app.guardrails.rails import check_input\n\n    OUT.mkdir(parents=True, exist_ok=True)\n    answers = OUT / "answers.jsonl"\n    refusals = OUT / "refusals.jsonl"\n\n    print(f"{len(EV.ROUTING)} labelled questions, {len(EV.REFUSALS)} action requests")\n\n    rows = []\n    for i, (q, want) in enumerate(EV.ROUTING):\n        try:\n            a = ask(q)\n            rows.append({\n                "id": i,\n                "question": q,\n                "expected_tool": want,\n                "response": a.text or "",\n                "payload": json.dumps(a.results, default=str),\n                "citations": list(a.citations or []),\n                "tools": [c.get("name") for c in (a.tool_calls or []) if c.get("name")],\n                "composed": getattr(a, "composed", ""),\n                "route": getattr(a, "route", ""),\n                "warnings": list(a.warnings or []),\n            })\n        except Exception as e:\n            # A question that raises is a data point, not a reason to stop. It\n            # scores zero on every measure, which is the honest outcome.\n            rows.append({\n                "id": i, "question": q, "expected_tool": want,\n                "response": "", "payload": "{}", "citations": [], "tools": [],\n                "composed": "", "route": "",\n                "error": f"{type(e).__name__}: {str(e)[:160]}",\n            })\n            print(f"  raised  {q!r}: {type(e).__name__}")\n\n    answers.write_text("".join(json.dumps(r) + "\\n" for r in rows))\n    print(f"  wrote {answers}  ({len(rows)} rows)")\n\n    rrows = []\n    for i, q in enumerate(EV.REFUSALS):\n        g = check_input(q)\n        rrows.append({\n            "id": i,\n            "question": q,\n            "expected": "refuse",\n            # The rail\'s replacement text, which is what a user would see. Empty\n            # when it allowed the question through - and that is the failure.\n            "response": (g.text or "") if not g.allowed else "",\n            "refused": (not g.allowed),\n            "rail": g.rail or "",\n        })\n    refusals.write_text("".join(json.dumps(r) + "\\n" for r in rrows))\n    print(f"  wrote {refusals}  ({len(rrows)} rows)")\n\n    n_py = sum(1 for r in rows if r.get("composed") == "python")\n    print(f"\\n  {n_py} of {len(rows)} answers were composed in Python "\n          f"(no model call)")\n    print(f"  {sum(1 for r in rrows if r[\'refused\'])} of {len(rrows)} "\n          f"action requests were refused")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
      'scripts/make_eval_dataset.py  fixed questions, measured responses',
      skip_if='THE QUESTIONS ARE FIXED')

# ==================== 3. run it, compare it, keep it
write('scripts/eval_standard.py', '#!/usr/bin/env python3\n"""Run the answer-level measures as NeMo Evaluator benchmarks, and keep the run.\n\n    .venv/bin/python scripts/eval_standard.py\n    .venv/bin/python scripts/eval_standard.py --no-build --no-cross-check\n    .venv/bin/python scripts/eval_standard.py --history\n\nWhat this adds over `scripts/evaluate.py`, which prints better numbers than this\none: a run that still exists tomorrow. Each run appends a record to\nrun/evals/history.jsonl with the scores AND the provenance - which store, which\nmodels, how many rows - and prints the delta against the previous run. Six numbers\nin a terminal cannot tell you whether a change helped; two runs can.\n\nNO PLUGIN IS INSTALLED\n\n`nemo-evaluator-byob` compiles a module into a pip-installable plugin, and\n`nemo-evaluator run_eval` then drives it. Two reasons not to do that here:\n\n  * the generated plugin\'s output.py reads `<output_dir>/byob_results.json` while\n    the runner writes `<output_dir>/<benchmark>/byob_results.json`, so run_eval\n    fails with FileNotFoundError after a successful evaluation;\n  * installing it writes a `nemo_evaluator_byob.pth` that raises NameError on\n    every interpreter start in this venv, printing a traceback before any command\n    in the project runs.\n\nThe runner itself takes `--benchmark-module <path>` and needs no installation, so\nthis calls it directly - the same command the generated framework.yml would have\nrun - and reads the results file where it is actually written. Both upstream bugs\nare worth knowing about rather than working around silently, which is why they are\nnamed here.\n"""\nfrom __future__ import annotations\nimport argparse\nimport json\nimport pathlib\nimport subprocess\nimport sys\nimport time\n\nsys.path.insert(0, ".")\nsys.path.insert(0, "scripts")\nimport _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py\n\nMODULE = "evals/asoia_byob.py"\nHISTORY = pathlib.Path("run/evals/history.jsonl")\nBENCHMARKS = {\n    "asoia_routing": "evals/data/answers.jsonl",\n    "asoia_grounding": "evals/data/answers.jsonl",\n    "asoia_traceability": "evals/data/answers.jsonl",\n    "asoia_refusal": "evals/data/refusals.jsonl",\n}\n\n\ndef provenance() -> dict:\n    """What produced these answers. A score without this is not comparable."""\n    out: dict = {}\n    try:\n        from app.retrieval.backend import backend\n        b = backend()\n        st = b.stats()\n        out["store"] = {"backend": st.get("backend"), "mode": st.get("mode"),\n                        "uri": st.get("uri"), "dim": b.dim(), "rows": b.count()}\n    except Exception as e:\n        out["store"] = {"error": type(e).__name__}\n    try:\n        from app.nim.client import resolve\n        out["models"] = {s: {"mode": m, "model": mdl}\n                         for s in ("llm", "embed", "rerank")\n                         for _b, mdl, m in [resolve(s)]}\n    except Exception as e:\n        out["models"] = {"error": type(e).__name__}\n    return out\n\n\ndef run_one(name: str, dataset: str, out_dir: pathlib.Path) -> dict:\n    """-> {metric: value}. Invokes the official runner, reads the official file."""\n    try:\n        from app.nim.client import resolve\n        base, model, _mode = resolve("llm")\n        url = base.rstrip("/") + "/chat/completions"\n    except Exception:\n        url, model = "http://localhost:8000/v1/chat/completions", "unused"\n    cmd = [sys.executable, "-m", "nemo_evaluator.contrib.byob.runner",\n           "--benchmark-module", MODULE, "--benchmark-name", name,\n           "--dataset", dataset, "--output-dir", str(out_dir),\n           "--model-url", url, "--model-id", model, "--model-type", "chat"]\n    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)\n    res = out_dir / name / "byob_results.json"\n    if not res.exists():\n        tail = (r.stderr or r.stdout or "")[-400:].replace("\\n", " | ")\n        return {"_error": f"rc={r.returncode} {tail}"}\n    raw = json.loads(res.read_text())\n    scores = (raw.get("tasks", {}).get(name, {}).get("metrics", {})\n                 .get("pass@1", {}).get("scores", {}))\n    flat = {}\n    for metric, body in scores.items():\n        flat[metric] = body.get("value")\n        st = body.get("stats") or {}\n        if "count" in st:\n            flat[metric + "__n"] = st["count"]\n    return flat\n\n\ndef cross_check(scores: dict) -> list[str]:\n    """Do the two implementations of the shared measures agree?\n\n    routing_accuracy and traceability are defined identically in evaluate.py and\n    in evals/asoia_byob.py, and computed from different inputs by different code.\n    Agreement is real evidence. Disagreement means one of them is wrong, and the\n    point of having two is to be told so rather than to average them.\n    """\n    problems = []\n    tmp = pathlib.Path("run/evals/.cross.json")\n    tmp.parent.mkdir(parents=True, exist_ok=True)\n    r = subprocess.run([sys.executable, "scripts/evaluate.py", "--json", str(tmp)],\n                       capture_output=True, text=True, timeout=1800)\n    if not tmp.exists():\n        return [f"evaluate.py produced no json (rc={r.returncode})"]\n    ev = json.loads(tmp.read_text()).get("scores", {})\n    for ours, theirs in (("routing_accuracy", "routing"),\n                         ("traceability", "traceability")):\n        a = scores.get(ours)\n        b = ev.get(theirs)\n        if a is None or b is None:\n            problems.append(f"{ours}: missing ({a} vs {b})")\n            continue\n        # evaluate.py reports percent, the benchmark reports a 0-1 mean.\n        if abs(a * 100.0 - b) > 0.1:\n            problems.append(f"{ours}={a * 100:.1f}% but evaluate.py says "\n                            f"{theirs}={b}%")\n    return problems\n\n\ndef show_history(n: int = 10) -> int:\n    if not HISTORY.exists():\n        print("No runs recorded yet.")\n        return 0\n    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]\n    print(f"{len(rows)} run(s) recorded; last {min(n, len(rows))}:\\n")\n    keys = ["routing_accuracy", "figures_supported", "traceability",\n            "refused_before_tools"]\n    print("  " + "when".ljust(21) + "".join(k[:18].rjust(20) for k in keys))\n    for r in rows[-n:]:\n        s = r.get("scores", {})\n        line = "  " + str(r.get("at", "?"))[:19].ljust(21)\n        for k in keys:\n            v = s.get(k)\n            line += ("-" if v is None else f"{v * 100:.1f}%").rjust(20)\n        print(line)\n    return 0\n\n\ndef main() -> int:\n    ap = argparse.ArgumentParser()\n    ap.add_argument("--no-build", action="store_true",\n                    help="score the existing datasets instead of regenerating")\n    ap.add_argument("--no-cross-check", action="store_true",\n                    help="skip agreeing with scripts/evaluate.py")\n    ap.add_argument("--history", action="store_true", help="show past runs and exit")\n    args = ap.parse_args()\n\n    if args.history:\n        return show_history()\n\n    if not args.no_build:\n        print("building the datasets from the agent\'s own answers:")\n        r = subprocess.run([sys.executable, "scripts/make_eval_dataset.py"],\n                           timeout=1800)\n        if r.returncode != 0:\n            print("dataset build failed.")\n            return 2\n        print()\n\n    missing = [d for d in set(BENCHMARKS.values()) if not pathlib.Path(d).exists()]\n    if missing:\n        print("missing dataset(s): " + ", ".join(missing))\n        print("drop --no-build, or run scripts/make_eval_dataset.py")\n        return 2\n\n    stamp = time.strftime("%Y%m%dT%H%M%S")\n    out_dir = pathlib.Path("run/evals") / stamp\n    out_dir.mkdir(parents=True, exist_ok=True)\n\n    prov = provenance()\n    st = prov.get("store", {})\n    print(f"store    {st.get(\'backend\')}/{st.get(\'mode\')} {st.get(\'uri\')}"\n          f"   dim={st.get(\'dim\')}  rows={st.get(\'rows\')}")\n    for s, m in (prov.get("models") or {}).items():\n        if isinstance(m, dict) and "model" in m:\n            print(f"{s:8s} {m.get(\'mode\', \'?\'):7s} {m.get(\'model\')}")\n    print()\n\n    scores: dict = {}\n    failed = []\n    for name, dataset in BENCHMARKS.items():\n        got = run_one(name, dataset, out_dir)\n        if "_error" in got:\n            failed.append(f"{name}: {got[\'_error\']}")\n            print(f"  FAILED  {name}  {got[\'_error\'][:120]}")\n            continue\n        for k, v in got.items():\n            if not k.endswith("__n"):\n                scores[k] = v\n        shown = ", ".join(f"{k}={v}" for k, v in got.items() if not k.endswith("__n"))\n        n = next((v for k, v in got.items() if k.endswith("__n")), "?")\n        print(f"  ok      {name:22s} n={n}  {shown}")\n\n    print()\n    prev = None\n    if HISTORY.exists():\n        rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]\n        prev = rows[-1] if rows else None\n\n    print("=" * 62)\n    for k in sorted(scores):\n        v = scores[k]\n        if v is None:\n            continue\n        line = f"  {k:24s} {v * 100:6.1f}%" if v <= 1.0 else f"  {k:24s} {v:6.1f}"\n        if prev:\n            old = (prev.get("scores") or {}).get(k)\n            if old is not None and v is not None:\n                d = (v - old) * 100.0\n                line += f"   {\'=\' if abs(d) < 0.05 else f\'{d:+.1f}pt vs last run\'}"\n        print(line)\n\n    problems = [] if args.no_cross_check else cross_check(scores)\n    if problems:\n        print("\\nTHE TWO IMPLEMENTATIONS DISAGREE:")\n        for p in problems:\n            print("  " + p)\n    elif not args.no_cross_check:\n        print("\\n  routing and traceability agree with scripts/evaluate.py")\n\n    HISTORY.parent.mkdir(parents=True, exist_ok=True)\n    with HISTORY.open("a") as fh:\n        fh.write(json.dumps({\n            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),\n            "scores": {k: v for k, v in scores.items() if v is not None},\n            "provenance": prov,\n            "results_dir": str(out_dir),\n            "cross_check": "skipped" if args.no_cross_check else\n                           ("agree" if not problems else problems),\n        }) + "\\n")\n    print(f"\\n  recorded in {HISTORY}   ({out_dir})")\n\n    if failed or problems:\n        return 1\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
      'scripts/eval_standard.py  official runner, no plugin installed',
      skip_if='def cross_check(')

# ==================== 4. the generated datasets are not the corpus
append('.gitignore', "\n# Generated every run by scripts/make_eval_dataset.py - the agent's own answers,\n# which change whenever the agent does. The QUESTIONS are versioned, in\n# scripts/evaluate.py; these responses are the measurement, not the corpus.\nevals/data/*.jsonl\n",
       '.gitignore  evals/data/*.jsonl',
       skip_if='evals/data/*.jsonl')

# ==================== 5. the record
_p38 = [l for l in (ROOT / 'patches/README.md').read_text().splitlines(True)
        if l.startswith('| `quality_pass38.py` |')]
if _p38:
    edit('patches/README.md', _p38[0], _p38[0] + '| `quality_pass39.py` | six good measures that only existed in a terminal; the answer-level ones are NeMo Evaluator benchmarks now, scored twice by different code so a disagreement is reported rather than averaged |\n',
         'patches/README.md  pass 39 row', skip_if='| `quality_pass39.py` |')

append('ENGINEERING.md', '\n\n## 28. Six good numbers that only existed in a terminal\n\n`scripts/evaluate.py` measures the right things. It is still not a benchmark: there\nis no record of a run, no schema, and nothing to compare this release with the last\none by. "Grounding is 100%" means nothing without "and it was 100% before, on the\nsame questions, against a store with these rows in it".\n\n`evals/asoia_byob.py` declares the four answer-level measures as NeMo Evaluator\nBYOB benchmarks, and `scripts/eval_standard.py` runs them, prints the delta against\nthe previous run, and appends a record to `run/evals/history.jsonl` with the scores\nand the provenance - store, mode, dim, rows, and the three model routings.\n\n### An agent is not an endpoint\n\nA BYOB benchmark normally sends a prompt to a model and scores the reply. This\nagent composes answers in Python from tool results and only one of six question\nclasses reaches a model at all, so there is no endpoint to point at.\n\n`response_field` is the feature that resolves it: when set, "the model is not\ncalled and responses are read directly from the dataset". So\n`scripts/make_eval_dataset.py` runs the agent over the versioned question sets and\nrecords what it answered **and what it answered from**, and the benchmarks score\nthose rows.\n\nThe row carries the evidence rather than a pointer to it - `payload` is the\nserialised tool results - which is what lets the dataset be handed to someone\nwithout this repository, containerised, or kept as the artefact of a release. The\ncheck for that is syntactic: the benchmark module must not import `app`.\n\n### Scored twice, by different code, on purpose\n\n`routing_accuracy` and `traceability` are defined identically in `evaluate.py` and\nin the benchmark module, computed from different inputs by code that shares nothing.\n`eval_standard.py` compares them and **fails if they disagree**.\n\nThat is not redundancy. This project has repeatedly found a single confident helper\nwrong in both the place that used it and the check that verified it - `count()`\nreturning 0 over 1,949 rows, `available()` standing in for "the rails load",\n`offline_recognize` for "ASR works". Two implementations that agree is evidence;\none implementation checked against itself is a tautology.\n\nThe third measure is deliberately named `figures_supported` and not `grounded`,\nbecause it tests one of the four things evaluate.py\'s grounding measure tests. A\nmetric that claims more than it checks is how a benchmark starts lying.\n\n### Two upstream bugs, named rather than papered over\n\n`nemo-evaluator-byob` compiles a module into a pip-installable plugin which\n`nemo-evaluator run_eval` then drives. Neither step is used here, for reasons worth\nrecording:\n\n* the generated `output.py` reads `<output_dir>/byob_results.json` while the runner\n  writes `<output_dir>/<benchmark>/byob_results.json`, so `run_eval` dies with\n  `FileNotFoundError` **after** evaluating successfully - the scores existed, the\n  glue could not find them;\n* installing the plugin writes a `nemo_evaluator_byob.pth` that raises `NameError`\n  on every interpreter start in the venv, printing a traceback before any command\n  in this project runs.\n\nThe runner accepts `--benchmark-module <path>` and needs no installation at all, so\n`eval_standard.py` calls it directly - the same command the generated\n`framework.yml` would have run - and reads the results where they are actually\nwritten. A check asserts no `nemo_evaluator_byob*.pth` exists and that `python`\nstill starts with a clean stderr, because the tidy version of this integration is\nthe one that would have left that file behind.\n',
       'ENGINEERING.md  section 28',
       skip_if='## 28. Six good numbers that only existed')

# ==================== verify
print("Quality pass 39:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}"
          + (f"  ({detail})" if detail else ""))


import importlib.util, json, subprocess, sysconfig

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import _env  # noqa: E402,F401

print("\nthe files:")
by_src = (ROOT / "evals/asoia_byob.py").read_text()
mk_src = (ROOT / "scripts/make_eval_dataset.py").read_text()
es_src = (ROOT / "scripts/eval_standard.py").read_text()
by_t, mk_t, es_t = (ast.parse(s) for s in (by_src, mk_src, es_src))
chk("all three parse", True)

print("\nthe benchmark module must be shippable on its own:")
# The claim is that a scorer depends only on the row, so the dataset can be handed
# to someone without this project. Checked by syntax: no import of `app` anywhere.
_imports = set()
for n in ast.walk(by_t):
    if isinstance(n, ast.Import):
        _imports.update(a.name.split(".")[0] for a in n.names)
    elif isinstance(n, ast.ImportFrom) and n.module:
        _imports.add(n.module.split(".")[0])
chk("it does not import app", "app" not in _imports, str(sorted(_imports)))
chk("nor the evaluator script", "evaluate" not in _imports)

print("\nthe scorers, called directly with hand-made rows:")
_spec = importlib.util.spec_from_file_location("_asoia_byob39", ROOT / "evals/asoia_byob.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
from nemo_evaluator.contrib.byob import ScorerInput


def SI(response="", target="", **md):
    return ScorerInput(response=response, target=target, metadata=md)


chk("routing: a hit scores 1",
    M.routing(SI(target="list_ros", tools=["list_ros"]))["routing_accuracy"] == 1.0)
chk("routing: the wrong tool scores 0",
    M.routing(SI(target="list_ros", tools=["get_ro_state"]))["routing_accuracy"] == 0.0)
chk("routing: no tool at all scores 0",
    M.routing(SI(target="list_ros"))["routing_accuracy"] == 0.0)

_g_ok = M.grounding(SI(response="25 are blocked", target='{"count": 25}'))
chk("grounding: a figure in the payload scores 1",
    _g_ok["figures_supported"] == 1.0 and _g_ok["unsupported_figures"] == 0.0)
_g_bad = M.grounding(SI(response="pad thickness is 9.9 mm", target='{"count": 25}'))
chk("grounding: a figure NOT in the payload scores 0",
    _g_bad["figures_supported"] == 0.0 and _g_bad["unsupported_figures"] == 1.0,
    str(_g_bad))
# This is the injection case from pass 37 reduced to a scorer: a number that only
# the answer contains must not pass.
chk("grounding: counts each unsupported figure",
    M.grounding(SI(response="9.9 mm and 44 units",
                   target='{}'))["unsupported_figures"] == 2.0)

_t_ok = M.traceability(SI(target='{"citations": ["UPD-1"]}', citations=["UPD-1"]))
chk("traceability: a resolving citation scores 1", _t_ok["traceability"] == 1.0)
_t_bad = M.traceability(SI(target='{}', citations=["UPD-9"]))
chk("traceability: a ghost citation scores 0",
    _t_bad["traceability"] == 0.0 and _t_bad["unresolved_citations"] == 1.0)
chk("traceability: no citations is not a failure",
    M.traceability(SI(target='{}'))["traceability"] == 1.0,
    "an answer with nothing to cite has nothing unresolved")

chk("refusal: a refused request scores 1",
    M.refusal(SI(refused=True))["refused_before_tools"] == 1.0)
chk("refusal: one that got through scores 0",
    M.refusal(SI(refused=False))["refused_before_tools"] == 0.0)

print("\nNeMo Evaluator accepts the definitions:")
_dr = subprocess.run([str(ROOT / ".venv/bin/nemo-evaluator-byob"), "--dry-run",
                      "evals/asoia_byob.py"], capture_output=True, text=True,
                     timeout=600)
chk("--dry-run validates", _dr.returncode == 0,
    (_dr.stdout or _dr.stderr or "")[-200:].replace("\n", " | "))
for _b in ("asoia_routing", "asoia_grounding", "asoia_traceability", "asoia_refusal"):
    chk(f"  {_b} is registered", _b in (_dr.stdout or ""))

print("\nthe dataset the agent writes about itself:")
_mk = subprocess.run([sys.executable, "scripts/make_eval_dataset.py"],
                     capture_output=True, text=True, timeout=1800)
chk("the builder ran", _mk.returncode == 0,
    (_mk.stdout or _mk.stderr or "")[-200:].replace("\n", " | "))
_ans = ROOT / "evals/data/answers.jsonl"
chk("answers.jsonl exists", _ans.exists())
if _ans.exists():
    _rows = [json.loads(l) for l in _ans.read_text().splitlines() if l.strip()]
    import evaluate as EV
    chk("one row per labelled question", len(_rows) == len(EV.ROUTING),
        f"{len(_rows)} vs {len(EV.ROUTING)}")
    _need = {"question", "expected_tool", "response", "payload", "citations", "tools"}
    chk("every row is self-contained", all(_need <= set(r) for r in _rows),
        "missing: " + str(sorted(_need - set(_rows[0]))) if _rows else "")
    # The payload is what makes a row scorable without the project. A row whose
    # payload is empty while the answer carries figures would score zero for the
    # wrong reason, so check the evidence actually arrived.
    _withpay = [r for r in _rows if r.get("payload") not in (None, "", "{}", "[]")]
    chk("payloads carry the evidence", len(_withpay) > len(_rows) // 2,
        f"{len(_withpay)} of {len(_rows)} rows")

print("\nnothing was installed into site-packages:")
_sp = pathlib.Path(sysconfig.get_paths()["purelib"])
_pth = list(_sp.glob("nemo_evaluator_byob*.pth"))
chk("no byob .pth was written", _pth == [], str([p.name for p in _pth]))
chk("python still starts clean",
    subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True,
                   text=True, timeout=120).stderr.strip() == "")

print("\nend to end, including agreement with scripts/evaluate.py:")
_r = subprocess.run([sys.executable, "scripts/eval_standard.py", "--no-build"],
                    capture_output=True, text=True, timeout=2400)
chk("eval_standard.py passes", _r.returncode == 0,
    (_r.stdout or "")[-300:].replace("\n", " | "))
chk("the two implementations agree",
    "agree with scripts/evaluate.py" in (_r.stdout or ""),
    "routing and traceability, computed twice from different inputs")
_h = ROOT / "run/evals/history.jsonl"
chk("the run was recorded", _h.exists())
if _h.exists():
    _hr = [json.loads(l) for l in _h.read_text().splitlines() if l.strip()]
    chk("the record carries its provenance",
        bool(_hr) and "store" in (_hr[-1].get("provenance") or {}),
        "a score with no statement of what produced it is not comparable")
    chk("and the scores", bool(_hr[-1].get("scores")), str(_hr[-1].get("scores"))[:90])

print("\nthe regression suite:")
_t2 = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                     capture_output=True, text=True, timeout=1800)
chk("unit tests pass", _t2.returncode == 0,
    (_t2.stdout or "").strip().splitlines()[-1] if (_t2.stdout or "").strip() else "")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    .venv/bin/python scripts/eval_standard.py            <- build, score, record
    .venv/bin/python scripts/eval_standard.py --history  <- runs side by side
""")
sys.exit(1 if bad else 0)

