"""Semantic search over technician updates: Milvus + nv-embedqa + nv-rerankqa.

Scope note: most manager questions ("what is the state of RO-x", "which are
blocked", "what did EMP014 do") are STRUCTURED queries and are answered by the
deterministic tools, not by this. Retrieval serves the narrative slice - "has
anyone seen this fault before", "what did the last technician say about it".
Building the index is a one-off batch job; only the query embedding is per-call.

The store is behind `app/retrieval/backend.py`, so Milvus and LanceDB are a
config change rather than a code change:

    VECTOR_BACKEND=milvus        (default)
    ASOIA_MILVUS_URI=data/generated/milvus.db      embedded, no server
    ASOIA_MILVUS_URI=http://localhost:19530        a Milvus standalone

Nothing in this file knows which one is in use.
"""
from __future__ import annotations
import os, time
from typing import Any

from app.state import db as dbm
from app.retrieval.backend import backend, BackendError
from app.nim.client import (embed as nim_embed, embed_query as nim_embed_query,
                            rerank as nim_rerank)

BATCH = 64


def _rows(con, only: list[str] | None = None) -> list[dict]:
    """Updates joined to their repair order, so retrieval can filter on metadata.

    `only` restricts to specific update ids, which is what re-indexing a single
    edited chunk needs - see app/retrieval/edit.py.
    """
    sql = """
      SELECT u.update_id, u.ro_number, u.staff_id, u.at, u.shift, u.text,
             s.name AS staff_name, s.role,
             r.make, r.model, r.model_year, r.category, r.concern, r.vin
      FROM updates u
      LEFT JOIN staff s ON s.staff_id = u.staff_id
      LEFT JOIN ros   r ON r.ro_number = u.ro_number
    """
    args: tuple = ()
    if only:
        sql += " WHERE u.update_id IN (%s)" % ",".join("?" * len(only))
        args = tuple(only)
    sql += " ORDER BY u.at"
    out = []
    for r in con.execute(sql, args):
        d = dict(r)
        d["vehicle"] = f"{d.pop('model_year')} {d.pop('make')} {d.pop('model')}"
        d.pop("role", None)
        # Embed the update together with light context so the vector carries the
        # vehicle and the job it belongs to, not just the sentence.
        d["embed_text"] = (f"{d['vehicle']} | {d['category']} | "
                           f"concern: {d['concern']} | update: {d['text']}")
        out.append(d)
    return out


def _embed_rows(rows: list[dict], progress: bool = False) -> int:
    """Embed in place. Returns the dimension."""
    vecs: list[list[float]] = []
    for i in range(0, len(rows), BATCH):
        chunk = [r["embed_text"] for r in rows[i:i + BATCH]]
        vecs.extend(nim_embed(chunk, input_type="passage"))
        if progress:
            print(f"  embedded {min(i + BATCH, len(rows))}/{len(rows)}", end="\r")
    if progress and rows:
        print()
    for r, v in zip(rows, vecs):
        r["vector"] = v
        r.pop("embed_text", None)
    return len(vecs[0]) if vecs else 0


def build(con=None, progress: bool = True, **_legacy) -> dict:
    """Embed every update once and persist. Run after 01, before any search."""
    con = con or dbm.connect()
    rows = _rows(con)
    if not rows:
        return {"rows": 0, "error": "no updates to index - generate the dataset first"}
    t0 = time.time()
    dim = _embed_rows(rows, progress)
    b = backend()
    b.create(dim)
    b.upsert(rows)
    st = b.stats()
    return {"rows": len(rows), "dim": dim, "seconds": round(time.time() - t0, 1),
            **st}


def reindex(update_ids: list[str], con=None) -> dict:
    """Re-embed and replace specific chunks. Used after an edit."""
    con = con or dbm.connect()
    rows = _rows(con, only=list(update_ids))
    if not rows:
        return {"reindexed": 0, "error": f"no updates found for {update_ids}"}
    dim = _embed_rows(rows)
    b = backend()
    if not b.exists():
        b.create(dim)
    n = b.upsert(rows)
    return {"reindexed": n, "dim": dim, "update_ids": [r["update_id"] for r in rows]}


# How many candidates the reranker is handed.
#
# 18, and not more, on evidence. A wider pool raises the ceiling - the vector
# stage puts the right repair order inside its top 18 for 72.5% of queries and
# inside its top 50 for 100% - but raising the ceiling did not raise the result:
# reranked recall@6 over 120 HELD-OUT queries is 49.2% at pool 18, 30 and 50
# alike. The apparent +7.5 points at pool 50 existed only on the 40 queries the
# number was chosen with, held-out MRR fell as the pool grew (0.236 -> 0.222 ->
# 0.196), and at 50 the model began answering "none of them" on a narration
# question, which the absence rail correctly blocked.
#
# Env-tunable because the right number is a property of the corpus rather than
# of the code - but measure on more than the 40-query sample before moving it.
RERANK_POOL = int(os.environ.get("ASOIA_RERANK_POOL", "18"))



