#!/usr/bin/env python
"""Print every store the stack keeps, where it lives, and how to open it.

The agent's own UI deliberately shows none of this - an operator's view of the
system of record does not belong in a service advisor's chat window. This is
that view instead: stack.sh prints it on `up` and `restart`, and it also stands
alone as `scripts/stack.sh stores` at any time.

It loads .env the way scripts/stack.sh does, through scripts._env, because that
is the only way to report the store that is actually serving answers. Measured
in a shell that never read .env, this script would open the embedded Milvus Lite
file in data/generated/ instead of the Milvus the API is talking to, and would
report that store's row count with a straight face. That mistake has already
been made here once, and it cost an afternoon.

Two promises hold for every section:

  nothing raises   - a store that is down prints one line saying so, because a
                     report that dies on its first unreachable backend is worth
                     less than no report at all.
  nothing writes   - SQLite is opened mode=ro. An operator asking what is in the
                     system of record must not be able to damage it by asking.
"""
from __future__ import annotations

import glob
import json
import os
import socket
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")


def _load_env() -> list[str]:
    """Load .env the way scripts/stack.sh does, through scripts._env.

    Tolerant of that module's entry point moving. This import has to happen
    before any store lookup below, and a report that cannot start is worth less
    than one that runs and says the environment was never loaded - so a missing
    or renamed loader degrades to [] rather than killing the process.
    """
    try:
        import scripts._env as m  # noqa: E402 - must precede any store lookup
    except Exception:
        return []
    for attr in ("load", "load_env"):
        fn = getattr(m, attr, None)
        if callable(fn):
            try:
                r = fn()
            except Exception:
                return []
            if isinstance(r, (list, tuple, set)):
                return sorted(str(x) for x in r)
            if isinstance(r, dict):
                return sorted(str(k) for k in r)
            return []
    return []


_LOADED = _load_env()

# Defaults mirror the app's own: app/state/db.py reads ASOIA_DB with this
# fallback, so the report follows the app rather than restating it.
DB_PATH = os.environ.get("ASOIA_DB", "data/generated/service.sqlite")
MILVUS_URI = os.environ.get("ASOIA_MILVUS_URI", "")
LITE_PATH = "data/generated/milvus.db"

# Loopback only. The standing rule on this box is that 19530, 8080, 3000 and
# 8888 do not leave it; an admin UI with write access has no business being
# laxer than the service it administers.
ATTU_PORT = int(os.environ.get("ASOIA_ATTU_PORT", "8101"))
SQLITEWEB_PORT = int(os.environ.get("ASOIA_SQLITEWEB_PORT", "8102"))
# No default host. This used to be "capstone-poc", which was the GPU box;
# that box was deleted and the report went on printing a tunnel command to
# a machine that does not exist. When the stack runs where you are - which
# is now the normal case - there is nothing to tunnel. Set ASOIA_SSH_ALIAS
# to print the tunnel line for a remote box.
SSH_ALIAS = os.environ.get("ASOIA_SSH_ALIAS", "")


def _n(x) -> str:
    """Thousands separators, because 1949 and 19490 look alike at a glance."""
    try:
        return f"{int(x):,}"
    except Exception:
        return str(x)


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# sqlite - the system of record


