#!/usr/bin/env python3
"""Thirty-first pass: one command up, one command down.

Run from the project root:   .venv/bin/python quality_pass31.py

Starting this project meant five things in a fixed order, three of them
backgrounded by hand, and the order mattered - Milvus before the API, because the
API reads the store on the way up. That is a runbook, and a runbook is a bug
report about the tooling.

1. scripts/stack.sh

       bash scripts/stack.sh up             store, API, UI - in that order
       bash scripts/stack.sh up --share     ... and a public gradio.live link
       bash scripts/stack.sh up --nims      ... and the three local NIMs
       bash scripts/stack.sh status         what is up, and is it answering
       bash scripts/stack.sh logs ui        ui | api | milvus
       bash scripts/stack.sh restart
       bash scripts/stack.sh down

   Four things in it are load-bearing.

   PID FILES, NOT pgrep. `pgrep -f app.ui.gradio_app` matches the ssh command
   line that launched the server, and it matches this script. That is how a
   duplicate UI hid behind

       OSError: Cannot find empty port in range: 7860-7860

   for twenty minutes. Each service writes run/<name>.pid, and `alive` reads the
   command line of that pid back to confirm it is still the process we started -
   so a pid file left behind by a killed process is detected, not believed.

   THE CHILD WRITES THE PID FILE, NOT `echo $!`. setsid forks when it is already
   a process group leader and execs when it is not, so `$!` is whichever of the
   two happened to occur. Measured on the box: `$!` reported 77108 while the
   process was 77110. So bash writes its own pid and then execs python over
   itself, and the file holds the server by construction rather than by luck.

   HEALTH IS WAITED FOR, NOT SLEPT AT. And "answering" is the test, not "200":
   the UI returns 401 for its own login page once GRADIO_AUTH is set, and that is
   a healthy UI.

   --nims DOES NOT REPOINT THE APP. Starting the containers and using them are
   separate decisions, because they are different embedders at different widths -
   hosted nemotron-3-embed-1b is 2048, local nv-embedqa-e5-v5 is 1024, and the
   index is built at one of them. Flipping NIM_MODE without rebuilding leaves a
   store whose vectors and queries disagree, and every search fails. `status`
   says so when the containers are up and NIM_MODE is hosted, because ~41GB of
   VRAM serving nothing is otherwise invisible.

2. The store survives a reboot.

   `--restart unless-stopped` on the Milvus container: it comes back by itself
   after a reboot or a docker daemon restart, and stays down when it is stopped
   deliberately. A restart policy is fixed at create time, so `up` also applies
   it to a container that predates this change with `docker update` - an existing
   install does not have to be recreated, or dropped mid-request, to gain it.

3. .env.example said the wrong things.

   It named neither the store nor NIM_MODE, and it recommended ASOIA_NOW for
   reproducibility - which pass 25 made unnecessary, since the clock follows the
   newest event in the log.
"""
import sys, pathlib, os, re, stat, subprocess

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


