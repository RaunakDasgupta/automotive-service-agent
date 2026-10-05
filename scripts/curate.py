#!/usr/bin/env python
"""Curate the technician update corpus with NeMo Curator.

    .venv-curator/bin/python scripts/curate.py            # report only
    .venv-curator/bin/python scripts/curate.py --write    # also write the output

Runs in `.venv-curator`, never the serving venv. nemo-curator's base
dependencies are Ray, Torch and Transformers - 6.3 GB - and putting that
underneath a live serving stack to tidy 1,949 short notes would be a bad trade.
The two environments share nothing but the repository.

This reads the corpus read-only and writes NOTHING to the system of record.
Curation proposes; a separate, deliberate step would re-index. A script that
silently rewrote the store the agent is answering from would be the worst
possible shape for this.

Scope, stated plainly rather than implied: the heuristic and modifier stages
below are real Curator stages in a real Curator Pipeline, and the per-stage
attribution is measured by running them one at a time. Curator's *deduplication*
is a separate file-based workflow (`TextDuplicatesRemovalWorkflow`) that wants
parquet round-trips and an identification pass to produce the ids to remove; for
a corpus this size the exact-duplicate set is computed directly here and
reported instead. That is a deliberate scope choice, not an oversight.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd
from nemo_curator.stages.text.filters.doc_filter import DocumentFilter

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
try:
    import _env
    _env.load()
except Exception:
    pass

DB = "data/generated/service.sqlite"
OUT_ROOT = Path("run/curation")


class InstructionLikeFilter(DocumentFilter):
    """Drop technician notes that address the assistant instead of the record.

    This is the stage that earns Curator its place in this project. The
    heuristic stages above remove nothing from this corpus - it is generated,
    so it has no CRLF, no stray URLs and no symbol soup - but the corpus has one
    defect that matters, and it is the one scripts/test_injection.py exercises:
    a note that contains instructions aimed at the model.

    Curation is the right place to catch it. The answer-side rail added in pass
    37 stops the model acting on such a note, which is the backstop; removing it
    before it is ever embedded means the retriever cannot surface it and the
    model never sees it at all. Defence at ingestion and defence at output are
    not alternatives.

    The markers are deliberately narrow: phrasing that addresses a reader of
    instructions, which a note about a vehicle has no reason to contain. Words a
    technician legitimately writes - "approved", "release", "closed" - are NOT
    markers on their own, because dropping a real note is also a failure. The
    false-positive rate against the live corpus is asserted at 0 by --selftest.
    """

    _MARKERS = (
        r"system note",
        r"\bfor the assistant\b",
        r"\b(?:dis|)regard (?:your|the|all|any)\b.{0,24}\binstruction",
        r"\bignore (?:your|the|all|any|previous)\b.{0,24}\binstruction",
        r"\byou are now\b",
        r"\bnew instructions?\b",
        r"\bdo not mention\b",
        r"\bsystem prompt\b",
        r"^\s*assistant\s*:",
    )

    def __init__(self) -> None:
        super().__init__()
        self._re = [re.compile(m, re.I | re.M) for m in self._MARKERS]

    def score_document(self, text: str) -> float:
        return float(sum(1 for r in self._re if r.search(text or "")))

    def keep_document(self, scores: float) -> bool:
        return float(scores) == 0.0

def load_corpus() -> pd.DataFrame:
    """mode=ro, because curation must not be able to damage the record."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(
            "SELECT update_id, ro_number, staff_id, at, shift, text FROM updates", con)
    finally:
        con.close()


def exact_duplicates(df: pd.DataFrame) -> dict:
    """Exact duplicate texts, with the groups named so they can be checked.

    Reported rather than removed: two technicians writing the same sentence on
    different repair orders is not noise, and deciding that is not this
    script's call.
    """
    counts = Counter(df["text"])
    dupe_texts = {t: n for t, n in counts.items() if n > 1}
    groups = []
    for t, n in sorted(dupe_texts.items(), key=lambda kv: -kv[1])[:10]:
        ids = df.loc[df["text"] == t, "update_id"].tolist()
        ros = sorted(set(df.loc[df["text"] == t, "ro_number"].tolist()))
        groups.append({"count": n, "update_ids": ids[:6],
                       "distinct_ro_numbers": len(ros),
                       "text": t[:110]})
    return {"rows": len(df), "distinct_texts": len(counts),
            "duplicate_rows": len(df) - len(counts),
            "duplicate_groups": len(dupe_texts), "examples": groups}


