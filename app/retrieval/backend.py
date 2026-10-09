"""One interface over the vector store, so nothing else knows which one it is.

Milvus is the default. LanceDB is still here because it was the store for the
first twenty-six passes and a migration you cannot reverse is not a migration.

    VECTOR_BACKEND   "milvus" (default) or "lancedb"
    ASOIA_MILVUS_URI   a file path  -> embedded Milvus Lite, no server
                       http://host:19530 -> a Milvus standalone/cluster
    ASOIA_MILVUS_COLLECTION  default "updates"

NOT `MILVUS_URI`: pymilvus reads that name itself, at import, and rejects
anything that is not `http[s]://host:port` - so setting it to a Milvus Lite file
path makes `import pymilvus` raise before any of this runs. The ASOIA_ prefix the
rest of the project uses avoids the collision as well as being consistent.
    LANCE_URI        unchanged, for the lancedb backend

The URI decides whether Milvus runs embedded or against a server, exactly the way
`app/nim/client.py` decides local NIM versus hosted endpoint. The deployment uses
the SERVER - `ASOIA_MILVUS_URI=http://localhost:19530`, started by
`scripts/start_milvus.sh`. Embedded needs nothing installed, which makes it a
useful fallback and a dangerous default: a process that never read `.env` opens
the embedded file instead and reports its stale contents with a straight face.
That is the decoy `scripts/store_report.py` warns about and `scripts/
build_index.py` exists to avoid. The schema is identical either way, so the
difference is invisible until you notice you indexed the wrong store.

WHY THE INTERFACE IS THIS SHAPE

`scan()` returns rows WITHOUT vectors and `get()` returns one row WITH its
vector. That split is not tidiness: a 1024-float vector per row is about 8 KB, so
listing two thousand chunks to read their text used to move 15 MB of numbers that
nothing looked at. The review browser calls `scan`, the detail view calls `get`.

Every method returns plain dicts with the same keys regardless of backend, so
`app/review/store.py` and `app/retrieval/index.py` contain no per-store branching.
"""
from __future__ import annotations

import json
import math
import os
import threading
from typing import Any

# The fields carried for every chunk, besides the vector itself. Kept explicit so
# both backends agree, and so a schema change is one list rather than a search.
FIELDS = ["update_id", "ro_number", "staff_id", "staff_name", "at", "shift",
          "text", "vehicle", "category", "concern", "vin"]

COLLECTION = os.environ.get("ASOIA_MILVUS_COLLECTION", "updates")


def _default_milvus_uri() -> str:
    return os.environ.get("ASOIA_MILVUS_URI", "data/generated/milvus.db")


class BackendError(RuntimeError):
    """Raised with an actionable message; callers turn it into a reported error."""


# --------------------------------------------------------------------- Milvus