# ==================== 1. the launcher
write('scripts/stack.sh',
      '#!/usr/bin/env bash\n# The whole stack, one command up and one command down.\n#\n#   bash scripts/stack.sh up             Milvus, the API, the UI\n#   bash scripts/stack.sh up --share     ... and publish a gradio.live link\n#   bash scripts/stack.sh up --nims      ... and the three local NIMs as well\n#   bash scripts/stack.sh status         what is running, and is it answering\n#   bash scripts/stack.sh logs ui        tail one service (ui|api|milvus)\n#   bash scripts/stack.sh restart        down, then up with the same options\n#   bash scripts/stack.sh down           stop the store, the API and the UI\n#   bash scripts/stack.sh down --nims    ... and the NIMs too\n#\n# WHY PID FILES AND NOT pgrep\n#\n# `pgrep -f app.ui.gradio_app` matches more than the server. It matches the ssh\n# command line that launched it and it matches this script, which is how twenty\n# minutes went into a port conflict that was really a second copy of the UI. So\n# each service writes run/<name>.pid, and `alive` checks not just that the pid\n# exists but that it is still the process we started, by reading its command\n# line back. A pid file left behind by a killed process is detected, not\n# believed.\n#\n# WHY setsid nohup\n#\n# Both servers must outlive the shell that starts them, and they do: the ssh\n# session that launched them has been killed twice without interrupting a\n# request. Without setsid they sit in that session\'s process group and die with\n# it.\n#\n# WHAT THIS DELIBERATELY DOES NOT CHANGE: NIM_MODE\n#\n# --nims starts the local containers. It does NOT point the app at them, and the\n# reason is a dimension:\n#\n#     hosted   nvidia/nemotron-3-embed-1b   2048\n#     local    nvidia/nv-embedqa-e5-v5      1024\n#\n# The index in Milvus was built at 2048. Switching the embedder without\n# rebuilding gives you a store whose vectors and queries are different widths,\n# and every search fails. If you do want the local NIMs serving traffic - the\n# reranker only exists locally, the hosted catalogue has no reranking model -\n# then set NIM_MODE=local in .env and rebuild the index:\n#\n#     .venv/bin/python -c "from app.retrieval.index import build; print(build())"\n#\n# That is a deliberate act with a five-minute cost, not something a launcher\n# should do to you as a side effect of an --nims flag.\nset -uo pipefail\ncd "$(dirname "${BASH_SOURCE[0]}")/.."\nROOT="$(pwd)"\n\n[ -f .env ] && { set -a; . ./.env; set +a; }\n\nPY="${PY:-.venv/bin/python}"\ncase "$PY" in /*) PYABS="$PY" ;; *) PYABS="$ROOT/$PY" ;; esac\nRUN="$ROOT/run"\nAPI_PORT="${API_PORT:-8080}"\nUI_PORT="${PORT:-7860}"\nMILVUS_WEB="${MILVUS_WEB_PORT:-9091}"\nmkdir -p "$RUN"\n\n# ---------------------------------------------------------------- process table\n# name : module : port : log\nsvc_module() { case "$1" in api) echo app.api.server ;; ui) echo app.ui.gradio_app ;; esac; }\nsvc_port()   { case "$1" in api) echo "$API_PORT" ;;   ui) echo "$UI_PORT" ;; esac; }\nsvc_log()    { echo "/tmp/asoia-$1.log"; }\n# The API has no route at /, so probing / reported a perfectly healthy API as\n# http=404. Each service is asked the question it can answer.\nsvc_health() { case "$1" in api) echo "/health" ;; ui) echo "/" ;; esac; }\nsvc_pidfile(){ echo "$RUN/$1.pid"; }\n\n# Is the pid in the pidfile still OUR process? `ps -o args=` works the same on\n# Linux and macOS, which /proc does not.\nalive() {\n  local name="$1" f pid\n  f="$(svc_pidfile "$name")"\n  [ -f "$f" ] || return 1\n  pid="$(cat "$f" 2>/dev/null)"\n  [ -n "${pid:-}" ] || return 1\n  kill -0 "$pid" 2>/dev/null || return 1\n  ps -p "$pid" -o args= 2>/dev/null | grep -q "$(svc_module "$name")" || return 1\n  echo "$pid"\n}\n\n# Who is listening on a port, if the kernel will tell us. Needed because a\n# server started by hand - or by an earlier version of this script - holds the\n# port with no pid file, and starting a second copy is how you get\n#   OSError: Cannot find empty port in range: 7860-7860\n# reported as a bug in gradio.\nport_pid() {\n  local p="$1" pid=""\n  pid="$(ss -ltnpH "sport = :$p" 2>/dev/null \\\n         | grep -oE \'pid=[0-9]+\' | head -1 | cut -d= -f2)"\n  [ -n "$pid" ] || pid="$(lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null | head -1)"\n  echo "$pid"\n}\n\n# Claim a server that is already serving without a pid file, but only if it is\n# really ours: same module in its command line. Adoption means `up` is a no-op on\n# a box where the services were started by hand, instead of a port collision.\nadopt() {\n  local name="$1" pid\n  pid="$(port_pid "$(svc_port "$name")")"\n  [ -n "$pid" ] || return 1\n  ps -p "$pid" -o args= 2>/dev/null | grep -q "$(svc_module "$name")" || return 1\n  echo "$pid" > "$(svc_pidfile "$name")"\n  echo "$pid"\n}\n\nhttp_code() { curl -s -o /dev/null -w \'%{http_code}\' --max-time 4 "$1" 2>/dev/null; }\n\n# Answering at all is the test, not answering 200: the UI returns 401 for the\n# login page when GRADIO_AUTH is set, and that is a healthy UI.\nanswering() { case "$(http_code "$1")" in 000|"") return 1 ;; *) return 0 ;; esac; }\n\nwait_for() { # url label seconds\n  local url="$1" label="$2" secs="${3:-60}" i=0\n  printf \'     waiting for %s\' "$label"\n  while [ "$i" -lt "$secs" ]; do\n    if answering "$url"; then echo " ok"; return 0; fi\n    printf \'.\'; sleep 2; i=$((i + 2))\n  done\n  echo " timed out after ${secs}s"\n  return 1\n}\n\nstart_svc() { # name [env assignments...]\n  local name="$1"; shift\n  local pid log module\n  module="$(svc_module "$name")"\n  log="$(svc_log "$name")"\n  if pid="$(alive "$name")"; then\n    echo "  ==  $name already running (pid $pid)"\n    return 0\n  fi\n  if pid="$(adopt "$name")"; then\n    echo "  ==  $name already serving on :$(svc_port "$name") (pid $pid, adopted)"\n    return 0\n  fi\n  # The port is busy but not by us. Say so here, rather than letting the server\n  # start and die on a port-in-use error that names neither the holder nor the\n  # reason.\n  if pid="$(port_pid "$(svc_port "$name")")" && [ -n "$pid" ]; then\n    echo "  !!  :$(svc_port "$name") is held by pid $pid, which is not $module:"\n    ps -p "$pid" -o args= 2>/dev/null | tail -1 | cut -c1-100 | sed \'s/^/        /\'\n    return 1\n  fi\n  [ -x "$PY" ] || { echo "  !!  no $PY - see README"; return 1; }\n  : > "$log"\n  # PYTHONUNBUFFERED, because without it the log stays empty while the process\n  # is perfectly healthy and you go looking for a crash that never happened.\n  # `echo $!` does NOT give you the server. setsid forks when it is already a\n  # process group leader and execs when it is not, so $! is whichever of the two\n  # happened: measured on this box, $! reported 77108 while the process was\n  # 77110. So bash writes its OWN pid and then execs python over itself - the pid\n  # file holds the python process by construction, not by luck.\n  ( export PYTHONUNBUFFERED=1\n    for kv in "$@"; do export "$kv"; done\n    setsid nohup bash -c \'echo $$ > "$1"; exec "$2" -m "$3"\' _ \\\n      "$(svc_pidfile "$name")" "$PYABS" "$module" >"$log" 2>&1 </dev/null & )\n  sleep 2\n  if ! pid="$(alive "$name")"; then\n    echo "  !!  $name died immediately. Last lines of $log:"\n    tail -15 "$log" | sed \'s/^/        /\'\n    return 1\n  fi\n  echo "  ->  $name started (pid $pid), log $log"\n}\n\nstop_svc() { # name\n  local name="$1" pid f i=0\n  f="$(svc_pidfile "$name")"\n  # adopt first: a server started by hand has no pid file, and `down` reporting\n  # "was not running" while it carries on serving is the worst of the options.\n  if ! pid="$(alive "$name")" && ! pid="$(adopt "$name")"; then\n    [ -f "$f" ] && rm -f "$f" && echo "  --  $name was not running (stale pid file removed)" \\\n                || echo "  --  $name was not running"\n    return 0\n  fi\n  kill -TERM "$pid" 2>/dev/null\n  while [ "$i" -lt 10 ]; do\n    alive "$name" >/dev/null || break\n    sleep 1; i=$((i + 1))\n  done\n  if alive "$name" >/dev/null; then\n    kill -KILL "$pid" 2>/dev/null\n    echo "  --  $name did not stop on SIGTERM, killed (pid $pid)"\n  else\n    echo "  --  $name stopped (pid $pid)"\n  fi\n  rm -f "$f"\n}\n\nshare_url() { grep -oE \'https://[a-z0-9]+\\.gradio\\.live\' "$(svc_log ui)" 2>/dev/null | tail -1; }\n\n# The local NIMs can be running while the app ignores them completely. That is\n# ~41GB of VRAM doing nothing, and it is invisible unless something says so.\nnim_advice() {\n  local running\n  running="$(docker ps --filter \'name=nim-\' --format \'{{.Names}}\' 2>/dev/null | wc -l | tr -d \' \')"\n  [ "${running:-0}" -gt 0 ] || return 0\n  case "${NIM_MODE:-auto}" in\n    hosted)\n      echo "  note  $running local NIM container(s) are up, but NIM_MODE=hosted -"\n      echo "        the app is calling build.nvidia.com and not using them."\n      echo "        Free the VRAM with: bash scripts/start_nims.sh stop" ;;\n    *) echo "  note  $running local NIM container(s) up, NIM_MODE=${NIM_MODE:-auto}" ;;\n  esac\n}\n\n# ---------------------------------------------------------------------- actions\nup() {\n  local share=0 nims=0 pid=""\n  for a in "$@"; do case "$a" in\n    --share) share=1 ;;\n    --nims)  nims=1 ;;\n    *) echo "unknown option: $a"; exit 2 ;;\n  esac; done\n\n  echo "==> the vector store"\n  # MILVUS_QUIET: start_milvus.sh ends with advice about pointing the app at the\n  # store and rebuilding the index, which is right when you run it by hand and\n  # wrong here - `status` below reads the real index and says what is in it, and\n  # "rebuild, an embedded index does not move across" is alarming nonsense next\n  # to a line reporting 1,949 chunks.\n  MILVUS_QUIET=1 bash scripts/start_milvus.sh up | sed \'s/^/  /\' || exit 1\n\n  if [ "$nims" = 1 ]; then\n    echo "==> the local NIMs"\n    bash scripts/start_nims.sh run 2>&1 | sed \'s/^/  /\'\n    echo "  (first start builds TRT engines - minutes, not seconds)"\n  fi\n\n  echo "==> the API"\n  start_svc api || exit 1\n  wait_for "http://localhost:$API_PORT$(svc_health api)" "the API" 90 || {\n    tail -15 "$(svc_log api)" | sed \'s/^/        /\'; exit 1; }\n\n  echo "==> the UI"\n  if [ "$share" = 1 ]; then\n    if [ -z "${GRADIO_AUTH:-}" ]; then\n      echo "  !!  --share with no GRADIO_AUTH. The gradio.live link is public and"\n      echo "      the Technician Update tab WRITES to the event log. Put"\n      echo "      GRADIO_AUTH=user:password in .env, or drop --share."\n      exit 2\n    fi\n    # The tunnel is opened during launch and cannot be added to a process that is\n    # already serving. Without this, --share on a running UI adopted it, skipped\n    # the launch, and then reported whatever URL was left in the log - a dead\n    # link presented as the live one.\n    if pid="$(alive ui)" || pid="$(adopt ui)"; then\n      if [ -n "$(share_url)" ]; then\n        echo "  ==  ui already running with a public link (pid $pid)"\n      else\n        echo "  !!  the UI is already running WITHOUT a public link (pid $pid),"\n        echo "      and a share tunnel cannot be added to a live process."\n        echo "      Restart it:  bash scripts/stack.sh restart --share"\n        exit 2\n      fi\n    else\n      start_svc ui SHARE=1 "GRADIO_AUTH=$GRADIO_AUTH" || exit 1\n    fi\n  else\n    start_svc ui || exit 1\n  fi\n  wait_for "http://localhost:$UI_PORT$(svc_health ui)" "the UI" 120 || {\n    tail -15 "$(svc_log ui)" | sed \'s/^/        /\'; exit 1; }\n\n  if [ "$share" = 1 ]; then\n    printf \'     waiting for the public link\'\n    for _ in $(seq 1 20); do\n      [ -n "$(share_url)" ] && break\n      printf \'.\'; sleep 3\n    done\n    echo\n  fi\n  echo\n  status\n}\n\ndown() {\n  local nims=0\n  for a in "$@"; do case "$a" in\n    --nims|--all) nims=1 ;;\n    *) echo "unknown option: $a"; exit 2 ;;\n  esac; done\n  echo "==> stopping"\n  stop_svc ui\n  stop_svc api\n  bash scripts/start_milvus.sh down | sed \'s/^/  --  /\'\n  if [ "$nims" = 1 ]; then\n    bash scripts/start_nims.sh stop 2>&1 | sed \'s/^/  --  /\'\n  else\n    local n\n    n="$(docker ps --filter \'name=nim-\' --format \'{{.Names}}\' 2>/dev/null | tr \'\\n\' \' \')"\n    [ -n "${n// /}" ] && echo "  ==  left running: $n" \\\n      && echo "      (they cache TRT engines; stop them with --nims if you want the VRAM back)"\n  fi\n  echo "done."\n}\n\nstatus() {\n  local pid code url\n  echo "STACK"\n  printf \'  %-9s \' "milvus"\n  if answering "http://localhost:$MILVUS_WEB/healthz"; then\n    echo "up    localhost:${MILVUS_PORT:-19530}  ($(docker inspect -f \'{{.State.Status}}, restart={{.HostConfig.RestartPolicy.Name}}\' "${MILVUS_CONTAINER:-asoia-milvus}" 2>/dev/null || echo \'not a container\'))"\n  else\n    echo "DOWN  bash scripts/stack.sh up"\n  fi\n  for name in api ui; do\n    printf \'  %-9s \' "$name"\n    if pid="$(alive "$name")" || pid="$(adopt "$name")"; then\n      code="$(http_code "http://localhost:$(svc_port "$name")$(svc_health "$name")")"\n      echo "up    pid $pid  :$(svc_port "$name")  http=$code"\n    else\n      echo "DOWN"\n    fi\n  done\n  url="$(share_url)"\n  [ -n "$url" ] && alive ui >/dev/null && echo "  public    $url"\n  echo\n  echo "DATA"\n  # Only ask the store when it is answering. Otherwise this printed\n  #   index     ? chunks at None dims\n  # which is a stack trace\'s worth of confusion in place of "it is not running".\n  if ! answering "http://localhost:$MILVUS_WEB/healthz"; then\n    echo "  index     unreadable - the store is not running"\n  elif [ -x "$PY" ]; then\n    "$PY" - <<\'PYEOF\' 2>/dev/null || echo "  (could not read the store - is Milvus up?)"\nfrom app.retrieval.backend import backend\nfrom app.review.store import index_staleness\nst = index_staleness()\nprint(f"  index     {st.get(\'index_rows\', \'?\')} chunks at {backend().dim()} dims, "\n      f"{st.get(\'database_updates\', \'?\')} updates in the database")\n# The key names are the ones index_staleness() actually returns. Guessing them\n# is how a health line ends up reporting "ok" out of .get() defaults forever.\nflags = [k for k in (\'dangling\', \'unindexed\', \'text_drift\', \'excluded\')\n         if st.get(k)]\nprint("  integrity " + ("ok" if st.get("ok") and not flags else\n      ", ".join(f"{k}={st[k]}" for k in flags) or "see /health"))\nPYEOF\n  fi\n  echo\n  nim_advice\n  echo\n  echo "  logs: bash scripts/stack.sh logs ui | api | milvus"\n}\n\ncase "${1:-status}" in\n  up)      shift; up "$@" ;;\n  down)    shift; down "$@" ;;\n  restart) shift; down; echo; up "$@" ;;\n  status)  status ;;\n  logs)\n    case "${2:-ui}" in\n      milvus) bash scripts/start_milvus.sh logs ;;\n      api|ui) tail -f "$(svc_log "${2}")" ;;\n      *) echo "logs: ui | api | milvus"; exit 2 ;;\n    esac ;;\n  *) sed -n \'2,11p\' "${BASH_SOURCE[0]}" | sed \'s/^# \\{0,1\\}//\'; exit 2 ;;\nesac\n',
      'scripts/stack.sh  the whole stack, up and down',
      executable=True)

