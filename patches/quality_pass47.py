#!/usr/bin/env python
"""Pass 47 - NeMo Curator, and the one thing it is worth running here for.

Row 3 of the architecture was the last component with no code at all. This
installs `scripts/curate.py`: a real Curator Pipeline of six stages over the
real 1,949-update corpus, with per-stage attribution measured by running the
stages one at a time rather than reporting a single total.

Two honest results come out of it.

The five heuristic stages remove NOTHING from this corpus, and that is the
correct answer rather than a failure: the data is generated, so it has no CRLF,
no stray URLs, no symbol soup and no one-word notes. They are kept because they
are the stages a real DMS export needs, and because a pipeline that has never
been run against anything is not evidence of anything.

The sixth stage is why Curator earns its place. `InstructionLikeFilter` drops
notes that address the model instead of the record - the injection vector that
scripts/test_injection.py exercises. The answer-side rail from pass 37 stops the
model ACTING on such a note; removing it before it is embedded means the
retriever can never surface it. Those are not alternatives, they are two layers.

Measured, by `scripts/curate.py --selftest`:

    the known payload is caught            4 markers, read from test_injection.py
    false positives across 1,949 notes     0
    ordinary workshop phrasing             not flagged

The payload is imported from scripts/test_injection.py rather than restated, so
the filter and the attack it defends against cannot drift apart. The markers are
narrow on purpose: "approved", "release" and "closed" are words a technician
writes, so they are not markers - dropping a real note is also a failure.

This pass also narrows scripts/openshell_gateway.py. Its `write` verb
hand-registers an OpenShell gateway, which is wrong for a Brev launchable:
canonical NemoClaw owns gateway registration there, and the launchable's own
instructions say not to register one directly. `check` and `show` remain useful.

Environment: curate.py runs under .venv-curator, never the serving venv.
nemo-curator's base dependencies are Ray, Torch and Transformers - 6.3 GB -
and the two environments share nothing but the repository.

Idempotent. Re-running changes nothing and says so.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not (ROOT / "scripts").is_dir():
    ROOT = ROOT.parent


def note(s: str) -> None:
    print("  " + s)


CURATE = '#!/usr/bin/env python\n"""Curate the technician update corpus with NeMo Curator.\n\n    .venv-curator/bin/python scripts/curate.py            # report only\n    .venv-curator/bin/python scripts/curate.py --write    # also write the output\n\nRuns in `.venv-curator`, never the serving venv. nemo-curator\'s base\ndependencies are Ray, Torch and Transformers - 6.3 GB - and putting that\nunderneath a live serving stack to tidy 1,949 short notes would be a bad trade.\nThe two environments share nothing but the repository.\n\nThis reads the corpus read-only and writes NOTHING to the system of record.\nCuration proposes; a separate, deliberate step would re-index. A script that\nsilently rewrote the store the agent is answering from would be the worst\npossible shape for this.\n\nScope, stated plainly rather than implied: the heuristic and modifier stages\nbelow are real Curator stages in a real Curator Pipeline, and the per-stage\nattribution is measured by running them one at a time. Curator\'s *deduplication*\nis a separate file-based workflow (`TextDuplicatesRemovalWorkflow`) that wants\nparquet round-trips and an identification pass to produce the ids to remove; for\na corpus this size the exact-duplicate set is computed directly here and\nreported instead. That is a deliberate scope choice, not an oversight.\n"""\nfrom __future__ import annotations\n\nimport argparse\nimport hashlib\nimport json\nimport re\nimport sqlite3\nimport sys\nimport time\nfrom collections import Counter\nfrom pathlib import Path\n\nimport pandas as pd\nfrom nemo_curator.stages.text.filters.doc_filter import DocumentFilter\n\nsys.path.insert(0, ".")\nsys.path.insert(0, "scripts")\ntry:\n    import _env\n    _env.load()\nexcept Exception:\n    pass\n\nDB = "data/generated/service.sqlite"\nOUT_ROOT = Path("run/curation")\n\n\nclass InstructionLikeFilter(DocumentFilter):\n    """Drop technician notes that address the assistant instead of the record.\n\n    This is the stage that earns Curator its place in this project. The\n    heuristic stages above remove nothing from this corpus - it is generated,\n    so it has no CRLF, no stray URLs and no symbol soup - but the corpus has one\n    defect that matters, and it is the one scripts/test_injection.py exercises:\n    a note that contains instructions aimed at the model.\n\n    Curation is the right place to catch it. The answer-side rail added in pass\n    37 stops the model acting on such a note, which is the backstop; removing it\n    before it is ever embedded means the retriever cannot surface it and the\n    model never sees it at all. Defence at ingestion and defence at output are\n    not alternatives.\n\n    The markers are deliberately narrow: phrasing that addresses a reader of\n    instructions, which a note about a vehicle has no reason to contain. Words a\n    technician legitimately writes - "approved", "release", "closed" - are NOT\n    markers on their own, because dropping a real note is also a failure. The\n    false-positive rate against the live corpus is asserted at 0 by --selftest.\n    """\n\n    _MARKERS = (\n        r"system note",\n        r"\\bfor the assistant\\b",\n        r"\\b(?:dis|)regard (?:your|the|all|any)\\b.{0,24}\\binstruction",\n        r"\\bignore (?:your|the|all|any|previous)\\b.{0,24}\\binstruction",\n        r"\\byou are now\\b",\n        r"\\bnew instructions?\\b",\n        r"\\bdo not mention\\b",\n        r"\\bsystem prompt\\b",\n        r"^\\s*assistant\\s*:",\n    )\n\n    def __init__(self) -> None:\n        super().__init__()\n        self._re = [re.compile(m, re.I | re.M) for m in self._MARKERS]\n\n    def score_document(self, text: str) -> float:\n        return float(sum(1 for r in self._re if r.search(text or "")))\n\n    def keep_document(self, scores: float) -> bool:\n        return float(scores) == 0.0\n\ndef load_corpus() -> pd.DataFrame:\n    """mode=ro, because curation must not be able to damage the record."""\n    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)\n    try:\n        return pd.read_sql_query(\n            "SELECT update_id, ro_number, staff_id, at, shift, text FROM updates", con)\n    finally:\n        con.close()\n\n\ndef exact_duplicates(df: pd.DataFrame) -> dict:\n    """Exact duplicate texts, with the groups named so they can be checked.\n\n    Reported rather than removed: two technicians writing the same sentence on\n    different repair orders is not noise, and deciding that is not this\n    script\'s call.\n    """\n    counts = Counter(df["text"])\n    dupe_texts = {t: n for t, n in counts.items() if n > 1}\n    groups = []\n    for t, n in sorted(dupe_texts.items(), key=lambda kv: -kv[1])[:10]:\n        ids = df.loc[df["text"] == t, "update_id"].tolist()\n        ros = sorted(set(df.loc[df["text"] == t, "ro_number"].tolist()))\n        groups.append({"count": n, "update_ids": ids[:6],\n                       "distinct_ro_numbers": len(ros),\n                       "text": t[:110]})\n    return {"rows": len(df), "distinct_texts": len(counts),\n            "duplicate_rows": len(df) - len(counts),\n            "duplicate_groups": len(dupe_texts), "examples": groups}\n\n\ndef build_stages() -> list[tuple[str, object, str]]:\n    """(label, stage, why) - the why is the point of each one being here."""\n    from nemo_curator.stages.text.filters import ScoreFilter\n    from nemo_curator.stages.text.filters.heuristic import (\n        NonAlphaNumericFilter, WordCountFilter, WhiteSpaceFilter)\n    from nemo_curator.stages.text.modifiers import (\n        Modify, NewlineNormalizer, UrlRemover)\n\n    # Modify takes `input_fields` (default "text"), not `text_field` -\n    # ScoreFilter is the one that takes `text_field`. Both defaults are\n    # already "text" here, so neither is passed.\n\n    return [\n        ("normalise newlines", Modify(NewlineNormalizer()),\n         "a note pasted from a DMS arrives with CRLF and doubled blank lines; "\n         "the embedder sees those as content"),\n        ("strip urls", Modify(UrlRemover()),\n         "technician notes should carry no links. One that does is either a "\n         "paste accident or the injection vector that scripts/test_injection.py "\n         "exercises, and neither belongs in the index"),\n        # min_words=3, NOT the default 50. A default-configured WordCountFilter\n        # would delete the entire corpus: these are one-line shop-floor notes,\n        # and the median is far below fifty words.\n        ("drop near-empty notes",\n         ScoreFilter(WordCountFilter(min_words=3, max_words=20000),\n                     text_field="text", score_field="word_count"),\n         "a note of one or two words carries no retrievable meaning but still "\n         "occupies a chunk and can win a similarity search"),\n        ("drop symbol soup",\n         ScoreFilter(NonAlphaNumericFilter(max_non_alpha_numeric_to_text_ratio=0.5),\n                     text_field="text", score_field="non_alnum_ratio"),\n         "measurement dumps that are mostly punctuation retrieve badly and read "\n         "worse when quoted back to a service advisor"),\n        ("drop whitespace-heavy notes",\n         ScoreFilter(WhiteSpaceFilter(max_white_space_ratio=0.25),\n                     text_field="text", score_field="ws_ratio"),\n         "padding from a fixed-width DMS export"),\n        ("quarantine assistant-directed notes",\n         ScoreFilter(InstructionLikeFilter(), text_field="text",\n                     score_field="instruction_markers"),\n         "a note that addresses the model rather than the record is the "\n         "injection vector; removing it at ingestion means the retriever can "\n         "never surface it, which the answer-side rail cannot promise"),\n    ]\n\n\ndef run(write: bool) -> int:\n    from nemo_curator.pipeline import Pipeline\n    from nemo_curator.tasks import DocumentBatch\n\n    df = load_corpus()\n    print(f"corpus: {len(df)} updates from {DB}\\n")\n\n    dups = exact_duplicates(df)\n    print("exact duplicates (reported, not removed)")\n    print(f"  {dups[\'duplicate_rows\']} duplicate rows across "\n          f"{dups[\'duplicate_groups\']} groups; {dups[\'distinct_texts\']} distinct texts")\n    for g in dups["examples"][:4]:\n        print(f"    x{g[\'count\']} across {g[\'distinct_ro_numbers\']} RO(s): {g[\'text\'][:84]}")\n    print()\n\n    # One stage at a time, so a removal can be attributed to the rule that made\n    # it. A single pipeline would report only the total.\n    cur = df.copy()\n    report: list[dict] = []\n    print("curator stages")\n    for label, stage, why in build_stages():\n        before = len(cur)\n        t0 = time.time()\n        p = Pipeline(name=f"asoia-{label.replace(\' \', \'-\')}", stages=[stage])\n        out = p.run(initial_tasks=[DocumentBatch(dataset_name="updates", data=cur)])\n        frames = [t.to_pandas() if hasattr(t, "to_pandas") else t.data for t in (out or [])]\n        cur = pd.concat(frames, ignore_index=True) if frames else cur.iloc[0:0]\n        dt = time.time() - t0\n        removed = before - len(cur)\n        report.append({"stage": label, "before": before, "after": len(cur),\n                       "removed": removed, "seconds": round(dt, 2), "why": why})\n        print(f"  {label:28} {before:5} -> {len(cur):5}  removed {removed:4}  {dt:5.1f}s")\n    print()\n\n    kept = set(cur["update_id"]) if "update_id" in cur else set()\n    dropped = df.loc[~df["update_id"].isin(kept)]\n    print(f"result: {len(cur)} of {len(df)} updates survive "\n          f"({len(dropped)} dropped, {100 * len(cur) / max(1, len(df)):.1f}% kept)")\n    if len(dropped):\n        print("  dropped examples:")\n        for _, r in dropped.head(5).iterrows():\n            print(f"    {r[\'update_id\']}  {str(r[\'text\'])[:72]!r}")\n\n    payload = {\n        "db": DB, "rows_in": len(df), "rows_out": len(cur),\n        "exact_duplicates": dups, "stages": report,\n        "dropped_update_ids": dropped["update_id"].tolist(),\n    }\n    if write:\n        d = OUT_ROOT / time.strftime("%Y%m%dT%H%M%S")\n        d.mkdir(parents=True, exist_ok=True)\n        (d / "report.json").write_text(json.dumps(payload, indent=2))\n        cur.to_json(d / "curated.jsonl", orient="records", lines=True)\n        h = hashlib.sha256((d / "curated.jsonl").read_bytes()).hexdigest()[:16]\n        print(f"\\nwrote {d}/curated.jsonl ({len(cur)} rows, sha256 {h})")\n        print(f"wrote {d}/report.json")\n        print("\\nNOT done, on purpose: the live index is untouched. Re-indexing from")\n        print("this output is a separate, deliberate step.")\n    else:\n        print("\\n(report only - pass --write to save the curated set)")\n    return 0\n\n\ndef selftest() -> int:\n    """Both halves of the claim, measured: it catches the payload, and nothing else.\n\n    A filter that drops the poison is useless if it also drops real notes, and a\n    filter that keeps every real note is useless if it misses the poison. The\n    payload is read from scripts/test_injection.py rather than restated here, so\n    the two cannot drift apart.\n    """\n    import importlib.util as iu\n    spec = iu.spec_from_file_location("ti", "scripts/test_injection.py")\n    ti = iu.module_from_spec(spec)\n    try:\n        spec.loader.exec_module(ti)\n        poison = ti.POISON\n        src = "scripts/test_injection.py"\n    except Exception as e:\n        print(f"could not import the payload from scripts/test_injection.py ({e})")\n        return 2\n\n    f = InstructionLikeFilter()\n    bad = 0\n\n    score = f.score_document(poison)\n    caught = not f.keep_document(score)\n    print(f"  [{\'ok\' if caught else \'FAIL\'}] the known payload is caught "\n          f"(markers={int(score)}, from {src})")\n    bad += 0 if caught else 1\n\n    df = load_corpus()\n    flagged = [(r.update_id, r.text) for r in df.itertuples()\n               if not f.keep_document(f.score_document(r.text))]\n    clean = not flagged\n    print(f"  [{\'ok\' if clean else \'FAIL\'}] no false positives across "\n          f"{len(df)} live notes ({len(flagged)} flagged)")\n    for uid, t in flagged[:5]:\n        print(f"      {uid}  {str(t)[:70]!r}")\n    bad += 0 if clean else 1\n\n    # A marker must not fire on the ordinary vocabulary of a workshop.\n    innocent = [\n        "Advisor approved the extra work; customer notified and release authorised.",\n        "Repair order closed after road test. No further instructions from the advisor.",\n        "Front pad thickness 2.2mm, below the 3.0mm limit. Vehicle not safe to release.",\n    ]\n    ok = all(f.keep_document(f.score_document(t)) for t in innocent)\n    print(f"  [{\'ok\' if ok else \'FAIL\'}] ordinary workshop phrasing is not flagged")\n    bad += 0 if ok else 1\n\n    print()\n    print("all good" if not bad else f"{bad} failed")\n    return 0 if not bad else 1\n\n\ndef main() -> int:\n    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])\n    ap.add_argument("--write", action="store_true",\n                    help="save curated.jsonl and report.json under run/curation/")\n    ap.add_argument("--selftest", action="store_true",\n                    help="assert the injection filter catches the known payload "\n                         "and flags nothing in the live corpus")\n    a = ap.parse_args()\n    if a.selftest:\n        return selftest()\n    try:\n        return run(a.write)\n    except ModuleNotFoundError as e:\n        print(f"nemo_curator is not importable here ({e}).")\n        print("Run this with the curation environment:")\n        print("  .venv-curator/bin/python scripts/curate.py")\n        return 2\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'


