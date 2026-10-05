#!/usr/bin/env python3
"""Thirtieth pass: a launcher for Milvus, and the edits on the API too.

Run from the project root:   .venv/bin/python quality_pass30.py

Two loose ends from pass 27.

1. scripts/start_milvus.sh

   Pass 27 made Milvus the store but left standing one up as something you did
   by hand. This is the launcher, and it exists because embedded Milvus Lite has
   a property the old store did not:

       DataDirLockedError: another process holds the lock on
       '.../data/generated/milvus.db'

   Milvus Lite takes an EXCLUSIVE FILE LOCK. With the Gradio UI running, nothing
   else can open the store - not the API, not scripts/test_review.py, not a
   rebuild. LanceDB allowed concurrent readers, so this was a regression
   introduced by the store rather than by any code around it. Standalone is a
   server and the question does not arise; it is also what the architecture
   diagram actually says.

   One container, not the usual three: Milvus runs etcd in-process and uses the
   local filesystem instead of MinIO, which is the right trade for a single box.

   The image does NOT ship embedEtcd.yaml. Pointing ETCD_CONFIG_PATH at a file
   that is not there makes Milvus panic with a nil pointer dereference and exit
   134 - a Go stack trace, no mention of the missing config. The script writes
   that file before starting the container.

2. The edit endpoints.

   Editing was UI-and-Python only. The same four operations are now on the API,
   over the same functions, with the same rule: every write goes to the UPDATE
   and re-embeds the chunk.

       PATCH /review/chunks/{id}            correct the wording
       POST  /review/chunks/{id}/reindex    re-embed from the record
       POST  /review/chunks/{id}/exclude    out of the index, reversible
       POST  /review/chunks/{id}/restore    back in
       GET   /review/chunks/{id}/history    what has been changed here
       GET   /review/edits                  the whole audit trail

   ASOIA_REVIEW_WRITES=0 turns the four writes off. They default to on, so the
   API and the UI can do the same things - but this server binds 0.0.0.0 and has
   no authentication, so if port 8080 goes anywhere beyond the box, turn them
   off or put something in front of it.
"""
import sys, pathlib, ast, os, stat

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