def build_stages() -> list[tuple[str, object, str]]:
    """(label, stage, why) - the why is the point of each one being here."""
    from nemo_curator.stages.text.filters import ScoreFilter
    from nemo_curator.stages.text.filters.heuristic import (
        NonAlphaNumericFilter, WordCountFilter, WhiteSpaceFilter)
    from nemo_curator.stages.text.modifiers import (
        Modify, NewlineNormalizer, UrlRemover)

    # Modify takes `input_fields` (default "text"), not `text_field` -
    # ScoreFilter is the one that takes `text_field`. Both defaults are
    # already "text" here, so neither is passed.

    return [
        ("normalise newlines", Modify(NewlineNormalizer()),
         "a note pasted from a DMS arrives with CRLF and doubled blank lines; "
         "the embedder sees those as content"),
        ("strip urls", Modify(UrlRemover()),
         "technician notes should carry no links. One that does is either a "
         "paste accident or the injection vector that scripts/test_injection.py "
         "exercises, and neither belongs in the index"),
        # min_words=3, NOT the default 50. A default-configured WordCountFilter
        # would delete the entire corpus: these are one-line shop-floor notes,
        # and the median is far below fifty words.
        ("drop near-empty notes",
         ScoreFilter(WordCountFilter(min_words=3, max_words=20000),
                     text_field="text", score_field="word_count"),
         "a note of one or two words carries no retrievable meaning but still "
         "occupies a chunk and can win a similarity search"),
        ("drop symbol soup",
         ScoreFilter(NonAlphaNumericFilter(max_non_alpha_numeric_to_text_ratio=0.5),
                     text_field="text", score_field="non_alnum_ratio"),
         "measurement dumps that are mostly punctuation retrieve badly and read "
         "worse when quoted back to a service advisor"),
        ("drop whitespace-heavy notes",
         ScoreFilter(WhiteSpaceFilter(max_white_space_ratio=0.25),
                     text_field="text", score_field="ws_ratio"),
         "padding from a fixed-width DMS export"),
        ("quarantine assistant-directed notes",
         ScoreFilter(InstructionLikeFilter(), text_field="text",
                     score_field="instruction_markers"),
         "a note that addresses the model rather than the record is the "
         "injection vector; removing it at ingestion means the retriever can "
         "never surface it, which the answer-side rail cannot promise"),
    ]


