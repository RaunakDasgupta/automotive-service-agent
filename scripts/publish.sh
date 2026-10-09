#!/usr/bin/env bash
# Publish the stack's web UIs on public URLs, for reaching them from any device.
#
#   bash scripts/publish.sh up       # start a tunnel per UI, print the URLs
#   bash scripts/publish.sh urls     # print the current URLs
#   bash scripts/publish.sh down     # stop the tunnels
#
# THERE IS NO AUTHENTICATION IN FRONT OF ANY OF THESE, by decision. What that
# means, so it is not a surprise later:
#
#   gradio      the Technician Update tab WRITES to the event log, and every
#               model call spends this box's NVIDIA key
#   grafana     runs anonymous with the login form disabled and the anonymous
#               role set to Admin - a visitor can edit dashboards and add
#               datasources
#   attu        Milvus admin, read-write - a visitor can drop the collection
#   prometheus  read-only, but it describes the inside of the box
#
# A random subdomain is not a credential. It is not guessable, and it is also
# not secret once it has been pasted anywhere.
#
# WHY trycloudflare AND WHAT THAT COSTS
#
# cloudflared quick tunnels need no account and no DNS, which is why they are
# used here. They are also EPHEMERAL: every URL changes when its container
# restarts, so these links cannot be written down. `urls` re-reads them from the
# container logs, which is the only place they exist. The containers carry
# --restart unless-stopped, so they come back with the box - with new URLs.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }

IMAGE="${CLOUDFLARED_IMAGE:-cloudflare/cloudflared:latest}"
# name:port - the UI, the two observability consoles, and the two store admins.
SERVICES="gradio:${PORT:-7860} grafana:${GRAF_PORT:-3000} prometheus:${PROM_PORT:-9090} attu:${ASOIA_ATTU_PORT:-8101} sqlite-web:${ASOIA_SQLITEWEB_PORT:-8102}"

url_of() {   # read the quick-tunnel URL back out of the container's log
  docker logs "asoia-cf-$1" 2>&1 \
    | grep -ohE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1
}

up() {
  docker image inspect "$IMAGE" >/dev/null 2>&1 || {
    echo "==> pulling $IMAGE"; docker pull -q "$IMAGE" >/dev/null || {
      echo "    pull failed"; exit 1; }; }
  for s in $SERVICES; do
    local name="${s%%:*}" port="${s##*:}"
    if ! (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      echo "  --  $name: nothing listening on :$port, skipped"
      continue
    fi
    docker rm -f "asoia-cf-$name" >/dev/null 2>&1
    # --network host so the tunnel can reach a service bound to 127.0.0.1.
    docker run -d --name "asoia-cf-$name" --network host \
      --restart unless-stopped "$IMAGE" \
      tunnel --no-autoupdate --url "http://127.0.0.1:$port" >/dev/null \
      && echo "  ==  $name -> :$port"
  done
  printf '     waiting for the edge to register'
  for _ in $(seq 1 20); do
    printf '.'
    local missing=0
    for s in $SERVICES; do
      docker ps --format '{{.Names}}' | grep -q "asoia-cf-${s%%:*}$" || continue
      [ -n "$(url_of "${s%%:*}")" ] || missing=1
    done
    [ "$missing" = 0 ] && break
    sleep 3
  done
  echo; urls
}

urls() {
  echo "public URLs - no authentication in front of any of them"
  for s in $SERVICES; do
    local name="${s%%:*}" u
    docker ps --format '{{.Names}}' | grep -q "asoia-cf-$name$" || continue
    u="$(url_of "$name")"
    printf '  %-11s %s\n' "$name" "${u:-(not registered yet - retry in a moment)}"
  done
}

down() {
  for s in $SERVICES; do docker rm -f "asoia-cf-${s%%:*}" >/dev/null 2>&1; done
  echo "tunnels stopped. The UIs are still served on 127.0.0.1."
}

case "${1:-up}" in
  up)   up ;;
  urls) urls ;;
  down) down ;;
  *) sed -n '2,8p' "$0"; exit 2 ;;
esac
