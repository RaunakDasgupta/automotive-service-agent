#!/usr/bin/env bash
# Operator access to the stores, kept deliberately outside the agent's own UI.
#
# stack.sh sources this and calls stores_report at the end of `up` and
# `restart`; it is also reachable as `scripts/stack.sh stores [verb]`. It works
# when sourced and when run directly, so it can be debugged on its own.
#
# Two rules shape what follows.
#
# Ports 8101/8102, not 8001/8002: on this box nim-embed holds 8001 and
# nim-rerank holds 8002, and 7860, 8000, 8080, 9091 and 19530 are taken by the
# UI, the LLM NIM, the API, Milvus metrics and Milvus itself.
#
# Loopback only. Both UIs can write - sqlite-web runs arbitrary SQL against the
# system of record and Attu can drop a collection - so neither may be laxer than
# the services they administer. They bind 127.0.0.1 and reach your laptop over
# an ssh tunnel the report prints for you. Nothing here opens a firewall port,
# and nothing here goes through the public gradio.live link.
#
# `up` never downloads. A startup path that silently pulls a 100 MB image or
# writes to the venv is a startup path that fails on a metered connection in
# front of an audience. So: the report always prints, a UI starts only if its
# dependency is already on the box, and provisioning is an explicit verb you
# run once - `scripts/stack.sh stores provision`.

ASOIA_ATTU_PORT="${ASOIA_ATTU_PORT:-8101}"
ASOIA_SQLITEWEB_PORT="${ASOIA_SQLITEWEB_PORT:-8102}"
# Attu tracks Milvus by minor version; this box runs milvusdb/milvus:v2.5.4,
# so v2.5. Bump both together or the UI talks to a server it does not
# understand.
ASOIA_ATTU_IMAGE="${ASOIA_ATTU_IMAGE:-zilliz/attu:v2.5}"
ASOIA_ADMIN="${ASOIA_ADMIN:-on}"
_ASOIA_DB="${ASOIA_DB:-data/generated/service.sqlite}"

# stack.sh owns svc_log; define a compatible one only if we were run directly.
if ! declare -f svc_log >/dev/null 2>&1; then
  svc_log() { echo "/tmp/asoia-$1.log"; }
fi

_st_py() {
  # The report must run under the interpreter that has pymilvus, and must see
  # the same .env the stack saw - scripts/_env.py handles the second half.
  if [ -x .venv/bin/python ]; then .venv/bin/python "$@"
  elif command -v uv >/dev/null 2>&1; then uv run python "$@"
  else python3 "$@"; fi
}

_st_listening() {  # _st_listening PORT
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -q ":$1 "
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
  fi
}

# ---------------------------------------------------------------- milvus / attu

_st_milvus_container() {
  # The container serving 19530. Named first, since that is what this stack
  # calls it; otherwise whatever publishes the port.
  if docker ps --format "{{.Names}}" 2>/dev/null | grep -qx asoia-milvus; then
    echo asoia-milvus; return
  fi
  docker ps --format "{{.Names}} {{.Ports}}" 2>/dev/null \
    | awk "/19530->19530/ {print \$1; exit}"
}

_st_attu_target() {
  # Attu runs in a container, so a loopback URI means the container itself and
  # has to be translated.
  #
  # `host.docker.internal:host-gateway` is the usual answer and it does NOT
  # work on this box: the name resolves to the bridge gateway (172.17.0.1) but
  # TCP to the published 19530 times out - dropped, not refused. So go straight
  # to Milvus's own address on the bridge it shares with Attu. Measured, not
  # assumed; the gateway route is kept only for a Milvus that is not a
  # container.
  #
  # Container IPs are not stable, so this is re-resolved on every start and
  # stores_attu_up recreates Attu when the address has moved.
  local uri="${ASOIA_MILVUS_URI:-}" hp host port c ip
  [ -n "$uri" ] || { echo ""; return; }
  hp="${uri#*://}"; hp="${hp%%/*}"
  host="${hp%%:*}"; port="${hp##*:}"
  [ "$port" = "$host" ] && port=19530
  case "$host" in
    localhost|127.0.0.1|::1|0.0.0.0) ;;
    *) echo "$hp"; return ;;
  esac
  c="$(_st_milvus_container)"
  if [ -n "$c" ]; then
    ip="$(docker inspect "$c" \
          --format "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}" \
          2>/dev/null | awk "{print \$1}")"
    [ -n "$ip" ] && { echo "$ip:$port"; return; }
  fi
  echo "host.docker.internal:$port"
}

stores_attu_up() {
  command -v docker >/dev/null 2>&1 || {
    echo "  [attu] docker not available - skipping the vector-store UI"; return 0; }
  local target; target="$(_st_attu_target)"
  [ -n "$target" ] || {
    echo "  [attu] ASOIA_MILVUS_URI is unset - nothing to point a UI at"; return 0; }
  if docker ps --format "{{.Names}}" 2>/dev/null | grep -qx asoia-attu; then
    local cur
    cur="$(docker inspect asoia-attu \
           --format "{{range .Config.Env}}{{println .}}{{end}}" 2>/dev/null \
           | sed -n "s/^MILVUS_URL=//p")"
    if [ "$cur" = "$target" ]; then
      echo "  [attu] already running on 127.0.0.1:${ASOIA_ATTU_PORT}"; return 0
    fi
    echo "  [attu] Milvus moved: ${cur:-unknown} -> ${target}; recreating"
  fi
  # No pull on the startup path: report the one command that fixes it instead.
  docker image inspect "$ASOIA_ATTU_IMAGE" >/dev/null 2>&1 || {
    echo "  [attu] image absent. Provision once with:  scripts/stack.sh stores provision"
    return 0; }
  docker rm -f asoia-attu >/dev/null 2>&1
  if docker run -d --name asoia-attu --restart unless-stopped \
       -p "127.0.0.1:${ASOIA_ATTU_PORT}:3000" \
       --add-host host.docker.internal:host-gateway \
       -e "MILVUS_URL=${target}" "$ASOIA_ATTU_IMAGE" >>"$(svc_log attu)" 2>&1; then
    echo "  [attu] 127.0.0.1:${ASOIA_ATTU_PORT} -> ${target}"
  else
    echo "  [attu] failed to start; see $(svc_log attu)"
  fi
}

