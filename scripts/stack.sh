#!/usr/bin/env bash
# The whole stack, one command up and one command down.
#
#   bash scripts/stack.sh up             Milvus, the API, the UI
#   bash scripts/stack.sh up --share     ... and publish a gradio.live link
#   bash scripts/stack.sh up --nims      ... and the three local NIMs as well
#   bash scripts/stack.sh status         what is running, and is it answering
#   bash scripts/stack.sh stores         the data stores, and their admin UIs
#   bash scripts/stack.sh logs ui        tail one service (ui|api|milvus)
#   bash scripts/stack.sh restart        down, then up with the same options
#   bash scripts/stack.sh down           stop the store, the API and the UI
#   bash scripts/stack.sh down --nims    ... and the NIMs too
#
# WHY PID FILES AND NOT pgrep
#
# `pgrep -f app.ui.gradio_app` matches more than the server. It matches the ssh
# command line that launched it and it matches this script, which is how twenty
# minutes went into a port conflict that was really a second copy of the UI. So
# each service writes run/<name>.pid, and `alive` checks not just that the pid
# exists but that it is still the process we started, by reading its command
# line back. A pid file left behind by a killed process is detected, not
# believed.
#
# WHY setsid nohup
#
# Both servers must outlive the shell that starts them, and they do: the ssh
# session that launched them has been killed twice without interrupting a
# request. Without setsid they sit in that session's process group and die with
# it.
#
# WHAT THIS DELIBERATELY DOES NOT CHANGE: NIM_MODE
#
# --nims starts the local containers. It does NOT point the app at them, and the
# reason is a dimension:
#
#     hosted   nvidia/nemotron-3-embed-1b   2048
#     local    nvidia/nv-embedqa-e5-v5      1024
#
# The index in Milvus was built at 2048. Switching the embedder without
# rebuilding gives you a store whose vectors and queries are different widths,
# and every search fails. If you do want the local NIMs serving traffic - the
# reranker only exists locally, the hosted catalogue has no reranking model -
# then set NIM_MODE=local in .env and rebuild the index:
#
#     .venv/bin/python scripts/build_index.py
#
# That script loads .env first, which the bare one-liner that used to be
# printed here did not - so it rebuilt the EMBEDDED Milvus Lite file with the
# HOSTED embedder, and reported success.
#
# That is a deliberate act with a five-minute cost, not something a launcher
# should do to you as a side effect of an --nims flag.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"

[ -f .env ] && { set -a; . ./.env; set +a; }

# Operator view of the stores (pass 42). Sourced after .env so the
# admin ports and ASOIA_ADMIN can be set there.
. "$(dirname "$0")/stores.sh"