def sqlite_section() -> dict:
    out: dict = {"path": DB_PATH, "ok": False, "tables": [], "rows": 0}
    p = Path(DB_PATH)
    if not p.exists():
        out["error"] = "not present"
        return out
    out["bytes"] = p.stat().st_size
    try:
        # mode=ro: a read-only handle cannot be the cause of a corrupt store.
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2.0)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            try:
                # Table names come from sqlite_master, not from a caller, so
                # there is no untrusted text in this statement.
                cnt = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except Exception:
                cnt = None
            out["tables"].append({"name": name, "rows": cnt})
            if isinstance(cnt, int):
                out["rows"] += cnt
        out["ok"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        con.close()
    return out


# --------------------------------------------------------------------------
# milvus - the vector store


def _milvus_uri() -> tuple[str, str]:
    """Return (uri, how_we_got_it). The second value is the point of this.

    A report that prints a row count without saying which store it came from is
    how the wrong store gets believed.
    """
    if MILVUS_URI:
        return MILVUS_URI, "ASOIA_MILVUS_URI"
    if Path(LITE_PATH).exists():
        return LITE_PATH, f"fallback to embedded Milvus Lite ({LITE_PATH})"
    return "", "unset"


def milvus_section() -> dict:
    uri, how = _milvus_uri()
    out: dict = {"uri": uri, "source": how, "ok": False, "collections": []}
    if not uri:
        out["error"] = "no ASOIA_MILVUS_URI and no embedded file"
        return out
    try:
        from pymilvus import MilvusClient
    except Exception as e:
        out["error"] = f"pymilvus unavailable: {type(e).__name__}: {e}"
        return out
    try:
        client = MilvusClient(uri=uri if "://" in uri or uri.endswith(".db")
                              else "http://" + uri)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    try:
        for name in client.list_collections():
            row: dict = {"name": name}
            try:
                row["rows"] = client.get_collection_stats(name).get("row_count")
            except Exception:
                row["rows"] = None
            try:
                for f in client.describe_collection(name).get("fields", []):
                    dim = (f.get("params") or {}).get("dim")
                    if dim:
                        row["dim"] = dim
                        break
            except Exception:
                pass
            out["collections"].append(row)
        out["ok"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def lite_section() -> dict:
    """Report the embedded file even when it is not in use.

    It is reported precisely because it is a decoy: it holds a stale copy of the
    corpus at a different dimensionality, and a script run without .env will
    read it and look like it worked.
    """
    p = Path(LITE_PATH)
    if not p.exists():
        return {"present": False}
    uri, _ = _milvus_uri()
    return {"present": True, "path": LITE_PATH, "bytes": p.stat().st_size,
            "in_use": uri == LITE_PATH}


# --------------------------------------------------------------------------
# run artifacts - append-only, no UI earns its keep here


def _count_lines(path: str) -> int | None:
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except Exception:
        return None


def runs_section() -> dict:
    traces = sorted(glob.glob("run/traces/*.jsonl"))
    spans = 0
    for t in traces:
        n = _count_lines(t)
        if n:
            spans += n
    hist = "run/evals/history.jsonl"
    return {"traces": {"files": len(traces), "spans": spans,
                       "glob": "run/traces/*.jsonl"},
            "evals": {"path": hist, "runs": _count_lines(hist) or 0,
                      "present": Path(hist).exists()}}


def admin_section() -> dict:
    return {"attu": {"port": ATTU_PORT, "up": _port_open(ATTU_PORT)},
            "sqlite_web": {"port": SQLITEWEB_PORT,
                           "up": _port_open(SQLITEWEB_PORT)}}


# --------------------------------------------------------------------------
# rendering


def collect() -> dict:
    return {"env_file_loaded": bool(_LOADED), "env_names": sorted(_LOADED),
            "sqlite": sqlite_section(), "milvus": milvus_section(),
            "milvus_lite": lite_section(), "runs": runs_section(),
            "admin": admin_section()}


def render(d: dict) -> str:
    L: list[str] = []
    add = L.append
    add("data stores " + "-" * 62)

    s = d["sqlite"]
    if s["ok"]:
        mb = s.get("bytes", 0) / 1e6
        add(f"  sqlite    {s['path']}  ({mb:.1f} MB)")
        add(f"            {len(s['tables'])} tables, {_n(s['rows'])} rows total")
        for t in s["tables"]:
            add(f"              {t['name']:<22} {_n(t['rows']):>9}")
    else:
        add(f"  sqlite    {s['path']}  -- {s.get('error', 'unavailable')}")
    a = d["admin"]["sqlite_web"]
    add(f"            UI  http://127.0.0.1:{a['port']}  sqlite-web, read-write"
        f"  [{'up' if a['up'] else 'not running'}]")

    m = d["milvus"]
    add("")
    if m["ok"]:
        add(f"  milvus    {m['uri']}   (from {m['source']})")
        if not m["collections"]:
            add("            no collections -- corpus has not been indexed")
        for c in m["collections"]:
            dim = f"@{c['dim']}d" if c.get("dim") else ""
            add(f"              {c['name']:<22} {_n(c['rows']):>9} {dim}")
    else:
        add(f"  milvus    {m['uri'] or '(unset)'}  -- {m.get('error', 'unavailable')}")
    a = d["admin"]["attu"]
    add(f"            UI  http://127.0.0.1:{a['port']}  attu, read-write"
        f"        [{'up' if a['up'] else 'not running'}]")

    lt = d["milvus_lite"]
    if lt.get("present") and not lt.get("in_use"):
        add(f"            note: {lt['path']} exists and is NOT in use. A script")
        add("                  run without .env reads it instead, and reports")
        add("                  its stale corpus as though it were live.")

    r = d["runs"]
    add("")
    add(f"  traces    {r['traces']['glob']}  "
        f"{r['traces']['files']} files, {_n(r['traces']['spans'])} spans")
    add(f"  evals     {r['evals']['path']}  {_n(r['evals']['runs'])} runs")
    add("            jq -s 'group_by(.name)|map({k:.[0].name,n:length})' "
        "run/traces/*.jsonl")

    add("")
    if SSH_ALIAS:
        add("  both UIs are bound to 127.0.0.1. From your laptop, one tunnel:")
        add(f"    ssh -N -L {d['admin']['attu']['port']}:127.0.0.1:"
            f"{d['admin']['attu']['port']} "
            f"-L {d['admin']['sqlite_web']['port']}:127.0.0.1:"
            f"{d['admin']['sqlite_web']['port']} {SSH_ALIAS}")
        add("  then open the two http://127.0.0.1 links above in your own browser.")
    else:
        add("  both UIs are bound to 127.0.0.1 - open the two links above "
            "directly.")
        add("  For a remote box, set ASOIA_SSH_ALIAS and this prints the "
            "tunnel command.")
    add("-" * 74)
    return "\n".join(L)


def main(argv: list[str]) -> int:
    d = collect()
    if "--json" in argv:
        print(json.dumps(d, indent=2, sort_keys=True))
    else:
        print(render(d))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
