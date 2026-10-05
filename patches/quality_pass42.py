#!/usr/bin/env python
"""Pass 42 - an operator view of the stores, outside the agent's UI.

The agent's UI shows a service advisor what they need and nothing else. That is
the right call for the UI and the wrong call for the operator, who until now had
no way to see what is in the vector store or the system of record without
opening a python REPL on the box.

This pass adds that view and makes it mutable:

  scripts/store_report.py   every store, where it lives, how many rows, which
                            one is actually serving answers, and the ssh tunnel
                            that reaches the UIs. Read-only and never raises.
  scripts/stores.sh         starts Attu for Milvus and sqlite-web for the
                            system of record, both bound to 127.0.0.1.
  scripts/stack.sh          prints the report on `up` and `restart`, brings the
                            UIs up with the stack, takes them down with it, and
                            gains a `stores` verb.

Both UIs can write. Attu can drop a collection and sqlite-web runs arbitrary
SQL, so neither may be reachable more widely than the services it administers:
loopback only, reached over ssh, never through the public gradio.live link.

`up` never downloads. Provisioning pulls an image and installs a package, which
is not something a startup path should do unasked in front of an audience, so it
is its own verb: `scripts/stack.sh stores provision`.

Verified before shipping: sqlite-web 0.8.2 serves the real 4.6 MB store with all
six tables browsable and an editable query tab, the report's row counts match
sqlite_master, the Milvus-Lite decoy warning fires only when the decoy is not
the store in use, and start/report/stop are idempotent.

Idempotent. Re-running changes nothing and says so.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if (ROOT / "scripts").is_dir() is False:
    ROOT = ROOT.parent
NOTES: list[str] = []


def note(s: str) -> None:
    NOTES.append(s)
    print("  " + s)


REPORT_PY = '#!/usr/bin/env python\n"""Print every store the stack keeps, where it lives, and how to open it.\n\nThe agent\'s own UI deliberately shows none of this - an operator\'s view of the\nsystem of record does not belong in a service advisor\'s chat window. This is\nthat view instead: stack.sh prints it on `up` and `restart`, and it also stands\nalone as `scripts/stack.sh stores` at any time.\n\nIt loads .env the way scripts/stack.sh does, through scripts._env, because that\nis the only way to report the store that is actually serving answers. Measured\nin a shell that never read .env, this script would open the embedded Milvus Lite\nfile in data/generated/ instead of the Milvus the API is talking to, and would\nreport that store\'s row count with a straight face. That mistake has already\nbeen made here once, and it cost an afternoon.\n\nTwo promises hold for every section:\n\n  nothing raises   - a store that is down prints one line saying so, because a\n                     report that dies on its first unreachable backend is worth\n                     less than no report at all.\n  nothing writes   - SQLite is opened mode=ro. An operator asking what is in the\n                     system of record must not be able to damage it by asking.\n"""\nfrom __future__ import annotations\n\nimport glob\nimport json\nimport os\nimport socket\nimport sqlite3\nimport sys\nfrom pathlib import Path\n\nsys.path.insert(0, ".")\n\n\ndef _load_env() -> list[str]:\n    """Load .env the way scripts/stack.sh does, through scripts._env.\n\n    Tolerant of that module\'s entry point moving. This import has to happen\n    before any store lookup below, and a report that cannot start is worth less\n    than one that runs and says the environment was never loaded - so a missing\n    or renamed loader degrades to [] rather than killing the process.\n    """\n    try:\n        import scripts._env as m  # noqa: E402 - must precede any store lookup\n    except Exception:\n        return []\n    for attr in ("load", "load_env"):\n        fn = getattr(m, attr, None)\n        if callable(fn):\n            try:\n                r = fn()\n            except Exception:\n                return []\n            if isinstance(r, (list, tuple, set)):\n                return sorted(str(x) for x in r)\n            if isinstance(r, dict):\n                return sorted(str(k) for k in r)\n            return []\n    return []\n\n\n_LOADED = _load_env()\n\n# Defaults mirror the app\'s own: app/state/db.py reads ASOIA_DB with this\n# fallback, so the report follows the app rather than restating it.\nDB_PATH = os.environ.get("ASOIA_DB", "data/generated/service.sqlite")\nMILVUS_URI = os.environ.get("ASOIA_MILVUS_URI", "")\nLITE_PATH = "data/generated/milvus.db"\n\n# Loopback only. The standing rule on this box is that 19530, 8080, 3000 and\n# 8888 do not leave it; an admin UI with write access has no business being\n# laxer than the service it administers.\nATTU_PORT = int(os.environ.get("ASOIA_ATTU_PORT", "8101"))\nSQLITEWEB_PORT = int(os.environ.get("ASOIA_SQLITEWEB_PORT", "8102"))\nSSH_ALIAS = os.environ.get("ASOIA_SSH_ALIAS", "capstone-poc")\n\n\ndef _n(x) -> str:\n    """Thousands separators, because 1949 and 19490 look alike at a glance."""\n    try:\n        return f"{int(x):,}"\n    except Exception:\n        return str(x)\n\n\ndef _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:\n    try:\n        with socket.create_connection((host, port), timeout):\n            return True\n    except Exception:\n        return False\n\n\n# --------------------------------------------------------------------------\n# sqlite - the system of record\n\n\ndef sqlite_section() -> dict:\n    out: dict = {"path": DB_PATH, "ok": False, "tables": [], "rows": 0}\n    p = Path(DB_PATH)\n    if not p.exists():\n        out["error"] = "not present"\n        return out\n    out["bytes"] = p.stat().st_size\n    try:\n        # mode=ro: a read-only handle cannot be the cause of a corrupt store.\n        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2.0)\n    except Exception as e:\n        out["error"] = f"{type(e).__name__}: {e}"\n        return out\n    try:\n        names = [r[0] for r in con.execute(\n            "SELECT name FROM sqlite_master WHERE type=\'table\' "\n            "AND name NOT LIKE \'sqlite_%\' ORDER BY name")]\n        for name in names:\n            try:\n                # Table names come from sqlite_master, not from a caller, so\n                # there is no untrusted text in this statement.\n                cnt = con.execute(f\'SELECT COUNT(*) FROM "{name}"\').fetchone()[0]\n            except Exception:\n                cnt = None\n            out["tables"].append({"name": name, "rows": cnt})\n            if isinstance(cnt, int):\n                out["rows"] += cnt\n        out["ok"] = True\n    except Exception as e:\n        out["error"] = f"{type(e).__name__}: {e}"\n    finally:\n        con.close()\n    return out\n\n\n# --------------------------------------------------------------------------\n# milvus - the vector store\n\n\ndef _milvus_uri() -> tuple[str, str]:\n    """Return (uri, how_we_got_it). The second value is the point of this.\n\n    A report that prints a row count without saying which store it came from is\n    how the wrong store gets believed.\n    """\n    if MILVUS_URI:\n        return MILVUS_URI, "ASOIA_MILVUS_URI"\n    if Path(LITE_PATH).exists():\n        return LITE_PATH, f"fallback to embedded Milvus Lite ({LITE_PATH})"\n    return "", "unset"\n\n\ndef milvus_section() -> dict:\n    uri, how = _milvus_uri()\n    out: dict = {"uri": uri, "source": how, "ok": False, "collections": []}\n    if not uri:\n        out["error"] = "no ASOIA_MILVUS_URI and no embedded file"\n        return out\n    try:\n        from pymilvus import MilvusClient\n    except Exception as e:\n        out["error"] = f"pymilvus unavailable: {type(e).__name__}: {e}"\n        return out\n    try:\n        client = MilvusClient(uri=uri if "://" in uri or uri.endswith(".db")\n                              else "http://" + uri)\n    except Exception as e:\n        out["error"] = f"{type(e).__name__}: {e}"\n        return out\n    try:\n        for name in client.list_collections():\n            row: dict = {"name": name}\n            try:\n                row["rows"] = client.get_collection_stats(name).get("row_count")\n            except Exception:\n                row["rows"] = None\n            try:\n                for f in client.describe_collection(name).get("fields", []):\n                    dim = (f.get("params") or {}).get("dim")\n                    if dim:\n                        row["dim"] = dim\n                        break\n            except Exception:\n                pass\n            out["collections"].append(row)\n        out["ok"] = True\n    except Exception as e:\n        out["error"] = f"{type(e).__name__}: {e}"\n    return out\n\n\ndef lite_section() -> dict:\n    """Report the embedded file even when it is not in use.\n\n    It is reported precisely because it is a decoy: it holds a stale copy of the\n    corpus at a different dimensionality, and a script run without .env will\n    read it and look like it worked.\n    """\n    p = Path(LITE_PATH)\n    if not p.exists():\n        return {"present": False}\n    uri, _ = _milvus_uri()\n    return {"present": True, "path": LITE_PATH, "bytes": p.stat().st_size,\n            "in_use": uri == LITE_PATH}\n\n\n# --------------------------------------------------------------------------\n# run artifacts - append-only, no UI earns its keep here\n\n\ndef _count_lines(path: str) -> int | None:\n    try:\n        with open(path, "rb") as fh:\n            return sum(1 for _ in fh)\n    except Exception:\n        return None\n\n\ndef runs_section() -> dict:\n    traces = sorted(glob.glob("run/traces/*.jsonl"))\n    spans = 0\n    for t in traces:\n        n = _count_lines(t)\n        if n:\n            spans += n\n    hist = "run/evals/history.jsonl"\n    return {"traces": {"files": len(traces), "spans": spans,\n                       "glob": "run/traces/*.jsonl"},\n            "evals": {"path": hist, "runs": _count_lines(hist) or 0,\n                      "present": Path(hist).exists()}}\n\n\ndef admin_section() -> dict:\n    return {"attu": {"port": ATTU_PORT, "up": _port_open(ATTU_PORT)},\n            "sqlite_web": {"port": SQLITEWEB_PORT,\n                           "up": _port_open(SQLITEWEB_PORT)}}\n\n\n# --------------------------------------------------------------------------\n# rendering\n\n\ndef collect() -> dict:\n    return {"env_file_loaded": bool(_LOADED), "env_names": sorted(_LOADED),\n            "sqlite": sqlite_section(), "milvus": milvus_section(),\n            "milvus_lite": lite_section(), "runs": runs_section(),\n            "admin": admin_section()}\n\n\ndef render(d: dict) -> str:\n    L: list[str] = []\n    add = L.append\n    add("data stores " + "-" * 62)\n\n    s = d["sqlite"]\n    if s["ok"]:\n        mb = s.get("bytes", 0) / 1e6\n        add(f"  sqlite    {s[\'path\']}  ({mb:.1f} MB)")\n        add(f"            {len(s[\'tables\'])} tables, {_n(s[\'rows\'])} rows total")\n        for t in s["tables"]:\n            add(f"              {t[\'name\']:<22} {_n(t[\'rows\']):>9}")\n    else:\n        add(f"  sqlite    {s[\'path\']}  -- {s.get(\'error\', \'unavailable\')}")\n    a = d["admin"]["sqlite_web"]\n    add(f"            UI  http://127.0.0.1:{a[\'port\']}  sqlite-web, read-write"\n        f"  [{\'up\' if a[\'up\'] else \'not running\'}]")\n\n    m = d["milvus"]\n    add("")\n    if m["ok"]:\n        add(f"  milvus    {m[\'uri\']}   (from {m[\'source\']})")\n        if not m["collections"]:\n            add("            no collections -- corpus has not been indexed")\n        for c in m["collections"]:\n            dim = f"@{c[\'dim\']}d" if c.get("dim") else ""\n            add(f"              {c[\'name\']:<22} {_n(c[\'rows\']):>9} {dim}")\n    else:\n        add(f"  milvus    {m[\'uri\'] or \'(unset)\'}  -- {m.get(\'error\', \'unavailable\')}")\n    a = d["admin"]["attu"]\n    add(f"            UI  http://127.0.0.1:{a[\'port\']}  attu, read-write"\n        f"        [{\'up\' if a[\'up\'] else \'not running\'}]")\n\n    lt = d["milvus_lite"]\n    if lt.get("present") and not lt.get("in_use"):\n        add(f"            note: {lt[\'path\']} exists and is NOT in use. A script")\n        add("                  run without .env reads it instead, and reports")\n        add("                  its stale corpus as though it were live.")\n\n    r = d["runs"]\n    add("")\n    add(f"  traces    {r[\'traces\'][\'glob\']}  "\n        f"{r[\'traces\'][\'files\']} files, {_n(r[\'traces\'][\'spans\'])} spans")\n    add(f"  evals     {r[\'evals\'][\'path\']}  {_n(r[\'evals\'][\'runs\'])} runs")\n    add("            jq -s \'group_by(.name)|map({k:.[0].name,n:length})\' "\n        "run/traces/*.jsonl")\n\n    add("")\n    add("  both UIs are bound to 127.0.0.1. From your laptop, one tunnel:")\n    add(f"    ssh -N -L {d[\'admin\'][\'attu\'][\'port\']}:127.0.0.1:"\n        f"{d[\'admin\'][\'attu\'][\'port\']} "\n        f"-L {d[\'admin\'][\'sqlite_web\'][\'port\']}:127.0.0.1:"\n        f"{d[\'admin\'][\'sqlite_web\'][\'port\']} {SSH_ALIAS}")\n    add("  then open the two http://127.0.0.1 links above in your own browser.")\n    add("-" * 74)\n    return "\\n".join(L)\n\n\ndef main(argv: list[str]) -> int:\n    d = collect()\n    if "--json" in argv:\n        print(json.dumps(d, indent=2, sort_keys=True))\n    else:\n        print(render(d))\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main(sys.argv[1:]))\n'

