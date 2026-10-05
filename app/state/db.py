"""SQLite access. One file, no server - deploys anywhere, including a CPU box."""
from __future__ import annotations
import sqlite3, json, os, threading
from pathlib import Path
from datetime import datetime
from app.state.events import Event

DEFAULT_DB = os.environ.get("ASOIA_DB", "data/generated/service.sqlite")
SCHEMA = Path(__file__).with_name("schema.sql")


# SQLite connections cannot cross threads, and Gradio runs handlers in a worker
# pool - so hand each thread its own connection to the same file.
_local = threading.local()


def connect(path: str | None = None) -> sqlite3.Connection:
    p = str(Path(path or DEFAULT_DB))
    cache = getattr(_local, "conns", None)
    if cache is None:
        cache = _local.conns = {}
    con = cache.get(p)
    if con is not None:
        return con
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, detect_types=0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    cache[p] = con
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA.read_text())
    con.commit()


def insert_events(con: sqlite3.Connection, events: list[Event]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO events "
        "(event_id,ro_number,type,at,actor_id,shift,source_update_id,payload) "
        "VALUES (?,?,?,?,?,?,?,?)", [e.to_row() for e in events])


def events_for_ro(con: sqlite3.Connection, ro_number: str) -> list[Event]:
    rows = con.execute(
        "SELECT event_id,ro_number,type,at,actor_id,shift,source_update_id,payload "
        "FROM events WHERE ro_number=? ORDER BY at, event_id", (ro_number,)).fetchall()
    return [Event.from_row(tuple(r)) for r in rows]


def get_ro(con: sqlite3.Connection, ro_number: str) -> dict | None:
    r = con.execute("SELECT * FROM ros WHERE ro_number=?", (ro_number,)).fetchone()
    return dict(r) if r else None


def all_ro_numbers(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute("SELECT ro_number FROM ros ORDER BY ro_number")]