# ==================== 2. the store survives a reboot
edit('scripts/start_milvus.sh',
     '  if docker ps --format \'{{.Names}}\' | grep -qx "$NAME"; then\n    echo "already running: $NAME"\n  else\n',
     '  if docker ps --format \'{{.Names}}\' | grep -qx "$NAME"; then\n    echo "already running: $NAME"\n    # A container created before this script had a restart policy does not gain\n    # one when the script changes - the policy is fixed at create time. `docker\n    # update` applies it in place, so an existing install survives the next\n    # reboot without being recreated and without dropping a request.\n    docker update --restart unless-stopped "$NAME" >/dev/null 2>&1 \\\n      && echo "  restart policy: unless-stopped"\n  else\n',
     'start_milvus.sh  apply the policy to a container that predates it',
     skip_if='docker update --restart unless-stopped')

edit('scripts/start_milvus.sh',
     '    docker run -d --name "$NAME" \\\n      -p "${PORT}:19530" -p "${WEB}:9091" \\\n',
     '    # --restart unless-stopped: the store comes back by itself after a reboot or\n    # a docker daemon restart, and stays down when you stop it deliberately.\n    # Without it the box comes up with a UI that reports a broken store and an\n    # index that reads as empty, which looks like data loss and is not.\n    docker run -d --name "$NAME" --restart unless-stopped \\\n      -p "${PORT}:19530" -p "${WEB}:9091" \\\n',
     'start_milvus.sh  --restart unless-stopped on create',
     skip_if='--name "$NAME" --restart unless-stopped')