def search(query: str, k: int = 8, rerank_to: int | None = 4,
           ro_number: str | None = None, category: str | None = None,
           **_legacy) -> list[dict]:
    """Vector search, then rerank. Returns passages with update_id for citation."""
    qv = nim_embed_query(query)
    # Retrieve wide, rerank narrow. cand must be used for BOTH the limit and the
    # slice below - slicing back to k would hide the wide pool from the reranker.
    #
    # The pool floor is 50 and not 18 because 18 was capping the reranker below
    # its own ceiling. Vector-stage recall of the right repair order, 40 queries:
    # top-18 72.5%, top-30 92.5%, top-50 100%. Handing it 18 meant the answer was
    # simply absent a quarter of the time, whatever the reranker then did.
    # Measured end to end at k=6: 50.0% -> 57.5% on those 40, and 41.7% -> 49.2%
    # on 120 held-out queries. Costs about 0.2s per search.
    cand = max(k, (rerank_to or 0) * 3, RERANK_POOL if rerank_to else 0)
    hits = backend().search(qv, k=cand, ro_number=ro_number)
    if category:
        hits = [h for h in hits if h.get("category") == category]

    if rerank_to and len(hits) > 1:
        try:
            ranked = nim_rerank(query, [h["text"] for h in hits], top_n=rerank_to)
            out = []
            for r in ranked:
                h = dict(hits[r["index"]])
                h["rerank_score"] = r["score"]
                out.append(h)
            return out
        except Exception as e:
            for h in hits:
                h["rerank_error"] = f"{type(e).__name__}"
            return hits[:rerank_to]
    return hits


def _dangling(update_ids: list[str]) -> list[str]:
    """Which of these ids are not in the database. Cheap: one query, k ids."""
    ids = [i for i in update_ids if i]
    if not ids:
        return []
    try:
        con = dbm.connect()
        q = ",".join("?" * len(ids))
        found = {r[0] for r in con.execute(
            f"SELECT update_id FROM updates WHERE update_id IN ({q})", ids)}
    except Exception:
        return []                      # never fail a search over a health check
    return [i for i in ids if i not in found]


def _rerank_on() -> bool:
    """ASOIA_RERANK=off takes the vector top-k straight, with no second stage.

    Pass 36 measured the reranker over 40 queries: recall@6 50.0% with it and 50.0%
    without, MRR worse with it, and recorded that it was not earning its latency.
    That verdict was an artefact of the sample. Over 120 queries the same
    comparison is 41.7% vector-only against 49.2% reranked - the reranker finds
    the right repair order in nine cases the vector stage alone misses. The
    default sample in scripts/evaluate.py is now 120 for that reason.

    It is a flag and not a deletion, for two reasons. The label is RO-level - a hit
    is any passage from the right repair order - so it cannot tell a wrong answer
    from a reasonable one, and an MRR gap of 0.020 over 40 queries is not grounds to
    remove a declared component of the architecture. And the VRAM it would free
    does not buy what it was wanted for: 12.6 GB free plus the reranker's 8.7 GB is
    21.4 GB against the 22.5 GB a second local 8B needs. It would cover a LoRA job,
    and that is the moment to turn it off deliberately.
    """
    return (os.environ.get("ASOIA_RERANK") or "on").strip().lower() != "off"


def search_updates(query: str, k: int = 6, ro_number: str | None = None) -> dict:
    """Agent-tool shape: grounded passages plus their citations.

    The citations are checked against the database before they leave. An index
    built from a previous dataset keeps working perfectly - it returns plausible
    passages and cites update ids that no longer exist - and nothing downstream
    would notice: `check_grounding` verifies figures in the ANSWER against the
    TOOL RESULTS, never that a cited id resolves to a row. So it is verified
    here, at the only place citations enter the system from outside the database.

    The passages are still returned, flagged rather than dropped. Silently
    removing them would hide a broken index behind slightly worse answers, which
    is the failure mode this project keeps having to dig back out of.
    """
    if _rerank_on():
        hits = search(query, k=max(k * 3, 18), rerank_to=k, ro_number=ro_number)
    else:
        # Retrieve exactly k. Asking for 18 and keeping 6 without a reranker to
        # order them would just discard twelve rows at random.
        hits = search(query, k=k, rerank_to=None, ro_number=ro_number)
    cits = [h["update_id"] for h in hits]
    out = {"query": query, "count": len(hits),
           "passages": [{"update_id": h["update_id"], "ro_number": h["ro_number"],
                         "at": h["at"], "by": h.get("staff_name") or h["staff_id"],
                         "vehicle": h.get("vehicle"), "text": h["text"],
                         "score": h.get("rerank_score", h.get("vector_score"))}
                        for h in hits],
           "citations": cits}
    gone = _dangling(cits)
    if gone:
        out["stale_index"] = {
            "dangling": gone,
            "note": (f"the vector index is out of date: {len(gone)} of "
                     f"{len(cits)} cited updates are not in the database. "
                     f"Rebuild it with app.retrieval.index.build()")}
    return out
