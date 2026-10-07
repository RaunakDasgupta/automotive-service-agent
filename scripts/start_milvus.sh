#!/usr/bin/env bash
# Milvus standalone, in one container, for the vector store.
#
#   bash scripts/start_milvus.sh up       start it (idempotent)
#   bash scripts/start_milvus.sh status   is it listening
#   bash scripts/start_milvus.sh logs     tail the container
#   bash scripts/start_milvus.sh down     stop and remove, keep the data
#
# WHY NOT EMBEDDED MILVUS LITE
#
# Milvus Lite takes an EXCLUSIVE FILE LOCK on its data directory. One process at
# a time, full stop:
#
#   DataDirLockedError: another process holds the lock on
#   '.../data/generated/milvus.db': [Errno 11] Resource temporarily unavailable
#
# With the Gradio UI running, nothing else can open the store - not the API, not
# scripts/test_review.py, not a rebuild. LanceDB allowed concurrent readers, so
# this is a regression introduced by the store, not by the code around it.
# Standalone is a server: every process talks to it over gRPC and the question
# does not arise. It is also what the architecture diagram actually says.
#
# One container, not the usual three: Milvus can run etcd in-process and use the
# local filesystem instead of MinIO, which is the right trade for a single box.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAME="${MILVUS_CONTAINER:-asoia-milvus}"
IMAGE="${MILVUS_IMAGE:-milvusdb/milvus:v2.5.4}"
PORT="${MILVUS_PORT:-19530}"
WEB="${MILVUS_WEB_PORT:-9091}"
DATA="$(pwd)/data/milvus"

case "${1:-up}" in
up)
  if ! command -v docker >/dev/null; then
    echo "docker is not installed - use embedded Milvus instead:"
    echo "  unset ASOIA_MILVUS_URI   # falls back to data/generated/milvus.db"
    exit 1
  fi
  # Whether we CREATED it decides what is worth saying at the end. Telling
  # someone to rebuild an index "because an embedded one does not move across" is
  # false and alarming when the container was already up with a healthy index in
  # it, and this script is now called by scripts/stack.sh on every start.
  CREATED=0
  if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "already running: $NAME"
    # A container created before this script had a restart policy does not gain
    # one when the script changes - the policy is fixed at create time. `docker
    # update` applies it in place, so an existing install survives the next
    # reboot without being recreated and without dropping a request.
    docker update --restart unless-stopped "$NAME" >/dev/null 2>&1 \
      && echo "  restart policy: unless-stopped"
  else
    docker rm -f "$NAME" >/dev/null 2>&1
    mkdir -p "$DATA" "$(pwd)/configs/milvus"
    # The image does NOT ship embedEtcd.yaml. Pointing ETCD_CONFIG_PATH at a file
    # that is not there makes Milvus panic with a nil pointer dereference during
    # startup - no message about the missing config, just a Go stack trace and
    # exit 134. Generating it here is what the upstream launcher does.
    cat > "$(pwd)/configs/milvus/embedEtcd.yaml" <<'YAML'
listen-client-urls: http://0.0.0.0:2379
advertise-client-urls: http://0.0.0.0:2379
quota-backend-bytes: 4294967296
auto-compaction-mode: revision
auto-compaction-retention: '1000'
YAML
    cat > "$(pwd)/configs/milvus/user.yaml" <<'YAML'
# overrides for milvus.yaml; empty is fine
YAML
    CREATED=1
    echo "starting $NAME from $IMAGE ..."
    # --restart unless-stopped: the store comes back by itself after a reboot or
    # a docker daemon restart, and stays down when you stop it deliberately.
    # Without it the box comes up with a UI that reports a broken store and an
    # index that reads as empty, which looks like data loss and is not.
    docker run -d --name "$NAME" --restart unless-stopped \
      -p "${PORT}:19530" -p "${WEB}:9091" \
      -v "${DATA}:/var/lib/milvus" \
      -v "$(pwd)/configs/milvus/embedEtcd.yaml:/milvus/configs/embedEtcd.yaml" \
      -v "$(pwd)/configs/milvus/user.yaml:/milvus/configs/user.yaml" \
      -e ETCD_USE_EMBED=true \
      -e ETCD_DATA_DIR=/var/lib/milvus/etcd \
      -e ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml \
      -e COMMON_STORAGETYPE=local \
      --health-cmd="curl -f http://localhost:9091/healthz || exit 1" \
      --health-interval=10s --health-start-period=60s --health-timeout=5s \
      --health-retries=12 \
      "$IMAGE" milvus run standalone >/dev/null || {
        echo "docker run failed"; exit 1; }
  fi
  printf 'waiting for it to answer'
  for _ in $(seq 1 60); do
    if curl -sf "http://localhost:${WEB}/healthz" >/dev/null 2>&1; then
      echo; echo "ready on localhost:${PORT}"
      if [ "$CREATED" = 1 ] && [ -z "${MILVUS_QUIET:-}" ]; then
        echo
        echo "Point the app at it:"
        echo "  export ASOIA_MILVUS_URI=http://localhost:${PORT}"
        echo "and rebuild, because an embedded index does not move across:"
        echo "  .venv/bin/python scripts/build_index.py"
      fi
      exit 0
    fi
    printf '.'; sleep 3
  done
  echo; echo "it did not become healthy in 180s. Logs:"
  docker logs --tail 25 "$NAME"
  exit 1
  ;;
status)
  docker ps --filter "name=$NAME" --format '  {{.Names}}  {{.Status}}  {{.Ports}}'
  curl -sf "http://localhost:${WEB}/healthz" >/dev/null 2>&1 \
    && echo "  healthz: ok" || echo "  healthz: not answering"
  ;;
logs) docker logs --tail "${2:-40}" -f "$NAME" ;;
down)
  docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped $NAME"
  echo "data kept in $DATA - delete it by hand to start clean"
  ;;
*) echo "usage: start_milvus.sh [up|status|logs|down]"; exit 2 ;;
esac