stores_attu_down() {
  command -v docker >/dev/null 2>&1 || return 0
  docker rm -f asoia-attu >/dev/null 2>&1 && echo "  [attu] stopped"
  return 0
}

# ------------------------------------------------------------ sqlite/sqlite-web

_st_sqliteweb_bin() {
  if [ -x .venv/bin/sqlite_web ]; then echo .venv/bin/sqlite_web
  elif command -v sqlite_web >/dev/null 2>&1; then command -v sqlite_web
  else echo ""; fi
}

stores_sqliteweb_up() {
  local pidf=/tmp/asoia-sqliteweb.pid bin log
  log="$(svc_log sqliteweb)"
  if [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null; then
    echo "  [sqlite-web] already running on 127.0.0.1:${ASOIA_SQLITEWEB_PORT}"; return 0; fi
  [ -f "$_ASOIA_DB" ] || {
    echo "  [sqlite-web] ${_ASOIA_DB} is not present - nothing to serve"; return 0; }
  bin="$(_st_sqliteweb_bin)"
  [ -n "$bin" ] || {
    echo "  [sqlite-web] not installed. Provision once with:  scripts/stack.sh stores provision"
    return 0; }
  # Flags, all checked against sqlite-web 0.8.2:
  #   -x  never try to open a browser - this box is headless
  #   -q  errors only, so the log stays readable
  #   -f  foreign_keys ON, matching the PRAGMA app/state/db.py sets. Without it
  #       the admin UI enforces less than the app does, and an operator can
  #       delete an RO and leave its events orphaned - a state the agent itself
  #       cannot produce and does not expect to read.
  #   -T  do not ellipsize at 50 chars; events.payload is JSON and unreadable
  #       truncated.
  # Writes stay enabled on purpose: the mutable view is the point. SQLite's
  # default 5s busy timeout covers the app's small writes, but a long
  # transaction left open in the query tab can block the agent. That is the
  # cost of a read-write UI on a live store, and it is why this is loopback.
  nohup "$bin" -H 127.0.0.1 -p "$ASOIA_SQLITEWEB_PORT" -x -q -f -T "$_ASOIA_DB" \
      >>"$log" 2>&1 &
  echo $! >"$pidf"
  sleep 1
  if kill -0 "$(cat "$pidf")" 2>/dev/null; then
    echo "  [sqlite-web] 127.0.0.1:${ASOIA_SQLITEWEB_PORT} -> ${_ASOIA_DB} (read-write)"
  else
    rm -f "$pidf"
    echo "  [sqlite-web] exited immediately; tail of $log:"
    tail -n 6 "$log" 2>/dev/null | sed 's/^/      /'
  fi
}

stores_sqliteweb_down() {
  local pidf=/tmp/asoia-sqliteweb.pid
  [ -f "$pidf" ] || return 0
  kill "$(cat "$pidf")" 2>/dev/null && echo "  [sqlite-web] stopped"
  rm -f "$pidf"
  return 0
}

# ------------------------------------------------------------------- provision

stores_provision() {
  echo "provisioning the store UIs (this one does download)"
  if command -v docker >/dev/null 2>&1; then
    echo "  pulling ${ASOIA_ATTU_IMAGE}"
    docker pull "$ASOIA_ATTU_IMAGE" || echo "  pull failed - vector UI will stay off"
  else
    echo "  docker not available - skipping attu"
  fi
  if command -v uv >/dev/null 2>&1; then
    echo "  installing sqlite-web into .venv"
    uv pip install "sqlite-web>=0.8" || echo "  install failed - sqlite UI will stay off"
  elif [ -x .venv/bin/pip ]; then
    .venv/bin/pip install "sqlite-web>=0.8" || echo "  install failed - sqlite UI will stay off"
  else
    echo "  no uv and no .venv/bin/pip - install it yourself:"
    echo "    pip install -e \".[admin]\""
  fi
  echo "done. Now run: scripts/stack.sh stores up"
}

# ---------------------------------------------------------------------- public

stores_admin_up() {
  [ "$ASOIA_ADMIN" = "off" ] && return 0
  stores_attu_up
  stores_sqliteweb_up
  return 0
}

stores_admin_down() {
  stores_attu_down
  stores_sqliteweb_down
  return 0
}

stores_report() {
  _st_py scripts/store_report.py "$@"
}

stores_main() {
  case "${1:-report}" in
    report|"")  stores_report ;;
    json)       stores_report --json ;;
    up)         stores_admin_up; echo; stores_report ;;
    down)       stores_admin_down ;;
    provision)  stores_provision ;;
    *) echo "usage: stores.sh {report|json|up|down|provision}" >&2; return 2 ;;
  esac
}

# Sourced by stack.sh, or run on its own.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
  [ -f .env ] && { set -a; . ./.env; set +a; }
  stores_main "$@"
fi
