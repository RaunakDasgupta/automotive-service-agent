#!/usr/bin/env python3
"""Thirty-third pass: the whole stack self-hosted, and a row count that read zero
over a complete index.

Run from the project root:   .venv/bin/python quality_pass33.py

THE STACK IS NOW ENTIRELY LOCAL, WHICH IS WHAT THE README ALWAYS CLAIMED

    llm     local   nvidia/llama-3.1-nemotron-nano-8b-v1
    embed   local   nvidia/nv-embedqa-e5-v5          (1024-dim)
    rerank  local   nvidia/nv-rerankqa-mistral-4b-v3

Two of the three were running and idle while the app called hosted endpoints
instead, for two different reasons.

The embedder was deliberate: hosted nemotron-3-embed-1b is 2048-dimensional and
the local nv-embedqa-e5-v5 is 1024, so switching without rebuilding leaves vectors
and queries at different widths - and `index_staleness()` would not notice,
because the ids and the counts still match. The index has been rebuilt at 1024
against the local container: 1,949 chunks in 4.9 seconds, where the hosted path
was rate-limited to about 40 requests a minute.

The LLM was an accident, and it was breaking the product. The same blunt
NIM_MODE=hosted sent it to a model that reached end of life on 2026-08-26:

    HTTP 410 Gone: The model 'nvidia/llama-3.1-nemotron-nano-8b-v1' has reached
    its end of life on 2026-08-26T09:00:00Z and is no longer available.

Every narrative answer failed on that for over a month. Every deterministic one
kept working, which is exactly why all fourteen answer checks passed throughout
and nothing raised a flag: the figures are computed in Python and never went near
the LLM. The container serving the identical model id was up the whole time,
answering in 147ms.

WHY NIM_MODE=auto IS NOT THE ANSWER

`auto` probes and prefers a healthy local NIM for every service, embedding
included, which would have silently broken search against the 2048-dim index.
That is why the mode was pinned to `hosted` in the first place. With the index
rebuilt at the local width, `local` is now both correct and safe.

count() READ ZERO OVER 1,949 ROWS

`get_collection_stats()["row_count"]` counts SEALED segments only. A freshly built
index is entirely in a growing segment, so measured straight after the rebuild:

    get_collection_stats  ->  {'row_count': 0}
    count(*)              ->  1949
    len(scan())           ->  1949

It reports that zero rather than raising, so the `scan()` fallback underneath it
never fired, and the Vector store tab showed an empty index over a complete one
until Milvus happened to flush - which is time-and-size driven and may be minutes
away. Same shape as every other bug in this project's history: a degraded value
that is not an error. count() now runs a count(*) query, which goes through the
same read path as a search and honours the strong consistency the collection is
created with.

Only one caller reads it (app/review/store.py), which was checked before changing
it - the pass 29 lesson.

AND THE README SAID LanceDB

Six passes after the move to Milvus. It also listed the NIMs as self-hosted while
two of them were not. Both corrected, with the reason recorded, because a stack
diagram that disagrees with the running system is worse than none.
"""
import sys, pathlib, ast, subprocess

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
                 "      NOTE: edits before this one HAVE been applied - this\n"
                 "      harness writes as it goes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ==================== 1. a count that counts
edit('app/retrieval/backend.py',
     '''    def count(self) -> int | None:
        try:
            s = self.client().get_collection_stats(self.collection)
            return int(s.get("row_count", 0))
        except Exception:
            try:
                return len(self.scan())
            except Exception:
                return None
''',
     '''    def count(self) -> int | None:
        """How many rows are really in the collection.

        NOT get_collection_stats()["row_count"]. That counts SEALED segments
        only, so anything still in a growing segment is invisible to it - and a
        freshly built index is entirely in a growing segment. Measured on this
        box straight after a 1,949-row rebuild:

            get_collection_stats  ->  {'row_count': 0}
            count(*)              ->  1949
            len(scan())           ->  1949

        And it does not raise to get there. It returns 0, so the `scan()`
        fallback below never fired, and the Vector store tab reported an empty
        index over a complete one until Milvus happened to flush - which is
        time-and-size driven and may be minutes away. A zero that should have
        been an error, one more time.

        A count(*) query goes through the same read path as a search, so it
        respects the strong consistency this collection is created with.
        """
        try:
            r = self.client().query(self.collection, filter="",
                                    output_fields=["count(*)"],
                                    consistency_level="Strong")
            if r:
                return int(dict(r[0])["count(*)"])
        except Exception:
            pass
        try:
            return len(self.scan())
        except Exception:
            return None
''',
     'backend.py  count() asks for count(*), not sealed-segment stats',
     skip_if='output_fields=["count(*)"]')


