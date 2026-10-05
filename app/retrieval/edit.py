"""Editing the vector store, without letting it drift from the record.

WHY EDITS WRITE THROUGH

The vector store is DERIVED. Every chunk is one row of `updates`, embedded. Edit
a chunk's text in Milvus directly and it no longer matches the update it cites -
and nothing would catch it. `index_staleness()` compares ids and counts, not
text, and `check_grounding` checks figures in the answer against the tool
results, never the other way round. You would get answers quoting text that is
not in the database, which is the precise failure the citation checking in
`search_updates` exists to prevent.

So an edit changes the SOURCE and re-embeds:

    updates.text  ->  re-embed that one chunk  ->  upsert into the store

and the old text is kept, because this project does not overwrite history. An
edit is a correction, and a correction that hides what it corrected is worse than
the error.

THE AUDIT TRAIL IS ITS OWN TABLE, NOT THE EVENT LOG

The first version of this wrote edits into `events`. That table is the repair
order LIFECYCLE log: `Event.from_row()` parses every row's type through the
`EventType` enum and `fold()` consumes the result, so three new type strings took
out seven of the fourteen answer checks and every read of an affected repair
order with

    ValueError: 'UPDATE_TEXT_EDITED' is not a valid EventType

The docstring above already said these are not lifecycle events. They now live in
`index_audit`, where they cannot reach the fold, and where nothing has to pretend
a data correction is something that happened in the workshop.

WHAT IS AND IS NOT ALLOWED

  edit_text      change an update's wording, re-embed, record the before/after
  reindex        re-embed a chunk from the current record, no text change
  exclude        drop a chunk from the index only; the update stays on file
  restore        put an excluded chunk back

There is no "add a chunk". A chunk exists because an update exists; new updates
arrive through the Technician Update tab and the ingestion pipeline, which apply
the state machine and the conflict checks. A back door into the index would
bypass both.

Deleting an UPDATE is also not offered. The log is append-only; removing a
technician's note is not an edit, it is a rewrite of what happened. `exclude`
covers the real need - a chunk that should not be retrievable - and is
reversible.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from app.state import db as dbm

EDIT_EVENT = "UPDATE_TEXT_EDITED"
EXCLUDE_EVENT = "UPDATE_INDEX_EXCLUDED"
RESTORE_EVENT = "UPDATE_INDEX_RESTORED"

_DDL = """
CREATE TABLE IF NOT EXISTS index_exclusions (
  update_id TEXT PRIMARY KEY,
  at TEXT NOT NULL,
  actor_id TEXT,
  reason TEXT
);
CREATE TABLE IF NOT EXISTS index_audit (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  update_id TEXT NOT NULL,
  ro_number TEXT,
  kind TEXT NOT NULL,
  at TEXT NOT NULL,
  actor_id TEXT,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_index_audit_update ON index_audit(update_id, at);
"""


def _con(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return con if con is not None else dbm.connect()


def ensure_tables(con: sqlite3.Connection | None = None) -> None:
    c = _con(con)
    c.executescript(_DDL)
    c.commit()


def _record(con, update_id: str, kind: str, actor_id: str, payload: dict) -> int | None:
    """Append to the edit audit trail. Never raises - an edit must not fail over its log.

    Deliberately NOT the `events` table. That one is the repair order lifecycle
    log: every row is parsed through `EventType` and folded into state, so an
    unknown type string breaks every read of that repair order. A data
    correction is not something that happened to the vehicle.
    """
    try:
        ensure_tables(con)
        row = con.execute("SELECT ro_number FROM updates WHERE update_id = ?",
                          (update_id,)).fetchone()
        from app.state.clock import event_time
        cur = con.execute(
            "INSERT INTO index_audit (update_id, ro_number, kind, at, actor_id, "
            "payload) VALUES (?,?,?,?,?,?)",
            (update_id, row[0] if row else None, kind,
             event_time().isoformat(timespec="seconds"), actor_id,
             json.dumps(payload, default=str)))
        con.commit()
        return cur.lastrowid
    except Exception:
        return None


def get_update(update_id: str, con: sqlite3.Connection | None = None) -> dict | None:
    c = _con(con)
    r = c.execute(
        "SELECT u.update_id, u.ro_number, u.staff_id, u.at, u.shift, u.text, "
        "COALESCE(s.name, u.staff_id) AS staff_name FROM updates u "
        "LEFT JOIN staff s ON s.staff_id = u.staff_id WHERE u.update_id = ?",
        (update_id,)).fetchone()
    return dict(r) if r else None


def edit_text(update_id: str, new_text: str, actor_id: str = "REVIEWER",
              con: sqlite3.Connection | None = None) -> dict:
    """Change an update's text, re-embed its chunk, and record what changed."""
    c = _con(con)
    cur = get_update(update_id, c)
    if not cur:
        return {"ok": False, "error": f"no update {update_id}"}
    new_text = (new_text or "").strip()
    if not new_text:
        return {"ok": False, "error": "the text cannot be empty - use exclude "
                                      "to take a chunk out of the index"}
    if new_text == cur["text"]:
        return {"ok": True, "changed": False, "update_id": update_id,
                "note": "the text is unchanged; nothing was written"}

    before = cur["text"]
    try:
        c.execute("UPDATE updates SET text = ? WHERE update_id = ?",
                  (new_text, update_id))
        c.commit()
    except Exception as e:
        return {"ok": False, "error": f"could not write the update: "
                                      f"{type(e).__name__}: {e}"}

    ev = _record(c, update_id, EDIT_EVENT, actor_id,
                 {"before": before, "after": new_text})

    # Re-embed. If this fails the record is already correct and the index is
    # stale by exactly one chunk, which index_staleness() will report - so say so
    # rather than rolling back a correction the user asked for.
    try:
        from app.retrieval.index import reindex
        r = reindex([update_id], con=c)
        reindexed = bool(r.get("reindexed"))
        err = r.get("error")
    except Exception as e:
        reindexed, err = False, f"{type(e).__name__}: {e}"

    out = {"ok": True, "changed": True, "update_id": update_id,
           "before": before, "after": new_text, "audit_id": ev,
           "reindexed": reindexed}
    if not reindexed:
        out["warning"] = (
            f"the record was updated but the chunk could not be re-embedded "
            f"({err}). The index now disagrees with the database for this one "
            f"update; /health and the review Overview will report it. Rebuild "
            f"with app.retrieval.index.reindex(['{update_id}']) once the "
            f"embedding endpoint is reachable.")
    return out


def reindex_one(update_id: str, con: sqlite3.Connection | None = None) -> dict:
    """Re-embed a chunk from the current record. No text change."""
    c = _con(con)
    if not get_update(update_id, c):
        return {"ok": False, "error": f"no update {update_id}"}
    try:
        from app.retrieval.index import reindex
        r = reindex([update_id], con=c)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if r.get("error"):
        return {"ok": False, "error": r["error"]}
    return {"ok": True, "update_id": update_id, "dim": r.get("dim")}


def exclude(update_id: str, reason: str = "", actor_id: str = "REVIEWER",
            con: sqlite3.Connection | None = None) -> dict:
    """Remove a chunk from the index. The update itself stays on file."""
    c = _con(con)
    if not get_update(update_id, c):
        return {"ok": False, "error": f"no update {update_id}"}
    ensure_tables(c)
    try:
        from app.retrieval.backend import backend
        backend().delete([update_id])
    except Exception as e:
        return {"ok": False, "error": f"could not remove it from the index: "
                                      f"{type(e).__name__}: {e}"}
    c.execute("INSERT OR REPLACE INTO index_exclusions (update_id, at, actor_id, "
              "reason) VALUES (?,?,?,?)",
              (update_id, datetime.now().isoformat(timespec="seconds"), actor_id,
               reason))
    c.commit()
    ev = _record(c, update_id, EXCLUDE_EVENT, actor_id, {"reason": reason})
    return {"ok": True, "update_id": update_id, "audit_id": ev,
            "note": "the update is still on file; only its chunk was removed. "
                    "A full rebuild would bring it back unless it stays excluded."}


def restore(update_id: str, actor_id: str = "REVIEWER",
            con: sqlite3.Connection | None = None) -> dict:
    """Put an excluded chunk back into the index."""
    c = _con(con)
    ensure_tables(c)
    if not get_update(update_id, c):
        return {"ok": False, "error": f"no update {update_id}"}
    try:
        from app.retrieval.index import reindex
        r = reindex([update_id], con=c)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if r.get("error"):
        return {"ok": False, "error": r["error"]}
    c.execute("DELETE FROM index_exclusions WHERE update_id = ?", (update_id,))
    c.commit()
    ev = _record(c, update_id, RESTORE_EVENT, actor_id, {})
    return {"ok": True, "update_id": update_id, "audit_id": ev}


def exclusions(con: sqlite3.Connection | None = None) -> list[dict]:
    c = _con(con)
    ensure_tables(c)
    return [dict(r) for r in c.execute(
        "SELECT update_id, at, actor_id, reason FROM index_exclusions ORDER BY at DESC")]


def history(update_id: str, con: sqlite3.Connection | None = None) -> list[dict]:
    """Every edit, exclusion and restore recorded against one update."""
    c = _con(con)
    ensure_tables(c)
    rows = []
    for r in c.execute(
            "SELECT audit_id, kind, at, actor_id, payload FROM index_audit "
            "WHERE update_id = ? ORDER BY at DESC, audit_id DESC", (update_id,)):
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"])
        except (TypeError, ValueError):
            pass
        rows.append(d)
    return rows


def recent_edits(limit: int = 100, con: sqlite3.Connection | None = None) -> list[dict]:
    """The whole audit trail, newest first - for the review screen."""
    c = _con(con)
    ensure_tables(c)
    rows = []
    for r in c.execute(
            "SELECT audit_id, update_id, ro_number, kind, at, actor_id, payload "
            "FROM index_audit ORDER BY audit_id DESC LIMIT ?", (limit,)):
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"])
        except (TypeError, ValueError):
            pass
        rows.append(d)
    return rows
