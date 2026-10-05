#!/usr/bin/env bash
# Prometheus + Grafana for the service operations agent.
#
#   bash scripts/start_observability.sh up      # start both
#   bash scripts/start_observability.sh down
#   bash scripts/start_observability.sh status
#
# Both run on the CPU with host networking, so they cost no VRAM and nothing to
# run beyond the box you already have. The app exposes /metrics on 9400.
set -uo pipefail

# Both bind 127.0.0.1, not every interface. Grafana runs with
# anonymous admin and no login form - deliberately, because it is meant
# to be reached over an ssh port-forward - and an anonymous admin
# dashboard listening on 0.0.0.0 is exactly the exposure the store UIs
# in scripts/stores.sh are bound away from. Reach these the same way:
#   ssh -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 capstone-poc
PROM_PORT="${PROM_PORT:-9090}"
GRAF_PORT="${GRAF_PORT:-3000}"
APP_METRICS="${ASOIA_METRICS_PORT:-9400}"
DCGM_PORT="${DCGM_PORT:-9401}"
DCGM_IMAGE="${DCGM_IMAGE:-nvcr.io/nvidia/k8s/dcgm-exporter:4.1.1-4.0.4-ubuntu22.04}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

up() {
  [ -f "$ROOT/configs/prometheus.yml" ] || { echo "configs/prometheus.yml missing"; exit 1; }
  echo "==> prometheus on :$PROM_PORT (scraping localhost:$APP_METRICS)"
  docker rm -f asoia-prometheus >/dev/null 2>&1
  docker run -d --name asoia-prometheus --network host --restart unless-stopped \
    -v "$ROOT/configs/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
      -v asoia-prom-data:/prometheus \
    prom/prometheus:v2.54.1 \
      --config.file=/etc/prometheus/prometheus.yml \
      --web.listen-address="127.0.0.1:$PROM_PORT" >/dev/null || exit 1

  # NVIDIA DCGM exporter. Needs the GPU and SYS_ADMIN for the profiling
  # counters. Loopback-bound like everything else here. A box with no GPU
  # simply does not get this container, and the dcgm scrape target stays down.
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo "==> dcgm-exporter on :$DCGM_PORT (GPU telemetry)"
    docker rm -f asoia-dcgm >/dev/null 2>&1
    docker run -d --name asoia-dcgm --gpus all --cap-add SYS_ADMIN \
      --restart unless-stopped -p "127.0.0.1:$DCGM_PORT:9400" \
      "$DCGM_IMAGE" >/dev/null \
      || echo "    dcgm-exporter did not start - GPU panels will be empty"
  else
    echo "==> no nvidia-smi, skipping dcgm-exporter"
  fi

  echo "==> grafana on :$GRAF_PORT (anonymous viewer, no login)"
  docker rm -f asoia-grafana >/dev/null 2>&1
  docker run -d --name asoia-grafana --network host --restart unless-stopped \
    -e GF_SERVER_HTTP_PORT="$GRAF_PORT" -e GF_SERVER_HTTP_ADDR=127.0.0.1 \
    -e GF_AUTH_ANONYMOUS_ENABLED=true \
    -e GF_AUTH_ANONYMOUS_ORG_ROLE=Admin \
    -e GF_AUTH_DISABLE_LOGIN_FORM=true \
    -v "$ROOT/configs/grafana/datasources:/etc/grafana/provisioning/datasources:ro" \
    -v "$ROOT/configs/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro" \
    grafana/grafana:11.2.0 >/dev/null || exit 1

  cat <<NEXT

Started. From your laptop:
  brev port-forward capstone-poc --port $GRAF_PORT:$GRAF_PORT
  open http://localhost:$GRAF_PORT   -> dashboard "Service Operations Agent"

Anonymous access is on and the login form is off, because this is reachable only
over the port-forward. Do not publish $GRAF_PORT.
NEXT
}

down() {
  docker rm -f asoia-prometheus asoia-grafana asoia-dcgm >/dev/null 2>&1
  echo "stopped."
}

status() {
  docker ps --filter name=asoia- --format '{{.Names}}\t{{.Status}}'
  printf 'app /metrics -> '
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 4 "http://localhost:$APP_METRICS/metrics" \
    || echo "unreachable"
  printf 'prometheus   -> '
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 4 "http://localhost:$PROM_PORT/-/ready" \
    || echo "unreachable"
  printf 'dcgm /metrics -> '
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 4 "http://localhost:$DCGM_PORT/metrics" \
    || echo "unreachable"
}

case "${1:-up}" in
  up) up ;;
  down) down ;;
  status) status ;;
  *) echo "usage: $0 [up|down|status]"; exit 2 ;;
esac
