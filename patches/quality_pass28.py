#!/usr/bin/env python3
"""Twenty-eighth pass: model ids are configuration, not code.

Run from the project root:   .venv/bin/python quality_pass28.py

Building the Milvus index failed like this:

    HTTP 410: "The model 'nvidia/nv-embedqa-e5-v5' has reached its end of life
               on 2026-08-25T09:00:00Z and is no longer available."

Nothing was wrong with the code. A hosted catalogue retires models on its own
schedule, and three model ids were hardcoded, so a date passing somewhere else
became an outage that needed an edit and a redeploy here.

Every id is now an environment variable with the current default:

    NIM_MODEL_LLM_HOSTED      NIM_MODEL_LLM_LOCAL
    NIM_MODEL_EMBED_HOSTED    NIM_MODEL_EMBED_LOCAL
    NIM_MODEL_RERANK_HOSTED   NIM_MODEL_RERANK_LOCAL

The hosted embedding default moves to `nvidia/nemotron-3-embed-1b`, which is
what the catalogue actually serves today - verified against the live endpoint,
where of seven listed embedding models only that one answers.

IT IS 2048-DIMENSIONAL, WHERE THE OLD ONE WAS 1024.

Nothing hardcodes the width; the store takes it from the data at build time. But
an index built before this change cannot be searched after it, and
`index_staleness()` will NOT notice - ids, counts and text all still match, and
only the vectors are incomparable. Rebuild after changing the embedding model.
That gap is named here rather than closed, because checking the stored width
against the live model would cost a call on every health check.

AND THERE IS NO HOSTED RERANKER ANY MORE.

Every `/v1/retrieval/<model>/reranking` path 404s - the old id and the obvious
successors alike. `search()` already catches that and returns vector-only
results with `rerank_error` set, built in pass 24, so retrieval keeps working
with one stage instead of two and says so. To get the second stage back, run the
rerank NIM on the box and set NIM_MODE_RERANK=local.
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
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


edit('app/nim/client.py',
     'MODELS = {\n    "llm":    {"hosted": "nvidia/llama-3.1-nemotron-nano-8b-v1",\n               "local":  "nvidia/llama-3.1-nemotron-nano-8b-v1"},\n    "embed":  {"hosted": "nvidia/nv-embedqa-e5-v5", "local": "nvidia/nv-embedqa-e5-v5"},\n    "rerank": {"hosted": "nvidia/nv-rerankqa-mistral-4b-v3",\n               "local":  "nvidia/nv-rerankqa-mistral-4b-v3"},\n}',
     '# Model ids are configuration, not code. `nvidia/nv-embedqa-e5-v5` reached end of\n# life on 2026-08-25 and the hosted endpoint now answers\n#\n#     HTTP 410 ... "has reached its end of life ... no longer available"\n#\n# which stopped the index building until this file changed. A hosted catalogue\n# retires models on its own schedule; an override that needs an edit and a\n# redeploy is an outage waiting for a date. Every id can now be set from the\n# environment, so the next retirement is a variable, not a patch.\n#\n# As of 2026-09-29 the hosted catalogue lists seven embedding models and NO\n# reranking model at all - every `/v1/retrieval/<model>/reranking` path 404s.\n# `search()` already degrades to vector-only and flags `rerank_error` when the\n# reranker is unreachable, so retrieval keeps working and says that it is\n# working with one stage instead of two. To get the stage back, run the rerank\n# NIM on the box: scripts/start_nims.sh, then NIM_MODE_RERANK=local.\ndef _model(service: str, where: str, default: str) -> str:\n    return os.environ.get(f"NIM_MODEL_{service.upper()}_{where.upper()}", default)\n\n\nMODELS = {\n    "llm":    {"hosted": _model("llm", "hosted",\n                                "nvidia/llama-3.1-nemotron-nano-8b-v1"),\n               "local":  _model("llm", "local",\n                                "nvidia/llama-3.1-nemotron-nano-8b-v1")},\n    # nemotron-3-embed-1b is 2048-dimensional, where nv-embedqa-e5-v5 was 1024.\n    # Nothing hardcodes the width - the vector store takes it from the data at\n    # build time - but an index built before this change cannot be searched\n    # after it, and index_staleness will not notice, because the ids and counts\n    # still match. Rebuild after changing the embedding model.\n    "embed":  {"hosted": _model("embed", "hosted", "nvidia/nemotron-3-embed-1b"),\n               "local":  _model("embed", "local", "nvidia/nv-embedqa-e5-v5")},\n    "rerank": {"hosted": _model("rerank", "hosted",\n                                "nvidia/nv-rerankqa-mistral-4b-v3"),\n               "local":  _model("rerank", "local",\n                                "nvidia/nv-rerankqa-mistral-4b-v3")},\n}',
     'client.py  model ids from the environment, and a live embedding default',
     skip_if='def _model(service: str')


# ==================== verify
print("Quality pass 28:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/nim/client.py").read_text())
print("\nclient.py parses cleanly.")

sys.path.insert(0, ".")
import os, importlib
bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


import app.nim.client as C
importlib.reload(C)
print("\ndefaults:")
chk("the retired embedder is gone",
    C.MODELS["embed"]["hosted"] != "nvidia/nv-embedqa-e5-v5",
    C.MODELS["embed"]["hosted"])
chk("the llm default is unchanged",
    C.MODELS["llm"]["hosted"] == "nvidia/llama-3.1-nemotron-nano-8b-v1")

print("\noverrides:")
os.environ["NIM_MODEL_EMBED_HOSTED"] = "acme/test-embed"
importlib.reload(C)
chk("an env var overrides the default",
    C.MODELS["embed"]["hosted"] == "acme/test-embed", C.MODELS["embed"]["hosted"])
del os.environ["NIM_MODEL_EMBED_HOSTED"]
importlib.reload(C)
chk("removing it restores the default",
    C.MODELS["embed"]["hosted"] == "nvidia/nemotron-3-embed-1b")
for s in ("llm", "embed", "rerank"):
    for w in ("hosted", "local"):
        os.environ["NIM_MODEL_%s_%s" % (s.upper(), w.upper())] = "x/%s-%s" % (s, w)
importlib.reload(C)
chk("all six are overridable",
    all(C.MODELS[s][w] == "x/%s-%s" % (s, w)
        for s in ("llm", "embed", "rerank") for w in ("hosted", "local")))
for s in ("llm", "embed", "rerank"):
    for w in ("hosted", "local"):
        del os.environ["NIM_MODEL_%s_%s" % (s.upper(), w.upper())]
importlib.reload(C)

print("\nretrieval degrades when the reranker is unreachable:")
src = (ROOT / "app/retrieval/index.py").read_text()
chk("search catches a rerank failure", "rerank_error" in src)
chk("and still returns the vector results", "return hits[:rerank_to]" in src)

print("\n%d check(s) unexpected" % bad if bad else "\nAll checks as expected.")
print("""
The embedding width changed from 1024 to 2048, so the index MUST be rebuilt:

    .venv/bin/python -c "from app.retrieval.index import build; print(build())"

Nothing will tell you if you skip it: ids, counts and text all still match, and
only the vectors are incomparable.
""")
sys.exit(1 if bad else 0)