def run(write: bool) -> int:
    from nemo_curator.pipeline import Pipeline
    from nemo_curator.tasks import DocumentBatch

    df = load_corpus()
    print(f"corpus: {len(df)} updates from {DB}\n")

    dups = exact_duplicates(df)
    print("exact duplicates (reported, not removed)")
    print(f"  {dups['duplicate_rows']} duplicate rows across "
          f"{dups['duplicate_groups']} groups; {dups['distinct_texts']} distinct texts")
    for g in dups["examples"][:4]:
        print(f"    x{g['count']} across {g['distinct_ro_numbers']} RO(s): {g['text'][:84]}")
    print()

    # One stage at a time, so a removal can be attributed to the rule that made
    # it. A single pipeline would report only the total.
    cur = df.copy()
    report: list[dict] = []
    print("curator stages")
    for label, stage, why in build_stages():
        before = len(cur)
        t0 = time.time()
        p = Pipeline(name=f"asoia-{label.replace(' ', '-')}", stages=[stage])
        out = p.run(initial_tasks=[DocumentBatch(dataset_name="updates", data=cur)])
        frames = [t.to_pandas() if hasattr(t, "to_pandas") else t.data for t in (out or [])]
        cur = pd.concat(frames, ignore_index=True) if frames else cur.iloc[0:0]
        dt = time.time() - t0
        removed = before - len(cur)
        report.append({"stage": label, "before": before, "after": len(cur),
                       "removed": removed, "seconds": round(dt, 2), "why": why})
        print(f"  {label:28} {before:5} -> {len(cur):5}  removed {removed:4}  {dt:5.1f}s")
    print()

    kept = set(cur["update_id"]) if "update_id" in cur else set()
    dropped = df.loc[~df["update_id"].isin(kept)]
    print(f"result: {len(cur)} of {len(df)} updates survive "
          f"({len(dropped)} dropped, {100 * len(cur) / max(1, len(df)):.1f}% kept)")
    if len(dropped):
        print("  dropped examples:")
        for _, r in dropped.head(5).iterrows():
            print(f"    {r['update_id']}  {str(r['text'])[:72]!r}")

    payload = {
        "db": DB, "rows_in": len(df), "rows_out": len(cur),
        "exact_duplicates": dups, "stages": report,
        "dropped_update_ids": dropped["update_id"].tolist(),
    }
    if write:
        d = OUT_ROOT / time.strftime("%Y%m%dT%H%M%S")
        d.mkdir(parents=True, exist_ok=True)
        (d / "report.json").write_text(json.dumps(payload, indent=2))
        cur.to_json(d / "curated.jsonl", orient="records", lines=True)
        h = hashlib.sha256((d / "curated.jsonl").read_bytes()).hexdigest()[:16]
        print(f"\nwrote {d}/curated.jsonl ({len(cur)} rows, sha256 {h})")
        print(f"wrote {d}/report.json")
        print("\nNOT done, on purpose: the live index is untouched. Re-indexing from")
        print("this output is a separate, deliberate step.")
    else:
        print("\n(report only - pass --write to save the curated set)")
    return 0


def selftest() -> int:
    """Both halves of the claim, measured: it catches the payload, and nothing else.

    A filter that drops the poison is useless if it also drops real notes, and a
    filter that keeps every real note is useless if it misses the poison. The
    payload is read from scripts/test_injection.py rather than restated here, so
    the two cannot drift apart.
    """
    import importlib.util as iu
    spec = iu.spec_from_file_location("ti", "scripts/test_injection.py")
    ti = iu.module_from_spec(spec)
    try:
        spec.loader.exec_module(ti)
        poison = ti.POISON
        src = "scripts/test_injection.py"
    except Exception as e:
        print(f"could not import the payload from scripts/test_injection.py ({e})")
        return 2

    f = InstructionLikeFilter()
    bad = 0

    score = f.score_document(poison)
    caught = not f.keep_document(score)
    print(f"  [{'ok' if caught else 'FAIL'}] the known payload is caught "
          f"(markers={int(score)}, from {src})")
    bad += 0 if caught else 1

    df = load_corpus()
    flagged = [(r.update_id, r.text) for r in df.itertuples()
               if not f.keep_document(f.score_document(r.text))]
    clean = not flagged
    print(f"  [{'ok' if clean else 'FAIL'}] no false positives across "
          f"{len(df)} live notes ({len(flagged)} flagged)")
    for uid, t in flagged[:5]:
        print(f"      {uid}  {str(t)[:70]!r}")
    bad += 0 if clean else 1

    # A marker must not fire on the ordinary vocabulary of a workshop.
    innocent = [
        "Advisor approved the extra work; customer notified and release authorised.",
        "Repair order closed after road test. No further instructions from the advisor.",
        "Front pad thickness 2.2mm, below the 3.0mm limit. Vehicle not safe to release.",
    ]
    ok = all(f.keep_document(f.score_document(t)) for t in innocent)
    print(f"  [{'ok' if ok else 'FAIL'}] ordinary workshop phrasing is not flagged")
    bad += 0 if ok else 1

    print()
    print("all good" if not bad else f"{bad} failed")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="save curated.jsonl and report.json under run/curation/")
    ap.add_argument("--selftest", action="store_true",
                    help="assert the injection filter catches the known payload "
                         "and flags nothing in the live corpus")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    try:
        return run(a.write)
    except ModuleNotFoundError as e:
        print(f"nemo_curator is not importable here ({e}).")
        print("Run this with the curation environment:")
        print("  .venv-curator/bin/python scripts/curate.py")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