class MilvusBackend:
    name = "milvus"

    def __init__(self, uri: str | None = None, collection: str | None = None):
        self.uri = uri or _default_milvus_uri()
        self.collection = collection or COLLECTION
        self._client = None
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def mode(self) -> str:
        return "server" if self.uri.startswith(("http://", "https://")) else "embedded"

    def client(self):
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                from pymilvus import MilvusClient
            except ImportError:
                raise BackendError(
                    "pymilvus is not installed - the Milvus backend needs it. "
                    "uv pip install --python .venv 'pymilvus>=2.4' milvus-lite"
                ) from None
            if self.mode == "embedded":
                os.makedirs(os.path.dirname(os.path.abspath(self.uri)) or ".",
                            exist_ok=True)
            try:
                self._client = MilvusClient(uri=self.uri)
            except Exception as e:
                raise BackendError(
                    f"could not open Milvus at {self.uri} "
                    f"({type(e).__name__}: {e})") from e
            return self._client

    def _load(self):
        """Milvus will not read a collection until it is loaded into memory.

        A process that did not build the index finds the collection in state
        'released', and `query` then raises - or, through the review layer's
        try/except, comes back as an empty store. That reads as "the index is
        empty" rather than "this process has not loaded it", which is the worst
        kind of wrong answer. Loading is idempotent and cheap after the first
        call, so every read goes through here.
        """
        if self._loaded:
            return
        try:
            c = self.client()
            if self.collection in c.list_collections():
                c.load_collection(self.collection)
                self._loaded = True
        except Exception:
            pass

    def exists(self) -> bool:
        try:
            return self.collection in self.client().list_collections()
        except BackendError:
            raise
        except Exception:
            return False

    def create(self, dim: int) -> None:
        """Drop and recreate. Building the index is a batch job, not an upsert loop."""
        c = self.client()
        if self.collection in c.list_collections():
            c.drop_collection(self.collection)
        from pymilvus import DataType
        schema = c.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("pk", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
        # VARCHAR needs a max length; text is the only field that can be long.
        schema.add_field("update_id", DataType.VARCHAR, max_length=64)
        schema.add_field("ro_number", DataType.VARCHAR, max_length=32)
        schema.add_field("staff_id", DataType.VARCHAR, max_length=32)
        schema.add_field("staff_name", DataType.VARCHAR, max_length=128)
        schema.add_field("at", DataType.VARCHAR, max_length=40)
        schema.add_field("shift", DataType.VARCHAR, max_length=24)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        schema.add_field("vehicle", DataType.VARCHAR, max_length=128)
        schema.add_field("category", DataType.VARCHAR, max_length=64)
        schema.add_field("concern", DataType.VARCHAR, max_length=2048)
        schema.add_field("vin", DataType.VARCHAR, max_length=32)

        index_params = c.prepare_index_params()
        # COSINE because the embeddings are normalised and the reranker downstream
        # cares about ordering, not absolute distance. AUTOINDEX lets Milvus pick
        # FLAT for a collection this size, which is exact rather than approximate -
        # at two thousand rows an ANN index would trade recall for nothing.
        index_params.add_index(field_name="vector", index_type="AUTOINDEX",
                               metric_type="COSINE")
        # Strong consistency. Milvus server is eventually consistent by default,
        # so a read straight after an upsert can return the OLD row - which made
        # an edit report "re-embedded" while the index still held the previous
        # text, and left index_staleness reporting drift that was not real.
        # Milvus Lite is synchronous in-process, so this was invisible until the
        # store moved to a server. At two thousand rows the cost is nothing.
        c.create_collection(collection_name=self.collection, schema=schema,
                            index_params=index_params,
                            consistency_level="Strong")
        self._loaded = False

    @staticmethod
    def _pk(update_id: str) -> int:
        """A stable 63-bit primary key from the update id.

        Milvus wants an int64 primary key and the natural key is a string. Hashing
        keeps upsert idempotent - re-indexing one chunk replaces it rather than
        duplicating it - without carrying a separate id map that could drift.
        """
        import hashlib
        return int(hashlib.sha1(update_id.encode()).hexdigest()[:15], 16)

    def upsert(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        c = self.client()
        payload = []
        for r in rows:
            d = {"pk": self._pk(r["update_id"]), "vector": list(r["vector"])}
            for f in FIELDS:
                v = r.get(f)
                d[f] = "" if v is None else str(v)
            payload.append(d)
        c.upsert(collection_name=self.collection, data=payload)
        return len(payload)

    def flush(self) -> None:
        """Seal the growing segment so the row count is readable.

        Milvus counts only sealed segments, so a freshly built collection
        reports row_count 0 while `query` happily returns rows from it. The
        store report and Attu both read the count, so a build that had just
        written 1,857 rows showed `updates 0 @2048d` - which reads as a failed
        build rather than an unflushed one.

        Called by `build()` only. Not by `reindex()`: that writes one row after
        an edit, and flushing per edit seals a segment per row.
        """
        self.client().flush(self.collection)

    def scan(self) -> list[dict]:
        """Every row, without vectors."""
        self._load()
        c = self.client()
        # Strong here too: the staleness check compares this against the
        # database, and a stale read invents drift that does not exist.
        out = c.query(collection_name=self.collection, filter="pk >= 0",
                      output_fields=FIELDS, limit=16384,
                      consistency_level="Strong")
        return [dict(r) for r in out]

    def get(self, update_id: str) -> dict | None:
        self._load()
        c = self.client()
        safe = update_id.replace('"', '')
        rows = c.query(collection_name=self.collection,
                       filter=f'update_id == "{safe}"',
                       output_fields=FIELDS + ["vector"], limit=1,
                       consistency_level="Strong")
        return dict(rows[0]) if rows else None

    def search(self, vector: list[float], k: int,
               ro_number: str | None = None) -> list[dict]:
        self._load()
        c = self.client()
        flt = f'ro_number == "{ro_number}"' if ro_number else ""
        try:
            res = c.search(collection_name=self.collection, data=[list(vector)],
                           limit=k, filter=flt, output_fields=FIELDS,
                           search_params={"metric_type": "COSINE"})
        except Exception as e:
            # A width mismatch arrives from pymilvus as prose about vector
            # dimensions, several frames deep, naming neither the embedder nor
            # the fix. It means exactly one thing here - the index was built by
            # a different embedder than the one asking - so it is worth saying
            # that instead of passing the original up.
            msg = str(e).lower()
            if "dim" in msg and ("match" in msg or "inconsistent" in msg
                                 or "expected" in msg):
                raise BackendError(
                    f"the query vector is {len(vector)}-dimensional and the "
                    f"'{self.collection}' collection is not. The index was "
                    f"built by a different embedder - NIM_MODE was changed "
                    f"without rebuilding it. Rebuild:\n"
                    f"  .venv/bin/python -c 'from app.retrieval.index import "
                    f"build; print(build())'") from e
            raise
        hits = []
        for h in (res[0] if res else []):
            row = dict(h.get("entity") or {})
            # COSINE distance in Milvus is a similarity: higher is closer. The rest
            # of the codebase reads `vector_score` as "what the vector stage said",
            # and never compares it across backends, so it is passed through as is.
            row["vector_score"] = h.get("distance")
            hits.append(row)
        return hits

    def delete(self, update_ids: list[str]) -> int:
        if not update_ids:
            return 0
        c = self.client()
        c.delete(collection_name=self.collection,
                 ids=[self._pk(u) for u in update_ids])
        return len(update_ids)

    def sample_vectors(self, n: int = 64) -> list[dict]:
        """A few rows WITH their vectors, for the health check.

        Separate from scan() because scan() deliberately drops the vector column;
        a zero-norm vector is a failed embedding and nothing that reads text
        would ever notice one.
        """
        self._load()
        c = self.client()
        return [dict(r) for r in c.query(
            collection_name=self.collection, filter="pk >= 0",
            output_fields=["update_id", "vector"], limit=max(1, n))]

    def count(self) -> int | None:
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

    def dim(self) -> int | None:
        try:
            desc = self.client().describe_collection(self.collection)
            for f in desc.get("fields", []):
                if f.get("name") == "vector":
                    return (f.get("params") or {}).get("dim")
        except Exception:
            pass
        return None

    def stats(self) -> dict:
        return {"backend": "milvus", "mode": self.mode, "uri": self.uri,
                "collection": self.collection}


# -------------------------------------------------------------------- LanceDB

class LanceBackend:
    """The store used up to pass 26. Kept so the migration is reversible."""
    name = "lancedb"

    def __init__(self, uri: str | None = None, table: str | None = None):
        self.uri = uri or os.environ.get("LANCE_URI", "data/generated/lancedb")
        self.collection = table or "updates"

    mode = "embedded"

    def _tbl(self):
        try:
            import lancedb
        except ImportError:
            raise BackendError(
                "lancedb is not installed. uv pip install --python .venv lancedb"
            ) from None
        db = lancedb.connect(self.uri)
        if self.collection not in db.table_names():
            raise BackendError(
                f"no '{self.collection}' table at {self.uri} - build the index first")
        return db.open_table(self.collection)

    def exists(self) -> bool:
        try:
            self._tbl()
            return True
        except Exception:
            return False

    def create(self, dim: int) -> None:      # lancedb creates on first write
        self._pending_dim = dim

    def upsert(self, rows: list[dict]) -> int:
        import lancedb
        db = lancedb.connect(self.uri)
        data = [dict(r) for r in rows]
        if self.collection in db.table_names():
            tbl = db.open_table(self.collection)
            ids = [r["update_id"] for r in data]
            if ids:
                quoted = ",".join("'" + i.replace("'", "") + "'" for i in ids)
                try:
                    tbl.delete(f"update_id IN ({quoted})")
                except Exception:
                    pass
            tbl.add(data)
        else:
            db.create_table(self.collection, data=data)
        return len(data)

    def drop(self) -> None:
        import lancedb
        db = lancedb.connect(self.uri)
        if self.collection in db.table_names():
            db.drop_table(self.collection)

    def scan(self) -> list[dict]:
        tbl = self._tbl()
        try:
            t = tbl.to_arrow()
            if "vector" in t.column_names:
                t = (t.drop_columns(["vector"]) if hasattr(t, "drop_columns")
                     else t.drop(["vector"]))
            return t.to_pylist()
        except Exception:
            rows = tbl.search().limit(100000).to_list()
            for r in rows:
                r.pop("vector", None)
            return rows

    def get(self, update_id: str) -> dict | None:
        tbl = self._tbl()
        safe = update_id.replace("'", "")
        try:
            rows = tbl.search().where(f"update_id = '{safe}'").limit(1).to_list()
        except Exception:
            rows = [r for r in tbl.search().limit(100000).to_list()
                    if r.get("update_id") == update_id]
        return dict(rows[0]) if rows else None

    def search(self, vector: list[float], k: int,
               ro_number: str | None = None) -> list[dict]:
        q = self._tbl().search(vector).limit(k)
        if ro_number:
            q = q.where(f"ro_number = '{ro_number}'")
        hits = []
        for h in q.to_list():
            h.pop("vector", None)
            h["vector_score"] = h.pop("_distance", None)
            hits.append(h)
        return hits

    def delete(self, update_ids: list[str]) -> int:
        if not update_ids:
            return 0
        quoted = ",".join("'" + i.replace("'", "") + "'" for i in update_ids)
        self._tbl().delete(f"update_id IN ({quoted})")
        return len(update_ids)

    def sample_vectors(self, n: int = 64) -> list[dict]:
        rows = self._tbl().search().limit(max(1, n)).to_list()
        return [{"update_id": r.get("update_id"), "vector": r.get("vector")}
                for r in rows]

    def count(self) -> int | None:
        try:
            return self._tbl().count_rows()
        except Exception:
            return None

    def dim(self) -> int | None:
        try:
            one = self._tbl().search().limit(1).to_list()
            v = one[0].get("vector") if one else None
            return len(v) if v is not None else None
        except Exception:
            return None

    def flush(self) -> None:
        """Nothing to do: LanceDB writes are visible as soon as they return."""

    def stats(self) -> dict:
        return {"backend": "lancedb", "mode": "embedded", "uri": self.uri,
                "collection": self.collection}


# ------------------------------------------------------------------ selection

_cached: dict[str, Any] = {}


def backend(name: str | None = None):
    """The configured store. Cached, because opening Milvus Lite is not free."""
    which = (name or os.environ.get("VECTOR_BACKEND", "milvus")).lower()
    if which not in ("milvus", "lancedb"):
        raise BackendError(
            f"VECTOR_BACKEND={which!r} is not a store. Use 'milvus' or 'lancedb'.")
    if which not in _cached:
        _cached[which] = MilvusBackend() if which == "milvus" else LanceBackend()
    return _cached[which]


def reset():
    """Forget the cached backend - for tests, and after changing the URI."""
    _cached.clear()


def norm(vector) -> float:
    return math.sqrt(sum(float(x) * float(x) for x in vector))
