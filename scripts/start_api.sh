#!/usr/bin/env bash
# The HTTP API. Same functions the UI calls, same guardrails.
#
#   bash scripts/start_api.sh            # foreground on :8080
#   bash scripts/start_api.sh --detach   # background, logs to /tmp/asoia-api.log
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
: "${API_PORT:=8080}"
: "${ASOIA_NOW:=}"

PY=.venv/bin/python
[ -x "$PY" ] || { echo "no .venv - see README"; exit 1; }
"$PY" -c "import fastapi, uvicorn" 2>/dev/null || {
  echo "fastapi/uvicorn missing. Install with:"
  echo "  $PY -m pip install 'fastapi>=0.115' 'uvicorn>=0.30'"; exit 1; }

if [ "${1:-}" = "--detach" ]; then
  # setsid is Linux-only; see the note in scripts/stack.sh.
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$PY" -m app.api.server >/tmp/asoia-api.log 2>&1 </dev/null &
  else
    nohup "$PY" -m app.api.server >/tmp/asoia-api.log 2>&1 </dev/null &
  fi
  sleep 3
  printf 'health -> '
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 5 "http://localhost:$API_PORT/health"
  echo "logs: tail -f /tmp/asoia-api.log"
  echo "docs: http://localhost:$API_PORT/docs"
else
  echo "==> http://localhost:$API_PORT/docs   (Ctrl-C to stop)"
  exec "$PY" -m app.api.server
fi
