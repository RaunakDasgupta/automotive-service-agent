"""Read-only views over everything the agent stands on: events, updates, vectors.

WHY THIS EXISTS

The project's central claim is that every answer is derived from evidence and can
name it. Until now that claim was only checkable from the inside - `check_grounding`
asserted it, and you had to trust the assertion. Nobody could open the log, read the
chunk an answer cited, or watch the reranker change its mind.

This module is the evidence, exposed. It is deliberately one layer with no UI in it,
so `app/ui/gradio_app.py` and `app/api/server.py` show the SAME numbers rather than
two implementations that drift, and so the tests can call it directly.

Three rules it keeps:

  * READ ONLY. Nothing here writes. The one write in the system's review path is
    `log_answer`, which is separate, best-effort, and can be turned off.
  * NO VECTORS IN LIST VIEWS. A 1024-float vector per row turns a table browse into
    megabytes. Lists carry the dimension and the norm; the single-chunk view carries
    a preview.
  * A CONNECTION PER CALL. Gradio and FastAPI both run handlers on worker threads,
    and a SQLite connection belongs to the thread that made it. Passing one around
    is the bug pass 19 had to fix.
"""
from __future__ import annotations
import json
import math
import os
import sqlite3
import time
from dataclasses import fields as dc_fields, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from app.state import db as dbm

# Mirrors app/retrieval/index.py. Imported lazily everywhere so that the event and
# update views keep working on a box where lancedb is not installed.
LANCE_URI = os.environ.get("LANCE_URI", "data/generated/lancedb")
TABLE = "updates"

# What search_updates() actually uses. The trace has to match it or it is a
# demonstration of something else; test_review.py asserts they agree.
RETRIEVE_N = 18
RERANK_N = 6


def _con(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return con if con is not None else dbm.connect()


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur]


# ---------------------------------------------------------------- the event log