STORES_SH = '#!/usr/bin/env bash\n# Operator access to the stores, kept deliberately outside the agent\'s own UI.\n#\n# stack.sh sources this and calls stores_report at the end of `up` and\n# `restart`; it is also reachable as `scripts/stack.sh stores [verb]`. It works\n# when sourced and when run directly, so it can be debugged on its own.\n#\n# Two rules shape what follows.\n#\n# Ports 8101/8102, not 8001/8002: on this box nim-embed holds 8001 and\n# nim-rerank holds 8002, and 7860, 8000, 8080, 9091 and 19530 are taken by the\n# UI, the LLM NIM, the API, Milvus metrics and Milvus itself.\n#\n# Loopback only. Both UIs can write - sqlite-web runs arbitrary SQL against the\n# system of record and Attu can drop a collection - so neither may be laxer than\n# the services they administer. They bind 127.0.0.1 and reach your laptop over\n# an ssh tunnel the report prints for you. Nothing here opens a firewall port,\n# and nothing here goes through the public gradio.live link.\n#\n# `up` never downloads. A startup path that silently pulls a 100 MB image or\n# writes to the venv is a startup path that fails on a metered connection in\n# front of an audience. So: the report always prints, a UI starts only if its\n# dependency is already on the box, and provisioning is an explicit verb you\n# run once - `scripts/stack.sh stores provision`.\n\nASOIA_ATTU_PORT="${ASOIA_ATTU_PORT:-8101}"\nASOIA_SQLITEWEB_PORT="${ASOIA_SQLITEWEB_PORT:-8102}"\n# Attu tracks Milvus by minor version; this box runs milvusdb/milvus:v2.5.4,\n# so v2.5. Bump both together or the UI talks to a server it does not\n# understand.\nASOIA_ATTU_IMAGE="${ASOIA_ATTU_IMAGE:-zilliz/attu:v2.5}"\nASOIA_ADMIN="${ASOIA_ADMIN:-on}"\n_ASOIA_DB="${ASOIA_DB:-data/generated/service.sqlite}"\n\n# stack.sh owns svc_log; define a compatible one only if we were run directly.\nif ! declare -f svc_log >/dev/null 2>&1; then\n  svc_log() { echo "/tmp/asoia-$1.log"; }\nfi\n\n_st_py() {\n  # The report must run under the interpreter that has pymilvus, and must see\n  # the same .env the stack saw - scripts/_env.py handles the second half.\n  if [ -x .venv/bin/python ]; then .venv/bin/python "$@"\n  elif command -v uv >/dev/null 2>&1; then uv run python "$@"\n  else python3 "$@"; fi\n}\n\n_st_listening() {  # _st_listening PORT\n  if command -v ss >/dev/null 2>&1; then\n    ss -ltn 2>/dev/null | grep -q ":$1 "\n  else\n    (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1\n  fi\n}\n\n# ---------------------------------------------------------------- milvus / attu\n\n_st_milvus_container() {\n  # The container serving 19530. Named first, since that is what this stack\n  # calls it; otherwise whatever publishes the port.\n  if docker ps --format "{{.Names}}" 2>/dev/null | grep -qx asoia-milvus; then\n    echo asoia-milvus; return\n  fi\n  docker ps --format "{{.Names}} {{.Ports}}" 2>/dev/null \\\n    | awk "/19530->19530/ {print \\$1; exit}"\n}\n\n_st_attu_target() {\n  # Attu runs in a container, so a loopback URI means the container itself and\n  # has to be translated.\n  #\n  # `host.docker.internal:host-gateway` is the usual answer and it does NOT\n  # work on this box: the name resolves to the bridge gateway (172.17.0.1) but\n  # TCP to the published 19530 times out - dropped, not refused. So go straight\n  # to Milvus\'s own address on the bridge it shares with Attu. Measured, not\n  # assumed; the gateway route is kept only for a Milvus that is not a\n  # container.\n  #\n  # Container IPs are not stable, so this is re-resolved on every start and\n  # stores_attu_up recreates Attu when the address has moved.\n  local uri="${ASOIA_MILVUS_URI:-}" hp host port c ip\n  [ -n "$uri" ] || { echo ""; return; }\n  hp="${uri#*://}"; hp="${hp%%/*}"\n  host="${hp%%:*}"; port="${hp##*:}"\n  [ "$port" = "$host" ] && port=19530\n  case "$host" in\n    localhost|127.0.0.1|::1|0.0.0.0) ;;\n    *) echo "$hp"; return ;;\n  esac\n  c="$(_st_milvus_container)"\n  if [ -n "$c" ]; then\n    ip="$(docker inspect "$c" \\\n          --format "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}" \\\n          2>/dev/null | awk "{print \\$1}")"\n    [ -n "$ip" ] && { echo "$ip:$port"; return; }\n  fi\n  echo "host.docker.internal:$port"\n}\n\nstores_attu_up() {\n  command -v docker >/dev/null 2>&1 || {\n    echo "  [attu] docker not available - skipping the vector-store UI"; return 0; }\n  local target; target="$(_st_attu_target)"\n  [ -n "$target" ] || {\n    echo "  [attu] ASOIA_MILVUS_URI is unset - nothing to point a UI at"; return 0; }\n  if docker ps --format "{{.Names}}" 2>/dev/null | grep -qx asoia-attu; then\n    local cur\n    cur="$(docker inspect asoia-attu \\\n           --format "{{range .Config.Env}}{{println .}}{{end}}" 2>/dev/null \\\n           | sed -n "s/^MILVUS_URL=//p")"\n    if [ "$cur" = "$target" ]; then\n      echo "  [attu] already running on 127.0.0.1:${ASOIA_ATTU_PORT}"; return 0\n    fi\n    echo "  [attu] Milvus moved: ${cur:-unknown} -> ${target}; recreating"\n  fi\n  # No pull on the startup path: report the one command that fixes it instead.\n  docker image inspect "$ASOIA_ATTU_IMAGE" >/dev/null 2>&1 || {\n    echo "  [attu] image absent. Provision once with:  scripts/stack.sh stores provision"\n    return 0; }\n  docker rm -f asoia-attu >/dev/null 2>&1\n  if docker run -d --name asoia-attu --restart unless-stopped \\\n       -p "127.0.0.1:${ASOIA_ATTU_PORT}:3000" \\\n       --add-host host.docker.internal:host-gateway \\\n       -e "MILVUS_URL=${target}" "$ASOIA_ATTU_IMAGE" >>"$(svc_log attu)" 2>&1; then\n    echo "  [attu] 127.0.0.1:${ASOIA_ATTU_PORT} -> ${target}"\n  else\n    echo "  [attu] failed to start; see $(svc_log attu)"\n  fi\n}\n\nstores_attu_down() {\n  command -v docker >/dev/null 2>&1 || return 0\n  docker rm -f asoia-attu >/dev/null 2>&1 && echo "  [attu] stopped"\n  return 0\n}\n\n# ------------------------------------------------------------ sqlite/sqlite-web\n\n_st_sqliteweb_bin() {\n  if [ -x .venv/bin/sqlite_web ]; then echo .venv/bin/sqlite_web\n  elif command -v sqlite_web >/dev/null 2>&1; then command -v sqlite_web\n  else echo ""; fi\n}\n\nstores_sqliteweb_up() {\n  local pidf=/tmp/asoia-sqliteweb.pid bin log\n  log="$(svc_log sqliteweb)"\n  if [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null; then\n    echo "  [sqlite-web] already running on 127.0.0.1:${ASOIA_SQLITEWEB_PORT}"; return 0; fi\n  [ -f "$_ASOIA_DB" ] || {\n    echo "  [sqlite-web] ${_ASOIA_DB} is not present - nothing to serve"; return 0; }\n  bin="$(_st_sqliteweb_bin)"\n  [ -n "$bin" ] || {\n    echo "  [sqlite-web] not installed. Provision once with:  scripts/stack.sh stores provision"\n    return 0; }\n  # Flags, all checked against sqlite-web 0.8.2:\n  #   -x  never try to open a browser - this box is headless\n  #   -q  errors only, so the log stays readable\n  #   -f  foreign_keys ON, matching the PRAGMA app/state/db.py sets. Without it\n  #       the admin UI enforces less than the app does, and an operator can\n  #       delete an RO and leave its events orphaned - a state the agent itself\n  #       cannot produce and does not expect to read.\n  #   -T  do not ellipsize at 50 chars; events.payload is JSON and unreadable\n  #       truncated.\n  # Writes stay enabled on purpose: the mutable view is the point. SQLite\'s\n  # default 5s busy timeout covers the app\'s small writes, but a long\n  # transaction left open in the query tab can block the agent. That is the\n  # cost of a read-write UI on a live store, and it is why this is loopback.\n  nohup "$bin" -H 127.0.0.1 -p "$ASOIA_SQLITEWEB_PORT" -x -q -f -T "$_ASOIA_DB" \\\n      >>"$log" 2>&1 &\n  echo $! >"$pidf"\n  sleep 1\n  if kill -0 "$(cat "$pidf")" 2>/dev/null; then\n    echo "  [sqlite-web] 127.0.0.1:${ASOIA_SQLITEWEB_PORT} -> ${_ASOIA_DB} (read-write)"\n  else\n    rm -f "$pidf"\n    echo "  [sqlite-web] exited immediately; tail of $log:"\n    tail -n 6 "$log" 2>/dev/null | sed \'s/^/      /\'\n  fi\n}\n\nstores_sqliteweb_down() {\n  local pidf=/tmp/asoia-sqliteweb.pid\n  [ -f "$pidf" ] || return 0\n  kill "$(cat "$pidf")" 2>/dev/null && echo "  [sqlite-web] stopped"\n  rm -f "$pidf"\n  return 0\n}\n\n# ------------------------------------------------------------------- provision\n\nstores_provision() {\n  echo "provisioning the store UIs (this one does download)"\n  if command -v docker >/dev/null 2>&1; then\n    echo "  pulling ${ASOIA_ATTU_IMAGE}"\n    docker pull "$ASOIA_ATTU_IMAGE" || echo "  pull failed - vector UI will stay off"\n  else\n    echo "  docker not available - skipping attu"\n  fi\n  if command -v uv >/dev/null 2>&1; then\n    echo "  installing sqlite-web into .venv"\n    uv pip install "sqlite-web>=0.8" || echo "  install failed - sqlite UI will stay off"\n  elif [ -x .venv/bin/pip ]; then\n    .venv/bin/pip install "sqlite-web>=0.8" || echo "  install failed - sqlite UI will stay off"\n  else\n    echo "  no uv and no .venv/bin/pip - install it yourself:"\n    echo "    pip install -e \\".[admin]\\""\n  fi\n  echo "done. Now run: scripts/stack.sh stores up"\n}\n\n# ---------------------------------------------------------------------- public\n\nstores_admin_up() {\n  [ "$ASOIA_ADMIN" = "off" ] && return 0\n  stores_attu_up\n  stores_sqliteweb_up\n  return 0\n}\n\nstores_admin_down() {\n  stores_attu_down\n  stores_sqliteweb_down\n  return 0\n}\n\nstores_report() {\n  _st_py scripts/store_report.py "$@"\n}\n\nstores_main() {\n  case "${1:-report}" in\n    report|"")  stores_report ;;\n    json)       stores_report --json ;;\n    up)         stores_admin_up; echo; stores_report ;;\n    down)       stores_admin_down ;;\n    provision)  stores_provision ;;\n    *) echo "usage: stores.sh {report|json|up|down|provision}" >&2; return 2 ;;\n  esac\n}\n\n# Sourced by stack.sh, or run on its own.\nif [ "${BASH_SOURCE[0]}" = "${0}" ]; then\n  cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1\n  [ -f .env ] && { set -a; . ./.env; set +a; }\n  stores_main "$@"\nfi\n'


