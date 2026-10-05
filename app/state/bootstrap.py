"""Make sure there is a dataset, without making anyone run a separate step.

Generating the full default dataset - 400 repair orders, 10,715 events, 1,882
updates, 4.5 MB - takes **0.1 seconds**, and because it simulates relative to the
clock at generation time, the window always ends now. At that price there is no
argument for a manual step that can be forgotten, and every argument against one:
a missing dataset used to surface as an empty dashboard rather than as a message
saying what to run.

It only ever fires when there is NO data. A database with rows in it is never
touched, so this cannot overwrite anything.

    ASOIA_AUTOGEN=0     never generate; report the empty database instead
    ASOIA_GEN_ROS       how many repair orders (default 400)
    ASOIA_GEN_DAYS      how many days of history (default 14)

WHAT IT DELIBERATELY DOES NOT DO

It does not build the vector index. That means embedding every update through
nv-embedqa, which needs a NIM up and takes orders of magnitude longer than the
data itself - so it cannot be a startup cost, and silently doing it would make a
first launch hang with no explanation. The index is a separate, explicit step,
and `app.review.store.index_staleness()` is what notices when it no longer
matches the data.
"""
from __future__ import annotations
import os
import time


def _db_path(con) -> str | None:
    """The file this connection is actually attached to.

    Not `build_dataset`'s default, and not ASOIA_DB read fresh from the
    environment. The first version of this checked one database and generated
    into another: `dbm.connect()` honours ASOIA_DB, `build_dataset()` defaults to
    the literal "data/generated/service.sqlite", so pointing the app at a scratch
    database made the bootstrap find it empty and then overwrite the REAL one -
    400 repair orders replaced by a fresh 12, silently, at startup. The docstring
    promised "a database with rows in it is never touched" while the code did
    exactly that.

    Asking the connection removes the possibility: the file that was checked and
    the file that gets written are the same file by construction.
    """
    try:
        row = con.execute("PRAGMA database_list").fetchone()
        return row[2] if row and row[2] else None
    except Exception:
        return None


def _has_data(con) -> bool:
    try:
        have = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "ros" not in have:
            return False
        return con.execute("SELECT COUNT(*) FROM ros").fetchone()[0] > 0
    except Exception:
        return False


def _evict(dbm) -> None:
    """Drop this thread's cached connections after generating.

    `build_dataset` closes the connection it used, and `dbm.connect()` caches one
    per thread - so generating leaves the cache holding a CLOSED connection and
    every query afterwards raises "Cannot operate on a closed database". On a
    real startup that means the app generates its data and is then dead, which is
    a far worse failure than the empty dashboard this was meant to fix.

    Evicting is enough: the next connect() opens a fresh one against a file that
    now has a schema.
    """
    try:
        cache = getattr(dbm._local, "conns", None)
        if cache:
            cache.clear()
    except Exception:
        pass


def ensure_dataset(verbose: bool = True) -> dict:
    """Generate the dataset if, and only if, there is none. Never raises."""
    from app.state import db as dbm
    try:
        con = dbm.connect()
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    if _has_data(con):
        try:
            n = con.execute("SELECT COUNT(*) FROM ros").fetchone()[0]
        except Exception:
            n = None
        return {"status": "present", "repair_orders": n}

    if (os.environ.get("ASOIA_AUTOGEN") or "1") == "0":
        return {"status": "empty",
                "hint": "ASOIA_AUTOGEN=0, so nothing was generated. Run "
                        ".venv/bin/python -m app.data.generate"}

    try:
        from app.data.generate import build_dataset
        target = _db_path(con)
        if not target:
            return {"status": "error",
                    "error": "could not determine which database file to write"}
        kw = {"db_path": target}
        if os.environ.get("ASOIA_GEN_ROS"):
            kw["n_ros"] = int(os.environ["ASOIA_GEN_ROS"])
        if os.environ.get("ASOIA_GEN_DAYS"):
            kw["days"] = int(os.environ["ASOIA_GEN_DAYS"])
        if verbose:
            print(f"[bootstrap] no dataset in {target} - generating one "
                  f"(about a tenth of a second)")
        t0 = time.time()
        r = build_dataset(**kw)
        el = time.time() - t0
        _evict(dbm)
        if verbose:
            print(f"[bootstrap] generated {r['ros']} repair orders, "
                  f"{r['events']} events, {r['updates']} updates in {el:.1f}s")
            print("[bootstrap] the vector index is NOT built - semantic search "
                  "needs:  .venv/bin/python -c "
                  "'from app.retrieval.index import build; print(build())'")
        # Prove the app can still talk to the database it just made. If this
        # fails the process is unusable, and it should say so now rather than on
        # the first question somebody asks.
        try:
            n = dbm.connect().execute("SELECT COUNT(*) FROM ros").fetchone()[0]
        except Exception as e:
            return {"status": "error", "generated": True,
                    "error": f"generated, but the database is unreadable "
                             f"afterwards: {type(e).__name__}: {e}"}
        return {"status": "generated", "seconds": round(el, 2),
                "repair_orders": n, **r}
    except Exception as e:
        if verbose:
            print(f"[bootstrap] could not generate a dataset: "
                  f"{type(e).__name__}: {e}")
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}