edit('scripts/start_milvus.sh',
     '  if docker ps --format \'{{.Names}}\' | grep -qx "$NAME"; then\n    echo "already running: $NAME"\n',
     '  # Whether we CREATED it decides what is worth saying at the end. Telling\n  # someone to rebuild an index "because an embedded one does not move across" is\n  # false and alarming when the container was already up with a healthy index in\n  # it, and this script is now called by scripts/stack.sh on every start.\n  CREATED=0\n  if docker ps --format \'{{.Names}}\' | grep -qx "$NAME"; then\n    echo "already running: $NAME"\n',
     'start_milvus.sh  remember whether we created the container',
     skip_if='CREATED=0')

edit('scripts/start_milvus.sh',
     '    echo "starting $NAME from $IMAGE ..."\n',
     '    CREATED=1\n    echo "starting $NAME from $IMAGE ..."\n',
     'start_milvus.sh  set it on the create path',
     skip_if='CREATED=1')

edit('scripts/start_milvus.sh',
     '      echo; echo "ready on localhost:${PORT}"\n      echo\n      echo "Point the app at it:"\n      echo "  export ASOIA_MILVUS_URI=http://localhost:${PORT}"\n      echo "and rebuild, because an embedded index does not move across:"\n      echo "  .venv/bin/python -c \'from app.retrieval.index import build; print(build())\'"\n      exit 0\n',
     '      echo; echo "ready on localhost:${PORT}"\n      if [ "$CREATED" = 1 ]; then\n        echo\n        echo "Point the app at it:"\n        echo "  export ASOIA_MILVUS_URI=http://localhost:${PORT}"\n        echo "and rebuild, because an embedded index does not move across:"\n        echo "  .venv/bin/python -c \'from app.retrieval.index import build; print(build())\'"\n      fi\n      exit 0\n',
     'start_milvus.sh  only advise a rebuild when there is a new store',
     skip_if='if [ "$CREATED" = 1 ]; then')