def write_file(rel: str, body: str, mode: int | None = None) -> None:
    p = ROOT / rel
    if p.exists() and p.read_text() == body:
        note(f"{rel}: already current, skipped")
        return
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    if mode is not None:
        p.chmod(mode)
    note(f"{rel}: {'rewritten' if existed else 'created'}, {len(body.splitlines())} lines")


def _fail(step: str, txt: str, pattern: str) -> None:
    """Refuse loudly, and show the region, so the anchor can be corrected once.

    This pass was written without the live scripts/stack.sh in reach. Guessing an
    anchor and editing anyway is how a working stack gets a broken dispatch, so
    every edit asserts first and this prints what it actually found.
    """
    lines = [f"{i+1:4}  {l}" for i, l in enumerate(txt.splitlines())
             if re.search(r"case|\)\s*$|;;|\.env|usage", l)]
    raise RuntimeError(
        f"pass 42 refused: {step}\n  pattern: {pattern}\n"
        "  scripts/stack.sh structural lines:\n    " + "\n    ".join(lines[:60]))


def wire_stack() -> None:
    rel = "scripts/stack.sh"
    p = ROOT / rel
    if not p.exists():
        note(f"{rel}: absent - skipped wiring; use scripts/stores.sh directly")
        return
    txt = p.read_text()
    if "stores.sh" in txt:
        note(f"{rel}: already wired, skipped")
        return
    orig = txt

    # 1. Source stores.sh after the .env load, so .env can set ASOIA_ADMIN and
    #    the admin ports before stores.sh picks its defaults.
    pat = r"^.*\[ -f \.env \].*set -a.*$"
    m = list(re.finditer(pat, txt, re.M))
    if len(m) != 1:
        _fail(f"expected exactly 1 .env-load line, found {len(m)}", txt, pat)
    ins = ('\n\n# Operator view of the stores (pass 42). Sourced after .env so the\n'
           '# admin ports and ASOIA_ADMIN can be set there.\n'
           '. "$(dirname "$0")/stores.sh"')
    txt = txt[:m[0].end()] + ins + txt[m[0].end():]

    # 2. Report at the end of up) and restart); stop the UIs in down).
    for verb, call in (("up", "stores_admin_up; echo; stores_report"),
                       ("restart", "stores_admin_up; echo; stores_report"),
                       ("down", "stores_admin_down")):
        pat = r"^([ \t]*)" + verb + r"\)"
        m = list(re.finditer(pat, txt, re.M))
        if len(m) != 1:
            _fail(f"expected exactly 1 '{verb})' case arm, found {len(m)}", txt, pat)
        arm_indent = m[0].group(1)
        end = txt.find(";;", m[0].end())
        if end < 0:
            _fail(f"no ';;' terminating the '{verb})' arm", txt, pat)
        body = txt[m[0].end():end]
        # A restart arm that re-runs up - either as `"$0" up` or by calling the
        # up function - has already produced a report, because the up arm
        # reports. Adding the call here prints the whole thing twice.
        # Skip only a restart that re-enters the dispatch - `"$0" up` or
        # `bash scripts/stack.sh up` - because that path runs the up ARM and
        # the arm is what reports. A restart that calls the up FUNCTION has
        # not reported, and must get the call.
        if verb == "restart" and re.search(
                r'(?:"?\$0"?|stack\.sh"?)\s+up\b', body):
            note("scripts/stack.sh: restart re-enters the up arm - one report")
            continue
        if "\n" in body:
            # Multi-line arm: insert above the `;;`, indented like the body, so
            # an arm this pass touches looks like an arm it does not.
            line_start = txt.rfind("\n", 0, end) + 1
            body_lines = [l for l in body.splitlines() if l.strip()]
            ind = (re.match(r"[ \t]*", body_lines[-1]).group(0)
                   if body_lines else arm_indent + "  ")
            txt = txt[:line_start] + ind + call + "\n" + txt[line_start:]
        else:
            # One-line arm - `up)  shift; up "$@" ;;`. Inserting on its own line
            # would put a statement above the case pattern, which is a syntax
            # error, so extend the line instead.
            sep = "" if body.rstrip().endswith(";") else "; "
            txt = txt[:end] + sep + call + " " + txt[end:]

    # 3. A stores verb of its own, inserted before the catch-all arm.
    pat = r"^([ \t]*)\*\)"
    m = list(re.finditer(pat, txt, re.M))
    if not m:
        _fail("no '*)' catch-all arm to insert the stores verb before", txt, pat)
    # A nested case - `logs)` has one - puts its own `*)` earlier in the file
    # and more deeply indented. The stores verb belongs to the outer dispatch,
    # so take the shallowest arm, and the last of those if several tie.
    shallow = min(len(x.group(1)) for x in m)
    m = [x for x in m if len(x.group(1)) == shallow][-1:]
    indent = m[0].group(1)
    arm = (f"{indent}stores)     shift; stores_main \"$@\" ;;\n")
    txt = txt[:m[0].start()] + arm + txt[m[0].start():]

    # 4. The usage text. This script has no "usage:" line: the catch-all arm
    #    prints its own header comment with `sed -n '2,11p'`. Adding a line to
    #    that header therefore has to move the range too, or the last line of
    #    the usage silently stops being printed.
    um = re.search(r"sed -n '(\d+),(\d+)p'", txt)
    hm = re.search(r"^#\s+bash scripts/stack\.sh status\s+.*$", txt, re.M)
    if um and hm:
        first, last = int(um.group(1)), int(um.group(2))
        new_line = ("#   bash scripts/stack.sh stores         "
                    "the data stores, and their admin UIs")
        txt = txt[:hm.end()] + "\n" + new_line + txt[hm.end():]
        txt = txt.replace(um.group(0), f"sed -n '{first},{last + 1}p'", 1)
        # The inserted line must land inside the printed range, or it is
        # invisible; the range must not now run past the header block.
        hdr = txt.splitlines()[first - 1:last + 1]
        if not any("stores" in l for l in hdr):
            _fail("usage line landed outside the printed range", txt, um.group(0))
        if not all(l.startswith("#") for l in hdr):
            _fail("widened usage range now reads past the comment block", txt,
                  um.group(0))
        note(f"scripts/stack.sh: usage header + sed range {first},{last}p "
             f"-> {first},{last + 1}p")
    else:
        m = re.search(r"^(.*usage:.*)$", txt, re.M | re.I)
        if m and "stores" not in m.group(1):
            txt = txt.replace(m.group(1), m.group(1).replace(
                "status", "status|stores", 1), 1)
            note("scripts/stack.sh: usage line updated")
        else:
            note("scripts/stack.sh: no usage text recognised - not updated")

    assert txt != orig, "wiring produced no change"
    p.write_text(txt)
    note(f"{rel}: wired (+{len(txt.splitlines()) - len(orig.splitlines())} lines)")