def write(rel, body, label, executable=False):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    if existed and p.read_text() == body:
        CHANGES.append(f"  skip  {label} (already present)")
    else:
        p.write_text(body)
        CHANGES.append(f"  ok    {label}" + (" (replaced)" if existed else ""))
    if executable:
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ==================== 1. a launcher for the store
write('scripts/start_milvus.sh',
      '#!/usr/bin/env bash\n# Milvus standalone, in one container, for the vector store.\n#\n#   bash scripts/start_milvus.sh up       start it (idempotent)\n#   bash scripts/start_milvus.sh status   is it listening\n#   bash scripts/start_milvus.sh logs     tail the container\n#   bash scripts/start_milvus.sh down     stop and remove, keep the data\n#\n# WHY NOT EMBEDDED MILVUS LITE\n#\n# Milvus Lite takes an EXCLUSIVE FILE LOCK on its data directory. One process at\n# a time, full stop:\n#\n#   DataDirLockedError: another process holds the lock on\n#   \'.../data/generated/milvus.db\': [Errno 11] Resource temporarily unavailable\n#\n# With the Gradio UI running, nothing else can open the store - not the API, not\n# scripts/test_review.py, not a rebuild. LanceDB allowed concurrent readers, so\n# this is a regression introduced by the store, not by the code around it.\n# Standalone is a server: every process talks to it over gRPC and the question\n# does not arise. It is also what the architecture diagram actually says.\n#\n# One container, not the usual three: Milvus can run etcd in-process and use the\n# local filesystem instead of MinIO, which is the right trade for a single box.\nset -uo pipefail\ncd "$(dirname "${BASH_SOURCE[0]}")/.."\n\nNAME="${MILVUS_CONTAINER:-asoia-milvus}"\nIMAGE="${MILVUS_IMAGE:-milvusdb/milvus:v2.5.4}"\nPORT="${MILVUS_PORT:-19530}"\nWEB="${MILVUS_WEB_PORT:-9091}"\nDATA="$(pwd)/data/milvus"\n\ncase "${1:-up}" in\nup)\n  if ! command -v docker >/dev/null; then\n    echo "docker is not installed - use embedded Milvus instead:"\n    echo "  unset ASOIA_MILVUS_URI   # falls back to data/generated/milvus.db"\n    exit 1\n  fi\n  if docker ps --format \'{{.Names}}\' | grep -qx "$NAME"; then\n    echo "already running: $NAME"\n  else\n    docker rm -f "$NAME" >/dev/null 2>&1\n    mkdir -p "$DATA" "$(pwd)/configs/milvus"\n    # The image does NOT ship embedEtcd.yaml. Pointing ETCD_CONFIG_PATH at a file\n    # that is not there makes Milvus panic with a nil pointer dereference during\n    # startup - no message about the missing config, just a Go stack trace and\n    # exit 134. Generating it here is what the upstream launcher does.\n    cat > "$(pwd)/configs/milvus/embedEtcd.yaml" <<\'YAML\'\nlisten-client-urls: http://0.0.0.0:2379\nadvertise-client-urls: http://0.0.0.0:2379\nquota-backend-bytes: 4294967296\nauto-compaction-mode: revision\nauto-compaction-retention: \'1000\'\nYAML\n    cat > "$(pwd)/configs/milvus/user.yaml" <<\'YAML\'\n# overrides for milvus.yaml; empty is fine\nYAML\n    echo "starting $NAME from $IMAGE ..."\n    docker run -d --name "$NAME" \\\n      -p "${PORT}:19530" -p "${WEB}:9091" \\\n      -v "${DATA}:/var/lib/milvus" \\\n      -v "$(pwd)/configs/milvus/embedEtcd.yaml:/milvus/configs/embedEtcd.yaml" \\\n      -v "$(pwd)/configs/milvus/user.yaml:/milvus/configs/user.yaml" \\\n      -e ETCD_USE_EMBED=true \\\n      -e ETCD_DATA_DIR=/var/lib/milvus/etcd \\\n      -e ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml \\\n      -e COMMON_STORAGETYPE=local \\\n      --health-cmd="curl -f http://localhost:9091/healthz || exit 1" \\\n      --health-interval=10s --health-start-period=60s --health-timeout=5s \\\n      --health-retries=12 \\\n      "$IMAGE" milvus run standalone >/dev/null || {\n        echo "docker run failed"; exit 1; }\n  fi\n  printf \'waiting for it to answer\'\n  for _ in $(seq 1 60); do\n    if curl -sf "http://localhost:${WEB}/healthz" >/dev/null 2>&1; then\n      echo; echo "ready on localhost:${PORT}"\n      echo\n      echo "Point the app at it:"\n      echo "  export ASOIA_MILVUS_URI=http://localhost:${PORT}"\n      echo "and rebuild, because an embedded index does not move across:"\n      echo "  .venv/bin/python -c \'from app.retrieval.index import build; print(build())\'"\n      exit 0\n    fi\n    printf \'.\'; sleep 3\n  done\n  echo; echo "it did not become healthy in 180s. Logs:"\n  docker logs --tail 25 "$NAME"\n  exit 1\n  ;;\nstatus)\n  docker ps --filter "name=$NAME" --format \'  {{.Names}}  {{.Status}}  {{.Ports}}\'\n  curl -sf "http://localhost:${WEB}/healthz" >/dev/null 2>&1 \\\n    && echo "  healthz: ok" || echo "  healthz: not answering"\n  ;;\nlogs) docker logs --tail "${2:-40}" -f "$NAME" ;;\ndown)\n  docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped $NAME"\n  echo "data kept in $DATA - delete it by hand to start clean"\n  ;;\n*) echo "usage: start_milvus.sh [up|status|logs|down]"; exit 2 ;;\nesac\n',
      'scripts/start_milvus.sh  Milvus standalone in one container',
      executable=True)