edit('scripts/start_milvus.sh',
     '      if [ "$CREATED" = 1 ]; then\n',
     '      if [ "$CREATED" = 1 ] && [ -z "${MILVUS_QUIET:-}" ]; then\n',
     'start_milvus.sh  MILVUS_QUIET for callers that report the index themselves',
     skip_if='MILVUS_QUIET')

# ==================== 3. pid files are not source
# A write(), not an edit(): the anchor `*.egg-info/\n*.bak\n` SURVIVES its own
# replacement, so the edit applied cleanly on every run and left three copies of
# run/ in the file. An edit whose anchor is still there afterwards cannot be
# idempotent, however careful the skip_if is - writing the whole file can only
# ever produce one outcome.
write('.gitignore', '.env\n__pycache__/\n*.pyc\n.venv/\ndata/generated/*\n!data/generated/.gitkeep\n*.lance/\n.ipynb_checkpoints/\n.pytest_cache/\n*.egg-info/\n*.bak\n# pid files written by scripts/stack.sh\nrun/\n', '.gitignore  run/')

# ==================== 4. .env.example, saying the right things
write('.env.example', '# Copy to .env and fill in. .env is gitignored and must never be committed.\n# Get a key from https://build.nvidia.com (free tier: ~40 requests/minute).\nNVIDIA_API_KEY=nvapi-your-key-here\n\n# The vector store. Unset falls back to embedded Milvus Lite at\n# data/generated/milvus.db, which takes an EXCLUSIVE FILE LOCK - one process at a\n# time, so the UI and the API cannot both be up. Standalone has no such problem:\n#   bash scripts/start_milvus.sh up\nASOIA_MILVUS_URI=http://localhost:19530\n\n# Where the models run. `auto` probes for a local NIM and falls back to the\n# hosted endpoints; `hosted` skips the probe; `local` requires the containers.\n# Changing this CHANGES THE EMBEDDER, and the two are different widths -\n# nemotron-3-embed-1b is 2048, nv-embedqa-e5-v5 is 1024 - so rebuild the index\n# after you switch it or every search fails on a dimension mismatch.\nNIM_MODE=hosted\n\n# Required before scripts/stack.sh will publish a public gradio.live link. That\n# link is world-reachable and the Technician Update tab writes to the event log.\n# GRADIO_AUTH=demo:choose-something\n\n# Optional. Pins "now". You do not need it: the clock follows the newest event in\n# the log, so a dataset never goes stale. Set it only when you want a fixed\n# clock, e.g. to reproduce a specific run.\n# ASOIA_NOW=2026-09-24T20:03:00\n',
      '.env.example  the store, NIM_MODE, GRADIO_AUTH')