def readme_row() -> None:
    rel = "patches/README.md"
    p = ROOT / rel
    if not p.exists():
        note(f"{rel}: absent, skipped")
        return
    txt = p.read_text()
    if "quality_pass42.py" in txt:
        note(f"{rel}: row already present, skipped")
        return
    rows = re.findall(r"^\| `(quality_pass\d+\.py)`", txt, re.M)
    if not rows:
        note(f"{rel}: no pass rows found, skipped")
        return
    last = rows[-1]
    m = re.search(r"^\| `" + re.escape(last) + r"`.*$", txt, re.M)
    row = ("| `quality_pass42.py` | operator view of the stores: a startup report "
           "of every store and loopback Attu + sqlite-web UIs, read-write, "
           "outside the agent's UI |")
    txt = txt[:m.end()] + "\n" + row + txt[m.end():]
    p.write_text(txt)
    note(f"{rel}: row added after {last}")


def checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, bool(ok), detail))

    sh = ROOT / "scripts/stores.sh"
    rp = ROOT / "scripts/store_report.py"
    ck("stores.sh exists", sh.exists())
    ck("store_report.py exists", rp.exists())

    r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
    ck("stores.sh parses", r.returncode == 0, r.stderr.strip()[:120])

    import ast
    try:
        ast.parse(rp.read_text())
        ck("store_report.py parses", True)
    except SyntaxError as e:
        ck("store_report.py parses", False, str(e))

    body = rp.read_text()
    # The report must open SQLite read-only. An operator asking what is in the
    # system of record must not be able to damage it by asking.
    ck("report opens sqlite read-only", "mode=ro" in body and "uri=True" in body)
    # It must load .env before reading any store var, or it reports the decoy.
    ck("env loaded before store vars",
       body.index("_LOADED = _load_env()") < body.index("DB_PATH = os.environ.get"))

    shb = sh.read_text()
    # Loopback is the whole security story for a read-write admin UI.
    ck("attu binds loopback only", '-p "127.0.0.1:${ASOIA_ATTU_PORT}:3000"' in shb)
    ck("sqlite-web binds loopback only", '-H 127.0.0.1' in shb)
    # Not `"0.0.0.0" not in shb`: _st_attu_target has to NAME 0.0.0.0 as one of
    # the loopback spellings it translates, and a substring test calls that a
    # leak. Assert the bind POSITIONS instead - what the flags actually publish.
    binds = (re.findall(r'(?:-p|--publish)\s+"?([0-9.]+):', shb)
             + re.findall(r'(?:-H|--host)[\s=]+"?([0-9.]+)', shb))
    ck("every bind position is loopback",
       bool(binds) and all(b == "127.0.0.1" for b in binds),
       f"found {binds}")
    # The startup path must not download.
    ck("up does not pull", "docker pull" not in shb.split("stores_provision")[0])
    ck("provision is its own verb", "stores_provision()" in shb and "provision)" in shb)
    # Honour the app's own integrity rules in the admin UI.
    ck("sqlite-web enforces foreign keys", " -f " in shb)

    st = ROOT / "scripts/stack.sh"
    if st.exists():
        t = st.read_text()
        ck("stack.sh sources stores.sh", "stores.sh" in t)
        ck("stack.sh reports on up", "stores_report" in t)
        ck("stack.sh stops UIs on down", "stores_admin_down" in t)
        r = subprocess.run(["bash", "-n", str(st)], capture_output=True, text=True)
        ck("stack.sh still parses", r.returncode == 0, r.stderr.strip()[:200])

        # The first `*)` in this file is the nested one inside logs), so a
        # naive insert makes `stores` a subcommand of `logs`. Compare the arm's
        # indentation with up)'s: they must sit at the same level.
        iu = re.search(r"^([ \t]*)up\)", t, re.M)
        ist = re.search(r"^([ \t]*)stores\)", t, re.M)
        ck("stores verb sits in the outer dispatch",
           bool(iu and ist and len(iu.group(1)) == len(ist.group(1))),
           "nested under another case" if iu and ist else "arm not found")

        # restart calls the up FUNCTION here, which does not report - so the
        # arm must carry the call. Guard against the inverse mistake too.
        rm = re.search(r"^[ \t]*restart\).*$", t, re.M)
        if rm:
            reenters = re.search(r'(?:"?\$0"?|stack\.sh"?)\s+up\b', rm.group(0))
            has = "stores_report" in rm.group(0)
            ck("restart reports exactly once", bool(reenters) != has,
               "re-enters the up arm AND reports" if reenters and has
               else "neither re-enters the up arm nor reports")

        # End to end: a bogus verb prints the usage header, which must now
        # mention the new one. This runs the real script, so it also proves
        # sourcing stores.sh does not break the dispatch.
        r = subprocess.run(["bash", str(st), "definitely-not-a-verb"],
                           capture_output=True, text=True, cwd=str(ROOT))
        ck("usage output mentions stores", "stores" in r.stdout + r.stderr,
           (r.stdout + r.stderr).strip()[:120])

    rd = ROOT / "patches/README.md"
    if rd.exists():
        txt = rd.read_text()
        rows = re.findall(r"^\| `([^`]+\.py)`", txt, re.M)
        files = sorted(x.name for x in (ROOT / "patches").glob("quality_pass*.py"))
        ck("README has a row 42", "quality_pass42.py" in rows)
        if files:
            ck("README rows match script files", sorted(rows) == files,
               f"{len(rows)} rows vs {len(files)} files")

    return out


def main() -> int:
    print("pass 42: operator view of the stores\n")
    write_file("scripts/store_report.py", REPORT_PY)
    write_file("scripts/stores.sh", STORES_SH, mode=0o755)
    wire_stack()
    readme_row()

    print("\nchecks")
    bad = 0
    for name, ok, detail in checks():
        print(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
        bad += 0 if ok else 1
    print()
    if bad:
        print(f"{bad} check(s) failed")
        return 1
    print("all checks passed")
    print("\nnext:")
    print("  scripts/stack.sh stores provision   # once: pulls attu, installs sqlite-web")
    print("  scripts/stack.sh stores up          # start the UIs and print the report")
    print("  scripts/stack.sh stores             # just the report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