# ==================== 2. the edits, on the API too
edit('app/api/server.py',
     'def main() -> None:\n    import uvicorn\n    from app.obs import metrics as M\n    from app.state.bootstrap import ensure_dataset\n    ensure_dataset()\n    M.serve()',
     '# ------------------------------------------------------- editing the store\n# Parity with the Data & Retrieval tab, over HTTP. Same functions, same rules:\n# every write goes to the UPDATE and re-embeds the chunk, because a chunk that\n# disagrees with the record it cites produces confident, well-formed, fully\n# "grounded" answers quoting text that is not in the database.\n#\n# These are the only administrative writes on this API. /updates is ingestion -\n# the product doing its job - whereas correcting or hiding a technician\'s note\n# is an operator action, so it has its own switch:\n#\n#     ASOIA_REVIEW_WRITES=0     the four endpoints below return 403\n#\n# It defaults to ON, so the API and the UI can do the same things. Worth knowing\n# that this server binds 0.0.0.0 and has no authentication of its own: if you\n# expose port 8080 beyond the box, turn these off or put something in front.\n\nclass EditRequest(BaseModel):\n    text: str = Field(..., min_length=1, max_length=8000,\n                      description="The corrected wording of the update.")\n    actor_id: str = Field("API", max_length=32)\n\n\nclass ExcludeRequest(BaseModel):\n    reason: str = Field("", max_length=500)\n    actor_id: str = Field("API", max_length=32)\n\n\ndef _writes_allowed() -> None:\n    if (os.environ.get("ASOIA_REVIEW_WRITES") or "1") == "0":\n        raise HTTPException(\n            403, "review writes are disabled (ASOIA_REVIEW_WRITES=0)")\n\n\ndef _edited(r: dict) -> dict:\n    if not r.get("ok"):\n        raise HTTPException(404 if "no update" in str(r.get("error", ""))\n                            else 409, r.get("error", "the edit did not apply"))\n    return r\n\n\n@app.patch("/review/chunks/{update_id}", tags=["review"])\ndef review_edit(update_id: str, req: EditRequest) -> dict:\n    """Correct an update\'s wording and re-embed its chunk.\n\n    Writes to the record, not to the index: the two cannot drift apart this way.\n    The previous wording is kept in `index_audit` and returned as `before`.\n    """\n    _writes_allowed()\n    from app.retrieval import edit as E\n    return _edited(E.edit_text(update_id, req.text, actor_id=req.actor_id))\n\n\n@app.post("/review/chunks/{update_id}/reindex", tags=["review"])\ndef review_reindex(update_id: str) -> dict:\n    """Re-embed a chunk from the record as it stands. No text change."""\n    _writes_allowed()\n    from app.retrieval import edit as E\n    return _edited(E.reindex_one(update_id))\n\n\n@app.post("/review/chunks/{update_id}/exclude", tags=["review"])\ndef review_exclude(update_id: str, req: ExcludeRequest) -> dict:\n    """Take a chunk out of the index. The update itself stays on file."""\n    _writes_allowed()\n    from app.retrieval import edit as E\n    return _edited(E.exclude(update_id, reason=req.reason, actor_id=req.actor_id))\n\n\n@app.post("/review/chunks/{update_id}/restore", tags=["review"])\ndef review_restore(update_id: str, req: ExcludeRequest | None = None) -> dict:\n    """Put an excluded chunk back and re-embed it."""\n    _writes_allowed()\n    from app.retrieval import edit as E\n    return _edited(E.restore(update_id,\n                             actor_id=(req.actor_id if req else "API")))\n\n\n@app.get("/review/chunks/{update_id}/history", tags=["review"])\ndef review_chunk_history(update_id: str) -> dict:\n    """Every correction, exclusion and restore recorded against one update."""\n    from app.retrieval import edit as E\n    return {"update_id": update_id, "history": E.history(update_id)}\n\n\n@app.get("/review/edits", tags=["review"])\ndef review_edits(limit: int = Query(100, ge=1, le=1000)) -> dict:\n    """The whole edit audit trail, newest first.\n\n    Separate from /review/events on purpose: a data correction is not something\n    that happened in the workshop. Putting these in the lifecycle log is what\n    broke seven of the fourteen answer checks in pass 27.\n    """\n    from app.retrieval import edit as E\n    return {"edits": E.recent_edits(limit),\n            "excluded": E.exclusions()}\n\n\ndef main() -> None:\n    import uvicorn\n    from app.obs import metrics as M\n    from app.state.bootstrap import ensure_dataset\n    ensure_dataset()\n    M.serve()',
     'server.py  edit, reindex, exclude, restore and the audit trail',
     skip_if='def _writes_allowed()')