PY="${PY:-.venv/bin/python}"
case "$PY" in /*) PYABS="$PY" ;; *) PYABS="$ROOT/$PY" ;; esac
RUN="$ROOT/run"
API_PORT="${API_PORT:-8080}"
UI_PORT="${PORT:-7860}"
MILVUS_WEB="${MILVUS_WEB_PORT:-9091}"
mkdir -p "$RUN"

# ---------------------------------------------------------------- process table
# name : module : port : log
svc_module() { case "$1" in api) echo app.api.server ;; ui) echo app.ui.gradio_app ;; esac; }
svc_port()   { case "$1" in api) echo "$API_PORT" ;;   ui) echo "$UI_PORT" ;; esac; }
svc_log()    { echo "/tmp/asoia-$1.log"; }
# The API has no route at /, so probing / reported a perfectly healthy API as
# http=404. Each service is asked the question it can answer.
svc_health() { case "$1" in api) echo "/health" ;; ui) echo "/" ;; esac; }
# setsid is Linux-only and macOS has no equivalent. The box this was written for
# was Linux, so `setsid` was called unguarded and `stack.sh up` died on a Mac
# with `setsid: command not found` - which only surfaced once the box was gone
# and the Mac was the only machine left.
#
# The reason setsid was used still holds on Linux: an ssh session being killed
# would otherwise take the servers' process group with it. `nohup` alone detaches
# from the terminal but not from the process group, which is enough when nothing
# is going to kill a session - the local case - and is why the fallback is
# acceptable rather than merely convenient.
detach() {
  if command -v setsid >/dev/null 2>&1; then setsid nohup "$@"
  else nohup "$@"
  fi
}

svc_pidfile(){ echo "$RUN/$1.pid"; }

# Is the pid in the pidfile still OUR process? `ps -o args=` works the same on
# Linux and macOS, which /proc does not.
alive() {
  local name="$1" f pid
  f="$(svc_pidfile "$name")"
  [ -f "$f" ] || return 1
  pid="$(cat "$f" 2>/dev/null)"
  [ -n "${pid:-}" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o args= 2>/dev/null | grep -q "$(svc_module "$name")" || return 1
  echo "$pid"
}

# Who is listening on a port, if the kernel will tell us. Needed because a
# server started by hand - or by an earlier version of this script - holds the
# port with no pid file, and starting a second copy is how you get
#   OSError: Cannot find empty port in range: 7860-7860
# reported as a bug in gradio.
port_pid() {
  local p="$1" pid=""
  pid="$(ss -ltnpH "sport = :$p" 2>/dev/null \
         | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)"
  [ -n "$pid" ] || pid="$(lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null | head -1)"
  echo "$pid"
}

# Claim a server that is already serving without a pid file, but only if it is
# really ours: same module in its command line. Adoption means `up` is a no-op on
# a box where the services were started by hand, instead of a port collision.
adopt() {
  local name="$1" pid
  pid="$(port_pid "$(svc_port "$name")")"
  [ -n "$pid" ] || return 1
  ps -p "$pid" -o args= 2>/dev/null | grep -q "$(svc_module "$name")" || return 1
  echo "$pid" > "$(svc_pidfile "$name")"
  echo "$pid"
}

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 4 "$1" 2>/dev/null; }

# Answering at all is the test, not answering 200. It no longer serves a login, so
# 200 is what you should see - but a UI that is starting up, redirecting, or
# erroring is still a UI that is listening, and "is the port answering" is the
# question this is asking.
answering() { case "$(http_code "$1")" in 000|"") return 1 ;; *) return 0 ;; esac; }

wait_for() { # url label seconds
  local url="$1" label="$2" secs="${3:-60}" i=0
  printf '     waiting for %s' "$label"
  while [ "$i" -lt "$secs" ]; do
    if answering "$url"; then echo " ok"; return 0; fi
    printf '.'; sleep 2; i=$((i + 2))
  done
  echo " timed out after ${secs}s"
  return 1
}

start_svc() { # name [env assignments...]
  local name="$1"; shift
  local pid log module
  module="$(svc_module "$name")"
  log="$(svc_log "$name")"
  if pid="$(alive "$name")"; then
    echo "  ==  $name already running (pid $pid)"
    return 0
  fi
  if pid="$(adopt "$name")"; then
    echo "  ==  $name already serving on :$(svc_port "$name") (pid $pid, adopted)"
    return 0
  fi
  # The port is busy but not by us. Say so here, rather than letting the server
  # start and die on a port-in-use error that names neither the holder nor the
  # reason.
  if pid="$(port_pid "$(svc_port "$name")")" && [ -n "$pid" ]; then
    echo "  !!  :$(svc_port "$name") is held by pid $pid, which is not $module:"
    ps -p "$pid" -o args= 2>/dev/null | tail -1 | cut -c1-100 | sed 's/^/        /'
    return 1
  fi
  [ -x "$PY" ] || { echo "  !!  no $PY - see README"; return 1; }
  : > "$log"
  # PYTHONUNBUFFERED, because without it the log stays empty while the process
  # is perfectly healthy and you go looking for a crash that never happened.
  # `echo $!` does NOT give you the server. setsid forks when it is already a
  # process group leader and execs when it is not, so $! is whichever of the two
  # happened: measured on this box, $! reported 77108 while the process was
  # 77110. So bash writes its OWN pid and then execs python over itself - the pid
  # file holds the python process by construction, not by luck.
  ( export PYTHONUNBUFFERED=1
    for kv in "$@"; do export "$kv"; done
    detach bash -c 'echo $$ > "$1"; exec "$2" -m "$3"' _ \
      "$(svc_pidfile "$name")" "$PYABS" "$module" >"$log" 2>&1 </dev/null & )
  sleep 2
  if ! pid="$(alive "$name")"; then
    echo "  !!  $name died immediately. Last lines of $log:"
    tail -15 "$log" | sed 's/^/        /'
    return 1
  fi
  echo "  ->  $name started (pid $pid), log $log"
}

stop_svc() { # name
  local name="$1" pid f i=0
  f="$(svc_pidfile "$name")"
  # adopt first: a server started by hand has no pid file, and `down` reporting
  # "was not running" while it carries on serving is the worst of the options.
  if ! pid="$(alive "$name")" && ! pid="$(adopt "$name")"; then
    [ -f "$f" ] && rm -f "$f" && echo "  --  $name was not running (stale pid file removed)" \
                || echo "  --  $name was not running"
    return 0
  fi
  kill -TERM "$pid" 2>/dev/null
  while [ "$i" -lt 10 ]; do
    alive "$name" >/dev/null || break
    sleep 1; i=$((i + 1))
  done
  if alive "$name" >/dev/null; then
    kill -KILL "$pid" 2>/dev/null
    echo "  --  $name did not stop on SIGTERM, killed (pid $pid)"
  else
    echo "  --  $name stopped (pid $pid)"
  fi
  rm -f "$f"
}

share_url() { grep -oE 'https://[a-z0-9]+\.gradio\.live' "$(svc_log ui)" 2>/dev/null | tail -1; }

# Where each service ACTUALLY resolves. Ask the client; do not infer it from
# NIM_MODE. That inference was right for about a day and then stopped being the
# whole answer: with NIM_MODE=hosted and NIM_MODE_RERANK=local, "the app is not
# using them" was false about the reranker, which is the only service that has no
# hosted model at all. resolve() is the code that decides, so it is the only
# honest source for a status line.
routing() {
  [ -x "$PY" ] || return 0
  "$PYABS" - <<'PYEOF' 2>/dev/null
from app.nim.client import resolve
for s in ("llm", "embed", "rerank"):
    _base, model, mode = resolve(s)
    print(f"  {s:9s} {mode:7s} {model}")
PYEOF
}

# The local NIMs can be running while nothing routes to them. That is ~41GB of
# VRAM doing nothing, and it is invisible unless something says so.
nim_advice() {
  local running used
  running="$(docker ps --filter 'name=nim-' --format '{{.Names}}' 2>/dev/null | wc -l | tr -d ' ')"
  [ "${running:-0}" -gt 0 ] || return 0
  used="$(routing | grep -cw local)"
  if [ "${used:-0}" = 0 ]; then
    echo "  note  $running local NIM container(s) up and NOTHING routes to them."
    echo "        Free the VRAM with: bash scripts/start_nims.sh stop"
  else
    echo "  note  $running local NIM container(s) up, $used service(s) routed to them"
  fi
}

# ---------------------------------------------------------------------- actions
up() {
  local share=0 nims=0 pid=""
  for a in "$@"; do case "$a" in
    --share) share=1 ;;
    --nims)  nims=1 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac; done

  echo "==> the vector store"
  # MILVUS_QUIET: start_milvus.sh ends with advice about pointing the app at the
  # store and rebuilding the index, which is right when you run it by hand and
  # wrong here - `status` below reads the real index and says what is in it, and
  # "rebuild, an embedded index does not move across" is alarming nonsense next
  # to a line reporting 1,949 chunks.
  MILVUS_QUIET=1 bash scripts/start_milvus.sh up | sed 's/^/  /' || exit 1

  if [ "$nims" = 1 ]; then
    echo "==> the local NIMs"
    bash scripts/start_nims.sh run 2>&1 | sed 's/^/  /'
    echo "  (first start builds TRT engines - minutes, not seconds)"
  fi

  echo "==> the API"
  start_svc api || exit 1
  wait_for "http://localhost:$API_PORT$(svc_health api)" "the API" 90 || {
    tail -15 "$(svc_log api)" | sed 's/^/        /'; exit 1; }

  echo "==> the UI"
  if [ "$share" = 1 ]; then
    # There is no login in front of the public link, by decision. The UI prints
    # the same warning on startup; see app/ui/gradio_app.py. Nothing here blocks
    # --share any more, so a shared link is live the moment this returns.
    # The tunnel is opened during launch and cannot be added to a process that is
    # already serving. Without this, --share on a running UI adopted it, skipped
    # the launch, and then reported whatever URL was left in the log - a dead
    # link presented as the live one.
    if pid="$(alive ui)" || pid="$(adopt ui)"; then
      if [ -n "$(share_url)" ]; then
        echo "  ==  ui already running with a public link (pid $pid)"
      else
        echo "  !!  the UI is already running WITHOUT a public link (pid $pid),"
        echo "      and a share tunnel cannot be added to a live process."
        echo "      Restart it:  bash scripts/stack.sh restart --share"
        exit 2
      fi
    else
      start_svc ui SHARE=1 || exit 1
    fi
  else
    start_svc ui || exit 1
  fi
  wait_for "http://localhost:$UI_PORT$(svc_health ui)" "the UI" 120 || {
    tail -15 "$(svc_log ui)" | sed 's/^/        /'; exit 1; }

  if [ "$share" = 1 ]; then
    printf '     waiting for the public link'
    for _ in $(seq 1 20); do
      [ -n "$(share_url)" ] && break
      printf '.'; sleep 3
    done
    echo
  fi
  echo
  status
}

down() {
  local nims=0
  for a in "$@"; do case "$a" in
    --nims|--all) nims=1 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac; done
  echo "==> stopping"
  stop_svc ui
  stop_svc api
  bash scripts/start_milvus.sh down | sed 's/^/  --  /'
  if [ "$nims" = 1 ]; then
    bash scripts/start_nims.sh stop 2>&1 | sed 's/^/  --  /'
  else
    local n
    n="$(docker ps --filter 'name=nim-' --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
    [ -n "${n// /}" ] && echo "  ==  left running: $n" \
      && echo "      (they cache TRT engines; stop them with --nims if you want the VRAM back)"
  fi
  echo "done."
}

status() {
  local pid code url
  echo "STACK"
  printf '  %-9s ' "milvus"
  if answering "http://localhost:$MILVUS_WEB/healthz"; then
    echo "up    localhost:${MILVUS_PORT:-19530}  ($(docker inspect -f '{{.State.Status}}, restart={{.HostConfig.RestartPolicy.Name}}' "${MILVUS_CONTAINER:-asoia-milvus}" 2>/dev/null || echo 'not a container'))"
  else
    echo "DOWN  bash scripts/stack.sh up"
  fi
  for name in api ui; do
    printf '  %-9s ' "$name"
    if pid="$(alive "$name")" || pid="$(adopt "$name")"; then
      code="$(http_code "http://localhost:$(svc_port "$name")$(svc_health "$name")")"
      echo "up    pid $pid  :$(svc_port "$name")  http=$code"
    else
      echo "DOWN"
    fi
  done
  url="$(share_url)"
  [ -n "$url" ] && alive ui >/dev/null && echo "  public    $url"
  echo
  echo "DATA"
  # Only ask the store when it is answering. Otherwise this printed
  #   index     ? chunks at None dims
  # which is a stack trace's worth of confusion in place of "it is not running".
  if ! answering "http://localhost:$MILVUS_WEB/healthz"; then
    echo "  index     unreadable - the store is not running"
  elif [ -x "$PY" ]; then
    "$PY" - <<'PYEOF' 2>/dev/null || echo "  (could not read the store - is Milvus up?)"
from app.retrieval.backend import backend
from app.review.store import index_staleness
st = index_staleness()
print(f"  index     {st.get('index_rows', '?')} chunks at {backend().dim()} dims, "
      f"{st.get('database_updates', '?')} updates in the database")
# The key names are the ones index_staleness() actually returns. Guessing them
# is how a health line ends up reporting "ok" out of .get() defaults forever.
flags = [k for k in ('dangling', 'unindexed', 'text_drift', 'excluded')
         if st.get(k)]
print("  integrity " + ("ok" if st.get("ok") and not flags else
      ", ".join(f"{k}={st[k]}" for k in flags) or "see /health"))
PYEOF
  fi
  echo
  echo "MODELS"
  routing || echo "  (could not resolve - is the venv present?)"
  echo
  nim_advice
  echo
  echo "  logs: bash scripts/stack.sh logs ui | api | milvus"
}

case "${1:-status}" in
  up)      shift; up "$@" ; stores_admin_up; echo; stores_report ; bash scripts/start_observability.sh up >/dev/null 2>&1 && echo "  ==  observability: prometheus :9090, grafana :3000 (loopback)" ;;
  down)    shift; down "$@" ; stores_admin_down ; bash scripts/start_observability.sh down >/dev/null 2>&1 ;;
  restart) shift; down; echo; up "$@" ; stores_admin_up; echo; stores_report ;;
  status)  status ;;
  logs)
    case "${2:-ui}" in
      milvus) bash scripts/start_milvus.sh logs ;;
      api|ui) tail -f "$(svc_log "${2}")" ;;
      *) echo "logs: ui | api | milvus"; exit 2 ;;
    esac ;;
  stores)     shift; stores_main "$@" ;;
  *) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