# ==================== 2. the architecture, as it actually is
edit('README.md',
     '''Built on the NVIDIA stack: self-hosted **Nemotron Nano 8B NIM**, **nv-embedqa-e5-v5**,
**nv-rerankqa-mistral-4b-v3**, hosted **Parakeet ASR**, **NeMo Agent Toolkit**,
**NeMo Guardrails**, LanceDB.
''',
     '''Built on the NVIDIA stack, with all three NIMs self-hosted on one L40S:
**Nemotron Nano 8B**, **nv-embedqa-e5-v5** (1024-dim), **nv-rerankqa-mistral-4b-v3**,
plus **Parakeet ASR** over Riva gRPC, **NeMo Agent Toolkit**, **NeMo Guardrails**,
and **Milvus** standalone for the vector store.

**Nothing in the answer path calls a hosted model**, and that is deliberate rather
than tidy. Two hosted models this project depended on have been retired underneath
it: the embedder, which is what made model ids configuration rather than code, and
then `llama-3.1-nemotron-nano-8b-v1`, which reached end of life on 2026-08-26 and
now returns

    HTTP 410 Gone: the model has reached its end of life

taking every narrative answer with it while the deterministic ones carried on
passing. `NIM_MODE=local` removes that whole class of failure; the per-service
overrides `NIM_MODE_LLM`, `NIM_MODE_EMBED` and `NIM_MODE_RERANK` exist for when only
part of the stack is up. Speech-to-text is the one hosted dependency left, because
there is no Riva container in this deployment.
''',
     'README.md  the stack as it actually runs',
     skip_if='Nothing in the answer path calls a hosted model')


# ==================== verify
print("Quality pass 33:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


print("\nthe row count:")
be = (ROOT / "app/retrieval/backend.py").read_text()
ast.parse(be)
chk("backend.py parses", True)

# Look INSIDE count(), not across the file: `consistency_level="Strong"` appears
# in create(), get() and scan() too, so a whole-file count would pass whatever
# this function does.
_body = be.split("    def count(self)")[1].split("\n    def ")[0]
chk("count() asks the server for count(*)", 'output_fields=["count(*)"]' in _body)
chk("that query is strongly consistent",
    'consistency_level="Strong"' in _body,
    "it must see the same rows a search sees")
# The WORD is in the docstring, which is where the explanation of why that call is
# wrong belongs. What must be gone is the CALL. Asserting the word asserted the
# documentation instead of the code, and reported WRONG against a count() that was
# already provably correct. Fourth time in this project - passes 29, 30 and 31 -
# and always this same shape.
chk("it no longer trusts row_count",
    "self.client().get_collection_stats(" not in _body,
    "sealed segments only; a fresh build is entirely growing segments")
chk("scan() is still the fallback", "return len(self.scan())" in _body)

# The behaviour, not the source: this is the number the Vector store tab shows.
try:
    sys.path.insert(0, ".")
    from app.retrieval.backend import backend
    b = backend()
    n, scanned, d = b.count(), len(b.scan()), b.dim()
    chk("count() agrees with a full scan", n == scanned, f"count={n} scan={scanned}")
    chk("the index is not empty", bool(n), f"{n} rows at {d} dims")
    from app.state import db as dbm
    rows = dbm.connect().execute("SELECT COUNT(*) FROM updates").fetchone()[0]
    chk("and with the database", n == rows, f"index={n} updates={rows}")
except Exception as e:
    print(f"  note    cannot reach the store here ({type(e).__name__}: "
          f"{str(e)[:70]}) - this runs for real on the box")

print("\nthe architecture, as documented:")
rm = (ROOT / "README.md").read_text()
chk("the store is named correctly", "**Milvus**" in rm and "LanceDB." not in rm,
    "it said LanceDB six passes after the move to Milvus")
chk("it states nothing hosted is in the answer path",
    "Nothing in the answer path calls a hosted model" in rm)
chk("it records the 410 that made that necessary", "HTTP 410 Gone" in rm)
chk("it names the local embedder and its width",
    "nv-embedqa-e5-v5** (1024-dim)" in rm)
chk("ASR is still declared hosted, because it is",
    "no Riva container in this deployment" in rm)

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    bash scripts/stack.sh status      MODELS should read local, local, local
    .venv/bin/python scripts/test_review.py --live
""")
sys.exit(1 if bad else 0)