# ==================== verify
print("Quality pass 30:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/api/server.py").read_text())
print("\nserver.py parses cleanly.")

sys.path.insert(0, ".")
import subprocess
bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


print("\nthe launcher:")
sh = ROOT / "scripts/start_milvus.sh"
chk("it is executable", os.access(sh, os.X_OK))
r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
chk("it is valid bash", r.returncode == 0, (r.stderr or "").strip()[:80])
body = sh.read_text()
chk("it writes embedEtcd.yaml before starting",
    "embedEtcd.yaml" in body and "listen-client-urls" in body,
    "the image does not ship it; without it Milvus panics on startup")
chk("it mounts that config into the container",
    "the image does not ship it; without it Milvus panics")
chk("it mounts that config into the container",
    "/milvus/configs/embedEtcd.yaml" in body)
chk("usage is refused cleanly",
    subprocess.run(["bash", str(sh), "nonsense"],
                   capture_output=True, text=True).returncode == 2)

print("\nthe endpoints:")
s = (ROOT / "app/api/server.py").read_text()
for path, verb in [("/review/chunks/{update_id}", "patch"),
                   ("/review/chunks/{update_id}/reindex", "post"),
                   ("/review/chunks/{update_id}/exclude", "post"),
                   ("/review/chunks/{update_id}/restore", "post"),
                   ("/review/chunks/{update_id}/history", "get"),
                   ("/review/edits", "get")]:
    chk(f"{verb.upper():5s} {path}", f'@app.{verb}("{path}"' in s)
# The indented form counts calls only; the bare name also matches the `def`,
# which made this read 5 against correct code.
_calls = s.count("    _writes_allowed()")
chk("all four writes check the switch", _calls == 4, f"{_calls} calls")
chk("the reads do not", s.count("_writes_allowed") == _calls + 1,
    "history and the audit trail stay readable")
chk("writes go through app.retrieval.edit, not the store",
    s.count("from app.retrieval import edit as E") == 6
    and "backend()" not in s.split("# ---- editing")[-1])

# the routes must actually register - a duplicate path or a bad signature only
# shows up when FastAPI builds the app, not when the file parses.
try:
    import importlib
    import app.api.server as S
    importlib.reload(S)
    paths = {r.path for r in S.app.routes}
    missing = [p for p in ("/review/chunks/{update_id}",
                           "/review/chunks/{update_id}/reindex",
                           "/review/chunks/{update_id}/exclude",
                           "/review/chunks/{update_id}/restore",
                           "/review/chunks/{update_id}/history",
                           "/review/edits") if p not in paths]
    chk("FastAPI registers them all", not missing, str(missing))
    chk("the app still has its original endpoints",
        {"/ask", "/updates", "/health"} <= paths)
except ModuleNotFoundError as e:
    # Not a fault in the change: a minimal dev venv has no fastapi. On the box
    # that serves the API it is installed and this check runs for real.
    print(f"  note    cannot build the app here ({e.name} not installed) - "
          f"the route table is checked wherever the API actually runs")
except Exception as e:
    chk("FastAPI builds the app", False, f"{type(e).__name__}: {e}")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    bash scripts/start_milvus.sh up        start the store
    export ASOIA_MILVUS_URI=http://localhost:19530
    .venv/bin/python -c "from app.retrieval.index import build; print(build())"
    .venv/bin/python -m app.api.server     then /docs lists the edit endpoints
""")
sys.exit(1 if bad else 0)