def events(ro_number: str | None = None, actor_id: str | None = None,
           event_type: str | None = None, since_hours: int | None = None,
           text: str | None = None, limit: int = 200, offset: int = 0,
           con: sqlite3.Connection | None = None) -> dict:
    """The append-only log, filtered. Newest first, because that is what is asked for."""
    c = _con(con)
    where, args = [], []
    if ro_number:
        where.append("ro_number = ?"); args.append(ro_number)
    if actor_id:
        where.append("actor_id = ?"); args.append(actor_id)
    if event_type:
        where.append("type = ?"); args.append(event_type)
    if since_hours:
        cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat()
        where.append("at >= ?"); args.append(cutoff)
    if text:
        where.append("payload LIKE ?"); args.append(f"%{text}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    total = c.execute(f"SELECT COUNT(*) FROM events{clause}", args).fetchone()[0]
    rows = _rows(c.execute(
        f"SELECT event_id, ro_number, type, at, actor_id, shift, source_update_id, "
        f"payload FROM events{clause} ORDER BY at DESC, event_id DESC LIMIT ? OFFSET ?",
        (*args, limit, offset)))
    for r in rows:
        try:
            r["payload"] = json.loads(r["payload"])
        except (TypeError, ValueError):
            pass
    return {"total": total, "returned": len(rows), "offset": offset, "events": rows}


def event_types(con: sqlite3.Connection | None = None) -> list[dict]:
    """Every event type with its count. Seventeen are defined; this shows which are used."""
    c = _con(con)
    return _rows(c.execute(
        "SELECT type, COUNT(*) AS n, MIN(at) AS first_at, MAX(at) AS last_at "
        "FROM events GROUP BY type ORDER BY n DESC"))


def actors(con: sqlite3.Connection | None = None) -> list[dict]:
    c = _con(con)
    return _rows(c.execute(
        "SELECT e.actor_id, COALESCE(s.name, e.actor_id) AS name, COUNT(*) AS n "
        "FROM events e LEFT JOIN staff s ON s.staff_id = e.actor_id "
        "GROUP BY e.actor_id ORDER BY n DESC"))


# ------------------------------------------------------- the fold, and its inputs

def ro_review(ro_number: str, con: sqlite3.Connection | None = None) -> dict:
    """A repair order's derived state NEXT TO the events it was derived from.

    The point of the side-by-side: state is not stored anywhere, it is folded from
    the log on every read. Showing the fold beside its inputs is the difference
    between asserting that and demonstrating it.
    """
    c = _con(con)
    ro = dbm.get_ro(c, ro_number)
    if not ro:
        return {"error": f"no repair order {ro_number}"}
    evs = dbm.events_for_ro(c, ro_number)

    snap = None
    try:
        from app.state.engine import fold
        promised = ro.get("promised_time")
        snap = fold(evs, promised_time=datetime.fromisoformat(promised) if promised else None)
    except Exception as e:                       # a fold bug must not blank the page
        return {"ro": ro, "fold_error": f"{type(e).__name__}: {e}",
                "events": [e_.as_dict() for e_ in evs]}

    state = getattr(snap, "state", None)
    return {
        "ro": ro,
        "event_count": len(evs),
        "state": getattr(state, "value", str(state)),
        "snapshot": _snapshot_dict(snap),
        "events": [e_.as_dict() for e_ in evs],
        "updates": _rows(c.execute(
            "SELECT update_id, staff_id, at, shift, text FROM updates "
            "WHERE ro_number = ? ORDER BY at", (ro_number,))),
    }


def _jsonable(v: Any, depth: int = 0) -> Any:
    """Anything a snapshot holds, as real JSON.

    A snapshot carries nested dataclasses (`OpStatus`), enums and datetimes. The
    first version of this tested them with `json.dumps(v, default=str)`, which
    serialises almost anything - so the guard passed and the raw object went into
    the payload, where the JSON viewer and FastAPI would both choke on it. Testing
    with a converter that always succeeds is not a test. This converts instead.
    """
    if depth > 6:
        return str(v)
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, timedelta):
        return v.total_seconds()
    if is_dataclass(v) and not isinstance(v, type):
        return {f.name: _jsonable(getattr(v, f.name, None), depth + 1)
                for f in dc_fields(v)}
    if isinstance(v, dict):
        return {str(k): _jsonable(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_jsonable(x, depth + 1) for x in v]
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


def _snapshot_dict(snap) -> dict:
    """A snapshot as plain JSON, whatever fields it happens to carry."""
    out: dict[str, Any] = {}
    for k in dir(snap):
        if k.startswith("_"):
            continue
        v = getattr(snap, k, None)
        if callable(v):
            continue
        out[k] = _jsonable(v)
    return out


def updates(ro_number: str | None = None, staff_id: str | None = None,
            text: str | None = None, limit: int = 200, offset: int = 0,
            con: sqlite3.Connection | None = None) -> dict:
    """The technician updates as written - the raw material the vectors are built from."""
    c = _con(con)
    where, args = [], []
    if ro_number:
        where.append("u.ro_number = ?"); args.append(ro_number)
    if staff_id:
        where.append("u.staff_id = ?"); args.append(staff_id)
    if text:
        where.append("u.text LIKE ?"); args.append(f"%{text}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) FROM updates u{clause}", args).fetchone()[0]
    rows = _rows(c.execute(
        f"SELECT u.update_id, u.ro_number, u.staff_id, COALESCE(s.name, u.staff_id) "
        f"AS staff_name, u.at, u.shift, u.text FROM updates u "
        f"LEFT JOIN staff s ON s.staff_id = u.staff_id{clause} "
        f"ORDER BY u.at DESC LIMIT ? OFFSET ?", (*args, limit, offset)))
    return {"total": total, "returned": len(rows), "offset": offset, "updates": rows}


# ------------------------------------------------------------- the vector store

# The store is behind app/retrieval/backend.py, so none of these functions know
# whether they are reading Milvus or LanceDB. Before pass 27 they spoke LanceDB
# directly, which is why swapping the store meant touching the review layer at
# all - and why it will not next time.

def _backend():
    from app.retrieval.backend import backend
    return backend()


def _scan() -> list[dict]:
    """Every row, without vectors - the vector column never becomes Python."""
    return _backend().scan()


def index_health(sample: int = 64, uri: str | None = None) -> dict:
    """Sample vectors and check they are real. A zero norm is a failed embedding.

    Deliberately a sampled, separate call: the browse views never touch vectors,
    so nothing else in this module would ever notice an index full of zeros.
    """
    try:
        recs = _backend().sample_vectors(sample)
    except Exception as e:
        return {"error": str(e)}
    norms = []
    for r in recs:
        v = r.get("vector")
        if v is None:
            continue
        norms.append(math.sqrt(sum(float(x) * float(x) for x in v)))
    if not norms:
        return {"sampled": 0, "error": "no vectors in the sample"}
    zero = sum(1 for n in norms if n < 1e-9)
    return {"sampled": len(norms), "zero_norm": zero,
            "min_norm": round(min(norms), 6), "max_norm": round(max(norms), 6),
            "mean_norm": round(sum(norms) / len(norms), 6),
            "ok": zero == 0}


def index_stats(uri: str | None = None) -> dict:
    """Which store, where, how big, how wide - and whether it matches the data."""
    b = _backend()
    out: dict[str, Any] = {**b.stats(), "exists": False}
    try:
        out["exists"] = b.exists()
    except Exception as e:
        out["error"] = str(e)
        return out
    if not out["exists"]:
        out["error"] = (f"no '{b.collection}' collection at {b.uri} - build the "
                        f"index first: .venv/bin/python -c "
                        f"'from app.retrieval.index import build; print(build())'")
        return out
    try:
        out["rows"] = b.count()
    except Exception:
        out["rows"] = None
    try:
        out["dim"] = b.dim()
    except Exception:
        out["dim"] = None
    try:
        p = b.uri
        if os.path.exists(p):
            out["built_at"] = datetime.fromtimestamp(os.path.getmtime(p)).isoformat(
                timespec="seconds")
            out["bytes"] = (os.path.getsize(p) if os.path.isfile(p) else
                            sum(os.path.getsize(os.path.join(dp, f))
                                for dp, _, fs in os.walk(p) for f in fs))
    except Exception:
        pass
    try:
        out["staleness"] = index_staleness()
    except Exception as e:
        out["staleness"] = {"ok": None, "reasons": [f"{type(e).__name__}: {e}"]}
    return out


def index_staleness(uri: str | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Does the vector index still match the database?

    This is the one failure in the system that produces confident, well-formed,
    fully "grounded" answers citing records that do not exist. `check_grounding`
    verifies that figures and repair-order references in the ANSWER appear in the
    TOOL RESULTS; nothing has ever checked that a cited update id resolves to a
    real row. Regenerate the data without rebuilding the index and retrieval goes
    on serving passages from the old dataset, citing ids that are gone, and every
    check passes.

    Four drifts, in increasing order of how much they matter:

        the counts differ            built from a different dataset
        the newest update is absent  recent work is invisible to search
        cited ids do not resolve     answers cite records that are not there
        the TEXT differs             answers quote wording that is not on file

    The last one is new in pass 27 and only became possible once chunks were
    editable: an edit that writes to the database but fails to re-embed leaves
    the index quoting the old wording, and ids and counts both still match.
    """
    c = _con(con)
    out: dict[str, Any] = {"ok": True, "reasons": []}
    try:
        db_updates = c.execute("SELECT COUNT(*) FROM updates").fetchone()[0]
    except Exception as e:
        return {"ok": None, "reasons": [f"no updates table: {type(e).__name__}"]}
    out["database_updates"] = db_updates
    try:
        rows = _scan()
    except Exception as e:
        return {"ok": None, "reasons": [str(e)], "database_updates": db_updates}

    out["index_rows"] = len(rows)
    excluded = set()
    try:
        from app.retrieval.edit import exclusions
        excluded = {e["update_id"] for e in exclusions(c)}
    except Exception:
        pass
    out["excluded"] = len(excluded)

    if len(rows) + len(excluded) != db_updates:
        out["ok"] = False
        out["reasons"].append(
            f"the index holds {len(rows)} chunks and the database has "
            f"{db_updates} updates"
            + (f" ({len(excluded)} deliberately excluded)" if excluded else ""))

    indexed = {r.get("update_id") for r in rows if r.get("update_id")}
    known = {r[0] for r in c.execute("SELECT update_id FROM updates")}
    dangling = sorted(indexed - known)
    out["dangling"] = len(dangling)
    out["dangling_sample"] = dangling[:5]
    if dangling:
        out["ok"] = False
        out["reasons"].append(
            f"{len(dangling)} indexed chunk(s) cite update ids that are not in "
            f"the database - answers would cite records that do not exist")

    unindexed = sorted(known - indexed - excluded)
    out["unindexed"] = len(unindexed)
    if unindexed:
        out["ok"] = False
        out["reasons"].append(
            f"{len(unindexed)} update(s) are not in the index and cannot be "
            f"found by semantic search")

    # Text drift: only checkable for ids present in both, and only worth checking
    # since chunks became editable.
    drifted = []
    try:
        db_text = {r[0]: r[1] for r in c.execute(
            "SELECT update_id, text FROM updates")}
        for r in rows:
            uid = r.get("update_id")
            if uid in db_text and (r.get("text") or "") != (db_text[uid] or ""):
                drifted.append(uid)
    except Exception:
        pass
    out["text_drift"] = len(drifted)
    out["text_drift_sample"] = drifted[:5]
    if drifted:
        out["ok"] = False
        out["reasons"].append(
            f"{len(drifted)} chunk(s) hold different text from the update they "
            f"come from - an edit was written but not re-embedded, so answers "
            f"would quote wording that is not on file")

    # The embedder it was BUILT with, against the one configured now.
    #
    # Everything above compares the index to the database, and all of it passes
    # after someone flips NIM_MODE: the same chunks, the same ids, the same
    # text. What changed is the width of the vectors - nemotron-3-embed-1b is
    # 2048 and nv-embedqa-e5-v5 is 1024 - so the index is perfectly consistent
    # and completely unusable, and the first sign of it is a pymilvus error on
    # a question. This is the check that fires when a GPU box comes back.
    #
    # An index built before the sidecar existed reports nothing here. Unknown
    # is not mismatched: refusing to answer because a note is missing would be
    # worse than the problem.
    try:
        from app.retrieval.index import index_meta
        from app.nim.client import resolve as _resolve
        meta = index_meta()
        built_with = meta.get("embed_model")
        if built_with:
            now_model = _resolve("embed")[1]      # (base, MODEL, mode)
            out["index_embed_model"] = built_with
            out["configured_embed_model"] = now_model
            if built_with != now_model:
                out["ok"] = False
                out["reasons"].append(
                    f"the index was built with {built_with} "
                    f"({meta.get('dim', '?')}-dimensional) and this process is "
                    f"configured for {now_model} - every search will fail on a "
                    f"dimension mismatch until it is rebuilt")
    except Exception:
        pass

    if not out["ok"]:
        out["fix"] = (".venv/bin/python -c 'from app.retrieval.index import build; "
                      "print(build())'")
    return out


def chunks(ro_number: str | None = None, text: str | None = None,
           limit: int = 100, offset: int = 0, uri: str | None = None) -> dict:
    """Browse what is IN the vector store, without pulling the vectors themselves.

    A 1024-float vector per row is about 8 KB; a hundred of them is most of a
    megabyte of numbers nobody reads, so the backend drops the vector column
    before any of it becomes Python. `index_health()` samples the vectors
    themselves, and `chunk()` shows one.
    """
    try:
        recs = _scan()
    except Exception as e:
        return {"error": str(e), "rows": [], "total": 0}

    out = []
    for r in recs:
        if ro_number and r.get("ro_number") != ro_number:
            continue
        if text and text.lower() not in (r.get("text") or "").lower():
            continue
        r.pop("vector", None)
        r.pop("_distance", None)
        out.append(r)
    out.sort(key=lambda r: r.get("at") or "", reverse=True)
    return {"total": len(out), "returned": min(limit, max(0, len(out) - offset)),
            "offset": offset, "rows": out[offset:offset + limit]}


def chunk(update_id: str, preview_dims: int = 12, uri: str | None = None) -> dict:
    """One chunk in full: its text, its metadata, and the front of its vector.

    Also reports whether the chunk's text still matches the update it came from,
    because that is the one divergence the id-and-count checks cannot see.
    """
    try:
        r = _backend().get(update_id)
    except Exception as e:
        return {"error": str(e)}
    if not r:
        return {"error": f"no chunk for update {update_id}"}
    r = dict(r)
    v = r.pop("vector", None)
    r.pop("_distance", None)
    if v is not None:
        v = [float(x) for x in v]
        r["dim"] = len(v)
        r["norm"] = round(math.sqrt(sum(x * x for x in v)), 6)
        r["vector_preview"] = [round(x, 5) for x in v[:preview_dims]]
    try:
        row = _con().execute("SELECT text FROM updates WHERE update_id = ?",
                             (update_id,)).fetchone()
        if row is None:
            r["source"] = "MISSING - this chunk cites an update that is not on file"
            r["matches_source"] = False
        else:
            r["source_text"] = row[0]
            r["matches_source"] = (row[0] or "") == (r.get("text") or "")
    except Exception:
        pass
    return r


def _trace_out(out: dict, retrieved: list[dict], reranked: list[dict],
               rerank_n: int, applied: bool) -> dict:
    """The single exit from retrieval_trace, so every path returns one shape.

    It had three returns and only the healthy one set `citations`, `promoted` and
    `dropped`. So the moment the hosted reranker answered

        HTTP 404: 404 page not found

    - which it does permanently, because there is no hosted reranking model in
    the catalogue - the degraded return handed back a dict its own consumers
    could not read, and scripts/test_review.py died on

        KeyError: 'citations'

    A fallback that changes the SHAPE of the result turns a degraded service into
    a crash somewhere else entirely, which is the worst way to learn about it. The
    difference between working and degraded belongs in a flag - `rerank_applied`,
    plus `rerank_error` when there is one - never in which keys exist.
    """
    out["reranked"] = reranked
    out["rerank_applied"] = applied
    kept = {r["update_id"] for r in reranked}
    out["promoted"] = [r for r in reranked if r.get("moved", 0) > 0]
    out["dropped"] = [r for r in retrieved[:rerank_n] if r["update_id"] not in kept]
    out["citations"] = [r["update_id"] for r in reranked]
    return out


def retrieval_trace(query: str, retrieve_n: int = RETRIEVE_N,
                    rerank_n: int = RERANK_N, ro_number: str | None = None,
                    uri: str | None = None) -> dict:
    """Both stages of a real search, so the reranker's contribution is visible.

    `search_updates` returns six passages and nothing about how they were chosen.
    This runs the same two calls - the same query embedding, the same wide
    retrieve, the same rerank - and keeps the intermediate stage, with each
    passage's movement between the two.

    It mirrors app/retrieval/index.py rather than sharing its code, so that it
    can keep the stage that `search` throws away. test_review.py asserts the two
    agree on the final citations; if they ever diverge, that test is what says so.
    """
    from app.nim.client import embed_query as nim_embed_query, rerank as nim_rerank
    out: dict[str, Any] = {"query": query, "retrieve_n": retrieve_n,
                           "rerank_n": rerank_n, "ro_number": ro_number}
    b = _backend()
    out.update({k: v for k, v in b.stats().items() if k in ("backend", "mode")})
    try:
        if not b.exists():
            return {**out, "error": f"no index at {b.uri} - build it first"}
    except Exception as e:
        return {**out, "error": str(e)}

    t0 = time.perf_counter()
    try:
        qv = nim_embed_query(query)
    except Exception as e:
        return {**out, "error": f"embedding failed - {type(e).__name__}: {e}"}
    out["embed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["query_dim"] = len(qv)

    t1 = time.perf_counter()
    try:
        hits = b.search(qv, k=retrieve_n, ro_number=ro_number)
    except Exception as e:
        return {**out, "error": f"vector search failed - {type(e).__name__}: {e}"}
    out["search_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    retrieved = []
    for i, h in enumerate(hits):
        retrieved.append({
            "rank": i + 1, "update_id": h.get("update_id"),
            "ro_number": h.get("ro_number"), "at": h.get("at"),
            "by": h.get("staff_name") or h.get("staff_id"),
            "vehicle": h.get("vehicle"), "text": h.get("text"),
            "vector_score": h.get("vector_score")})
    out["retrieved"] = retrieved

    if not retrieved or rerank_n <= 0:
        return _trace_out(out, retrieved, [], rerank_n, applied=False)

    t2 = time.perf_counter()
    try:
        ranked = nim_rerank(query, [r["text"] for r in retrieved], top_n=rerank_n)
    except Exception as e:
        out["rerank_error"] = f"{type(e).__name__}: {e}"
        # The vector order becomes the final order. Each passage is given the same
        # keys a reranked one carries, with the truth in the numbers: it came from
        # rank N and it moved nowhere.
        stood = []
        for r in retrieved[:rerank_n]:
            d = dict(r)
            d["vector_rank"] = d["rank"]
            d["moved"] = 0
            stood.append(d)
        return _trace_out(out, retrieved, stood, rerank_n, applied=False)
    out["rerank_ms"] = round((time.perf_counter() - t2) * 1000, 1)

    reranked = []
    for new_rank, r in enumerate(ranked, 1):
        src = dict(retrieved[r["index"]])
        src["rerank_score"] = r["score"]
        src["vector_rank"] = src.pop("rank")
        src["rank"] = new_rank
        src["moved"] = src["vector_rank"] - new_rank      # positive = promoted
        reranked.append(src)
    return _trace_out(out, retrieved, reranked, rerank_n, applied=True)


# ------------------------------------------------------------ the answer log

LOG_ANSWERS = os.environ.get("ASOIA_LOG_ANSWERS", "1") != "0"

_ANSWER_LOG_DDL = """
CREATE TABLE IF NOT EXISTS answer_log (
  answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, question TEXT NOT NULL, answer TEXT,
  route TEXT, composed TEXT, grounded INTEGER,
  tools TEXT, citations TEXT, warnings TEXT, seconds REAL
);
CREATE INDEX IF NOT EXISTS idx_answer_log_at ON answer_log(at);
"""


def ensure_answer_log(con: sqlite3.Connection | None = None) -> None:
    c = _con(con)
    c.executescript(_ANSWER_LOG_DDL)
    c.commit()


def log_answer(ans, seconds: float | None = None) -> None:
    """Record that an answer was given, and what it cited. Best effort, always.

    This is the only write in the review path, and it is on the hot path of every
    question, so it cannot fail loudly and it cannot be slow. Every exception is
    swallowed: an audit trail that can break answering is worse than no audit trail.
    Set ASOIA_LOG_ANSWERS=0 to turn it off.
    """
    if not LOG_ANSWERS:
        return
    try:
        c = dbm.connect()
        ensure_answer_log(c)
        c.execute(
            "INSERT INTO answer_log (at, question, answer, route, composed, grounded, "
            "tools, citations, warnings, seconds) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"),
             ans.question, ans.text, ans.route, ans.composed, int(bool(ans.grounded)),
             json.dumps([t.get("name") for t in (ans.tool_calls or [])]),
             json.dumps(ans.citations or []),
             json.dumps(ans.warnings or []),
             round(seconds, 3) if seconds is not None else None))
        c.commit()
    except Exception:
        pass


def answers(limit: int = 100, offset: int = 0, grounded: bool | None = None,
            con: sqlite3.Connection | None = None) -> dict:
    """What has been asked, what it cited, and whether it was grounded."""
    c = _con(con)
    try:
        ensure_answer_log(c)
    except Exception as e:
        return {"error": str(e), "total": 0, "answers": []}
    where, args = [], []
    if grounded is not None:
        where.append("grounded = ?"); args.append(int(grounded))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = c.execute(f"SELECT COUNT(*) FROM answer_log{clause}", args).fetchone()[0]
    rows = _rows(c.execute(
        f"SELECT * FROM answer_log{clause} ORDER BY answer_id DESC LIMIT ? OFFSET ?",
        (*args, limit, offset)))
    for r in rows:
        for k in ("tools", "citations", "warnings"):
            try:
                r[k] = json.loads(r[k]) if r[k] else []
            except (TypeError, ValueError):
                r[k] = []
        r["grounded"] = bool(r["grounded"])
    return {"total": total, "returned": len(rows), "offset": offset, "answers": rows}


def cited_by(update_id: str, con: sqlite3.Connection | None = None) -> dict:
    """Which answers cited this update. The traceability claim, from the other end."""
    c = _con(con)
    try:
        ensure_answer_log(c)
    except Exception as e:
        return {"error": str(e), "answers": []}
    rows = _rows(c.execute(
        "SELECT answer_id, at, question, route, grounded, citations FROM answer_log "
        "WHERE citations LIKE ? ORDER BY answer_id DESC LIMIT 100", (f'%"{update_id}"%',)))
    for r in rows:
        try:
            r["citations"] = json.loads(r["citations"])
        except (TypeError, ValueError):
            r["citations"] = []
        r["grounded"] = bool(r["grounded"])
    # LIKE can match a longer id that contains this one; confirm exactly.
    rows = [r for r in rows if update_id in r["citations"]]
    return {"update_id": update_id, "count": len(rows), "answers": rows}


def overview(con: sqlite3.Connection | None = None) -> dict:
    """One call for the top of the review screen."""
    c = _con(con)
    # A missing schema and an empty shop both return nothing from every COUNT. The
    # first draft of this reported a row of zeros for a database that did not exist,
    # which is the kind of confident wrong answer the ASR check was full of.
    try:
        have = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception as e:
        return {"database": f"unreadable - {type(e).__name__}: {e}"}
    missing = {"ros", "events", "updates", "staff"} - have
    if missing:
        return {"database": f"no schema - missing {', '.join(sorted(missing))}. "
                            f"Generate the dataset first (notebook 01, or "
                            f"scripts/verify_data.py to check one that exists).",
                "tables": sorted(have)}

    def n(sql):
        try:
            return c.execute(sql).fetchone()[0]
        except Exception:
            return None
    idx = index_stats()
    logged = 0
    try:
        ensure_answer_log(c)
        logged = c.execute("SELECT COUNT(*) FROM answer_log").fetchone()[0]
    except Exception:
        pass
    try:
        from app.state.clock import source as _clock_source
        clock = _clock_source()
    except Exception as e:
        clock = {"error": f"{type(e).__name__}: {e}"}
    return {
        "database": "ok",
        "clock": clock,
        "index_staleness": idx.get("staleness"),
        "repair_orders": n("SELECT COUNT(*) FROM ros"),
        "events": n("SELECT COUNT(*) FROM events"),
        "event_types_used": n("SELECT COUNT(DISTINCT type) FROM events"),
        "updates": n("SELECT COUNT(*) FROM updates"),
        "staff": n("SELECT COUNT(*) FROM staff"),
        "first_event": n("SELECT MIN(at) FROM events"),
        "last_event": n("SELECT MAX(at) FROM events"),
        "vector_rows": idx.get("rows"),
        "vector_dim": idx.get("dim"),
        "vector_uri": idx.get("uri"),
        "vector_error": idx.get("error"),
        "answers_logged": logged,
    }