# ==================== 5. the README
edit('README.md',
     '## Other ways in\n\n```bash\nbash scripts/start_api.sh --detach          # HTTP API on :8080, /docs for OpenAPI\nbash scripts/start_observability.sh up      # Prometheus :9090 + Grafana :3000\n```\n',
     '## Running it\n\nOne command, in dependency order — Milvus first, because the API reads the store\non the way up:\n\n```bash\nbash scripts/stack.sh up                 # store + API :8080 + UI :7860\nbash scripts/stack.sh up --share         # ... and a public gradio.live link\nbash scripts/stack.sh status             # what is up, and is it answering\nbash scripts/stack.sh logs ui            # ui | api | milvus\nbash scripts/stack.sh down               # stop all three\n```\n\nEach service is waited for rather than slept at, and `status` reads the store as\nwell as the ports: chunk count, dimension, and whether the index still agrees\nwith the database. The store carries `--restart unless-stopped`, so it comes back\nafter a reboot on its own.\n\n`--share` refuses to run without `GRADIO_AUTH=user:password` in `.env`. The\n`gradio.live` URL is world-reachable and the Technician Update tab writes to the\nevent log; a random subdomain is not a credential.\n\n`--nims` starts the three local NIM containers but does **not** point the app at\nthem. That is deliberate: the hosted embedder is 2048-dimensional and the local\none is 1024, so switching `NIM_MODE` without rebuilding the index leaves vectors\nand queries at different widths and every search fails. Switch it in `.env` and\nrebuild, knowingly.\n\n## Other ways in\n\n```bash\nbash scripts/start_api.sh --detach          # HTTP API on :8080, /docs for OpenAPI\nbash scripts/start_observability.sh up      # Prometheus :9090 + Grafana :3000\nbash scripts/start_milvus.sh up             # just the vector store\n```\n',
     'README.md  a Running it section',
     skip_if='## Running it')