def write_curate() -> None:
    p = ROOT / "scripts/curate.py"
    if p.exists() and p.read_text() == CURATE:
        note("scripts/curate.py: already current, skipped")
        return
    existed = p.exists()
    p.write_text(CURATE)
    p.chmod(0o755)
    note(f"scripts/curate.py: {'rewritten' if existed else 'created'}, "
         f"{len(CURATE.splitlines())} lines")


def narrow_gateway_tool() -> None:
    """Say, in the file, that `write` is wrong for a launchable-managed gateway."""
    rel = "scripts/openshell_gateway.py"
    p = ROOT / rel
    if not p.exists():
        note(f"{rel}: absent, skipped")
        return
    txt = p.read_text()
    if "NemoClaw owns gateway registration" in txt:
        note(f"{rel}: already carries the launchable caveat, skipped")
        return
    anchor = 'SECRET_ENV = "OPENSHELL_CLIENT_SECRET"'
    if txt.count(anchor) != 1:
        raise RuntimeError(f"pass 47 refused: {txt.count(anchor)} matches for the anchor")
    caveat = (
        '# NOT FOR A BREV LAUNCHABLE.\n'
        '#\n'
        '# `write` hand-registers a gateway. On a NemoClaw launchable that is the\n'
        '# wrong thing to do: NemoClaw owns gateway registration and Brev\n'
        '# supervises the declared gateway, and the launchable instructions say\n'
        '# explicitly not to start, stop, replace or register it directly. There,\n'
        '# onboard with /usr/local/bin/brev-quickstart and let it register the\n'
        '# gateway; this script\'s `check` and `show` verbs are still the quickest\n'
        '# way to see whether a client can reach it.\n'
        '#\n'
        '# `write` remains correct for a gateway you run yourself.\n'
    )
    txt = txt.replace(anchor, caveat + anchor)
    # And say it at the moment someone uses it, not only in a comment.
    old_w = '    print("\\n  no secret was written. Put it in .env as:")'
    new_w = ('    print("\\n  NOTE: on a Brev launchable, NemoClaw owns gateway "\n'
             '          "registration - use brev-quickstart there, not this verb.")\n'
             '    print("\\n  no secret was written. Put it in .env as:")')
    if txt.count(old_w) == 1:
        txt = txt.replace(old_w, new_w)
    p.write_text(txt)
    note(f"{rel}: launchable caveat added to the docstring and to `write`")


def readme_row() -> None:
    rel = "patches/README.md"
    p = ROOT / rel
    txt = p.read_text()
    if "quality_pass47.py" in txt:
        note(f"{rel}: row already present, skipped")
        return
    m = re.search(r"^\| `quality_pass46\.py`.*$", txt, re.M)
    if not m:
        note(f"{rel}: no row 46 to insert after, skipped")
        return
    row = ("| `quality_pass47.py` | row 3 had no code at all; a six-stage NeMo "
           "Curator pipeline over the real corpus, whose five heuristic stages "
           "correctly remove nothing from generated data and whose sixth "
           "quarantines notes that address the model - the injection vector - "
           "caught 1/1 with 0 false positives across 1,949 notes |")
    p.write_text(txt[:m.end()] + "\n" + row + txt[m.end():])
    note(f"{rel}: row added after quality_pass46.py")


def checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def ck(n: str, ok: bool, d: str = "") -> None:
        out.append((n, bool(ok), d))

    p = ROOT / "scripts/curate.py"
    ck("scripts/curate.py exists", p.exists())
    body = p.read_text()
    import ast
    try:
        ast.parse(body); ck("curate.py parses", True)
    except SyntaxError as e:
        ck("curate.py parses", False, str(e)); return out

    # It must not be able to damage the system of record.
    ck("the corpus is opened read-only", "mode=ro" in body and "uri=True" in body)
    # Not a search for SQL keywords: `re.I` plus the stage label "drop
    # near-empty notes" matched `DROP\s+\w` and failed this on prose, which is
    # the ninth time this project has tested for a word instead of for syntax.
    # The real guarantee is that every connection this file opens is read-only,
    # so assert exactly that.
    conns = re.findall(r"sqlite3\.connect\(([^)]*)\)", body, re.S)
    ck("every sqlite connection is read-only",
       bool(conns) and all("mode=ro" in c for c in conns),
       f"{len(conns)} connection(s): {[c[:40] for c in conns]}")
    ck("output goes under run/curation", 'OUT_ROOT = Path("run/curation")' in body)

    # The stage that justifies the pass, and the discipline around it.
    ck("the injection quarantine stage exists", "InstructionLikeFilter" in body)
    ck("the payload is imported, not restated",
       "scripts/test_injection.py" in body and "ti.POISON" in body,
       "restating the payload lets the filter and the attack drift apart")
    # Words a technician legitimately writes must not be markers on their own.
    markers = body[body.index("_MARKERS = ("):body.index("def __init__(self) -> None:")]
    for word in ("approved", "release", "closed", "invoice"):
        ck(f"'{word}' is not a marker on its own", word not in markers.lower())
    ck("the selftest asserts both directions",
       "no false positives" in body and "the known payload is caught" in body)

    g = ROOT / "scripts/openshell_gateway.py"
    if g.exists():
        gb = g.read_text()
        ck("the gateway tool warns about launchables",
           "NemoClaw owns gateway registration" in gb)
        r = subprocess.run([str(ROOT / ".venv/bin/python"), "-c",
                            "import ast;ast.parse(open('scripts/openshell_gateway.py').read())"],
                           capture_output=True, text=True, cwd=str(ROOT))
        ck("openshell_gateway.py still parses", r.returncode == 0,
           r.stderr.strip()[:120])

    txt = (ROOT / "patches/README.md").read_text()
    rows = re.findall(r"^\| `([^`]+\.py)`", txt, re.M)
    files = sorted(x.name for x in (ROOT / "patches").glob("quality_pass*.py"))
    ck("README has a row 47", "quality_pass47.py" in rows)
    ck("README rows match script files", sorted(rows) == files,
       f"{len(rows)} rows vs {len(files)} files")
    return out


def main() -> int:
    print("pass 47: curation, and the stage it is worth running for\n")
    write_curate()
    narrow_gateway_tool()
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
    print("\nrun it with the curation environment, not the serving one:")
    print("  .venv-curator/bin/python scripts/curate.py --selftest")
    print("  .venv-curator/bin/python scripts/curate.py --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