edit('README.md',
     '| `API_PORT` | `8080` | the HTTP API |\n',
     "| `API_PORT` | `8080` | the HTTP API |\n| `PORT` | `7860` | the Gradio UI |\n| `ASOIA_MILVUS_URI` | embedded file | `http://localhost:19530` for standalone; unset locks the store to one process |\n| `VECTOR_BACKEND` | `milvus` | `lance` restores the previous store |\n| `NIM_MODE` | `auto` | `hosted` skips the local probe, `local` requires the containers; changing it changes the embedder, so rebuild the index |\n| `ASOIA_REVIEW_WRITES` | `1` | `0` makes the API's four edit endpoints return 403 |\n| `GRADIO_AUTH` | — | `user:password`; required by `stack.sh up --share` |\n| `SHARE` | `0` | `1` publishes a `*.gradio.live` link |\n",
     'README.md  the environment table',
     skip_if='| `ASOIA_MILVUS_URI` |')# ==================== verify
print("Quality pass 31:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


def run(*a):
    return subprocess.run(a, capture_output=True, text=True)


print("\nthe launcher:")
sh = ROOT / "scripts/stack.sh"
chk("it is executable", os.access(sh, os.X_OK))
r = run("bash", "-n", str(sh))
chk("it is valid bash", r.returncode == 0, (r.stderr or "").strip()[:120])
body = sh.read_text()

chk("the pid file is written by the child, not by $!",
    "echo $$ > " in body and "echo $! >" not in body,
    "setsid forks or execs depending on the process group; $! is not the server")
chk("alive() reads the command line of that pid back",
    'ps -p "$pid" -o args=' in body,
    "a pid file left by a killed process must not be believed")
# The WORD appears - the comment above alive() explains why pgrep is wrong. What
# must not appear is a CALL. Checking for the word asserted the documentation.
_pg = [l for l in body.splitlines()
       if "pgrep" in l and not l.lstrip().startswith("#")]
chk("nothing greps the process table for the module name", not _pg,
    "it matches the ssh command line and this script too")
chk("services are waited for, not slept at",
    "wait_for " in body and body.count("answering ") >= 2)
chk("a non-200 answer still counts as up",
    "000|" in body, "gradio returns 401 for its own login page")
chk("a server already serving without a pid file is adopted, not duplicated",
    "adopted)" in body and 'pid="$(adopt "$name")"' in body,
    "otherwise `up` on a hand-started box is a port collision")
chk("a port held by something else is reported, not walked into",
    "is held by pid" in body)
chk("--share on a live UI is refused rather than reporting a stale link",
    "a share tunnel cannot be added to a live process" in body,
    "the tunnel is opened at launch; adopting one skipped the launch")
chk("down adopts before concluding nothing is running",
    '! pid="$(alive "$name")" && ! pid="$(adopt "$name")"' in body,
    "otherwise a hand-started server survives `down`")
chk("--share refuses to publish without GRADIO_AUTH",
    'if [ -z "${GRADIO_AUTH:-}" ]; then' in body)
# The point is not that the string is absent - nim_advice() prints it. It is
# that the launcher never ASSIGNS it, because hosted is 2048-dimensional and
# local is 1024 and the index is built at one of the two.
_sets = [l for l in body.splitlines()
         if re.match(r"\s*(export\s+)?NIM_MODE=", l)]
chk("--nims does not repoint the app", not _sets, str(_sets)[:70])
chk("status names the mismatch when it is live",
    "nim_advice" in body and "not using them" in body)
chk("it uses the keys index_staleness() really returns",
    "database_updates" in body and "db_rows" not in body,
    "guessing them yields a health line that reports ok forever")
missing = [s for s in ("up)", "down)", "status)", "logs)", "restart)")
           if f"  {s}" not in body]
chk("every subcommand is dispatched", not missing, str(missing))
r = run("bash", str(sh), "nonsense")
chk("an unknown subcommand exits 2", r.returncode == 2)
chk("...and prints the usage block",
    "stack.sh up" in (r.stdout or ""),
    (r.stdout or "").strip().splitlines()[0][:50] if r.stdout else "no output")

print("\nthe restart policy:")
mv = (ROOT / "scripts/start_milvus.sh").read_text()
chk("the container is created with it",
    '--name "$NAME" --restart unless-stopped' in mv)
chk("an existing container is updated in place",
    "docker update --restart unless-stopped" in mv,
    "the policy is fixed at create time, so a running store needs this")
chk("start_milvus.sh is still valid bash",
    run("bash", "-n", "scripts/start_milvus.sh").returncode == 0)

print("\nthe documentation:")
rm = (ROOT / "README.md").read_text()
chk("README documents the launcher", "bash scripts/stack.sh up" in rm)
chk("README explains why --nims is not a switch",
    "2048-dimensional" in rm and "1024" in rm)
chk("the environment table lists the store",
    "| `ASOIA_MILVUS_URI` |" in rm)
ee = (ROOT / ".env.example").read_text()
chk(".env.example covers the store and NIM_MODE",
    "ASOIA_MILVUS_URI" in ee and "NIM_MODE" in ee)
chk(".env.example no longer sells ASOIA_NOW as needed for reproducibility",
    "reproducible" not in ee, "pass 25 made the clock follow the data")
chk(".env.example still carries no real key",
    "nvapi-your-key-here" in ee and ee.count("nvapi-") == 1)
chk("run/ is ignored", "run/" in (ROOT / ".gitignore").read_text())

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    bash scripts/stack.sh up --share     start the store, the API and the UI
    bash scripts/stack.sh status         confirm it, and read the index
    bash scripts/stack.sh down           stop all three
""")
sys.exit(1 if bad else 0)
