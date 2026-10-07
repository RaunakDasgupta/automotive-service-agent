#!/usr/bin/env bash
# Start the three NIM containers for the Automotive Service Operations Intelligence Agent.
# Target: single Brev L40S 48GB. Run this FIRST - pulls + TRT engine builds take 30-90 min.
#
#   bash scripts/start_nims.sh pull     # login + pull all three in parallel (do this now)
#   bash scripts/start_nims.sh run      # start all three
#   bash scripts/start_nims.sh health   # check endpoints + VRAM
#   bash scripts/start_nims.sh logs llm # tail one container
#   bash scripts/start_nims.sh stop
set -uo pipefail

# Source .env first. Without this, `logs`, `stop` and `health` all died on the
# guard below in any shell that had not exported the key by hand - subcommands
# that never touch the network.
[ -f .env ] && { set -a; . ./.env; set +a; }

: "${NVIDIA_API_KEY:?Set NVIDIA_API_KEY (see .env). Never commit it.}"
NGC_API_KEY="${NGC_API_KEY:-$NVIDIA_API_KEY}"

LLM_IMG="nvcr.io/nim/nvidia/llama-3.1-nemotron-nano-8b-v1:latest"
EMB_IMG="nvcr.io/nim/nvidia/nv-embedqa-e5-v5:latest"
# NOT :latest - that repository publishes only versioned tags and `docker pull`
# fails with `manifest unknown`. NVIDIA's deployment docs pin 1.0.0; 1.0.2 is
# current. The llm and embedding repositories do publish :latest, which is why
# only one of the three pulls failed.
RRK_IMG="nvcr.io/nim/nvidia/nv-rerankqa-mistral-4b-v3:1.0.2"

LLM_PORT=8000; EMB_PORT=8001; RRK_PORT=8002
CACHE="${NIM_CACHE:-$HOME/.cache/nim}"

# ---------------------------------------------------------------------------
# CRITICAL: the LLM NIM uses a vLLM backend which PRE-ALLOCATES ~90% of VRAM by
# default. On a shared GPU that starves the embed + rerank NIMs and they will
# fail to start. We cap it so all three co-reside on 48GB:
#     LLM ~12GB (0.25) + embed ~5GB + rerank ~24GB = ~41GB
# If the LLM container OOMs or refuses to start, raise to 0.30; if the RERANKER
# fails, lower the LLM to 0.20 or switch to the 1B reranker (see FALLBACK below).
# ---------------------------------------------------------------------------
LLM_GPU_FRAC="${LLM_GPU_FRAC:-0.25}"
LLM_MAX_LEN="${LLM_MAX_LEN:-8192}"

# FALLBACK reranker (~4GB instead of ~24GB) if VRAM is tight:
#   RRK_IMG="nvcr.io/nim/nvidia/llama-3.2-nv-rerankqa-1b-v2:latest"

mkdir -p "$CACHE"
# A NIM container runs internally as a different uid to the host user, so a cache
# directory at the default 755 leaves it on "other" permissions and it dies with
# `PermissionError: /opt/nim/.cache/local_cache`. Containers are also run as the
# invoking user below, as NVIDIA's quickstart does.
chmod -R a+rwX "$CACHE" 2>/dev/null || true

login() {
  echo "==> docker login nvcr.io"
  echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin
}

pull() {
  login || exit 1
  echo "==> Pulling all three NIMs in parallel. This is the long pole."
  docker pull "$LLM_IMG" > /tmp/pull_llm.log 2>&1 &  P1=$!
  docker pull "$EMB_IMG" > /tmp/pull_emb.log 2>&1 &  P2=$!
  docker pull "$RRK_IMG" > /tmp/pull_rrk.log 2>&1 &  P3=$!
  echo "    llm=$P1 embed=$P2 rerank=$P3   (tail /tmp/pull_*.log)"
  # Each exit code is read, and a failure makes THIS script fail. Printing
  # "Pulls complete" after a `manifest unknown` is how a missing image became a
  # confusing container crash twenty minutes later instead of an error here.
  local bad=0 rc=0
  wait $P1; rc=$?; echo "    llm    exit=$rc"; [ $rc -eq 0 ] || bad=$((bad+1))
  wait $P2; rc=$?; echo "    embed  exit=$rc"; [ $rc -eq 0 ] || bad=$((bad+1))
  wait $P3; rc=$?; echo "    rerank exit=$rc"; [ $rc -eq 0 ] || bad=$((bad+1))
  if [ $bad -gt 0 ]; then
    echo
    echo "==> $bad of 3 pulls FAILED. The reason is in the logs, last lines:"
    for f in /tmp/pull_llm.log /tmp/pull_emb.log /tmp/pull_rrk.log; do
      echo "    --- $f"; tail -3 "$f" 2>/dev/null | sed 's/^/        /'
    done
    echo "    Do not run \`run\` until all three are pulled."
    return 1
  fi
  echo "==> Pulls complete. Next: bash scripts/start_nims.sh run"
}

run_one() { # name image port extra_env...
  local name=$1 image=$2 port=$3; shift 3
  docker rm -f "$name" >/dev/null 2>&1
  echo "==> starting $name on :$port"
  # Two things here are load-bearing:
  #  -u  the container must write to the mounted cache as the host user.
  #  -p "$port:8000"  leave the container's INTERNAL ports alone. A NIM uses the
  #      standard Triton triple - 8000 http, 8001 grpc, 8002 metrics - so forcing
  #      its http server onto 8001 made Triton's own grpc service fail to bind:
  #      `Socket '0.0.0.0:8001' already in use`. Separate network namespaces mean
  #      all three containers can use 8000 internally.
  docker run -d --name "$name" --gpus all --shm-size=16GB --restart unless-stopped \
    -u "$(id -u):$(id -g)" \
    -e NGC_API_KEY="$NGC_API_KEY" \
    "$@" -v "$CACHE:/opt/nim/.cache" -p "$port:8000" "$image" >/dev/null
}

run() {
  # Reranker first: it is the largest and most likely to fail on a crowded GPU.
  run_one nim-rerank "$RRK_IMG" $RRK_PORT
  run_one nim-embed  "$EMB_IMG" $EMB_PORT
  # Both memory caps, because which one applies depends on the profile the
  # container selects: NIM_GPU_MEMORY_UTILIZATION is vLLM, NIM_KVCACHE_PERCENT is
  # TRT-LLM. On an L40S this image picks a TRT-LLM FP8 profile, so the vLLM
  # setting on its own was silently doing nothing at all. Each backend ignores
  # the variable that is not its own.
  run_one nim-llm    "$LLM_IMG" $LLM_PORT \
      -e NIM_GPU_MEMORY_UTILIZATION="$LLM_GPU_FRAC" \
      -e NIM_KVCACHE_PERCENT="$LLM_GPU_FRAC" \
      -e NIM_MAX_MODEL_LEN="$LLM_MAX_LEN"
  echo "==> All three launched. First start builds TRT engines - can take 10-20 min."
  echo "    Watch: bash scripts/start_nims.sh logs llm"
}

health() {
  echo "=== NIM health ==="
  for pair in "llm:$LLM_PORT" "embed:$EMB_PORT" "rerank:$RRK_PORT"; do
    n="${pair%%:*}"; p="${pair##*:}"
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:$p/v1/health/ready" 2>/dev/null)
    [ "$code" = "200" ] && echo "  OK      $n  :$p" || echo "  NOT UP  $n  :$p  (http=$code)"
  done
  echo; echo "=== VRAM ==="
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv 2>/dev/null || echo "  nvidia-smi unavailable"
  echo; docker ps --filter 'name=nim-' --format '  {{.Names}}\t{{.Status}}' 2>/dev/null
}

case "${1:-}" in
  pull)   pull || exit 1 ;;
  run)    run ;;
  health) health ;;
  logs)   docker logs -f "nim-${2:-llm}" ;;
  stop)   docker rm -f nim-llm nim-embed nim-rerank 2>/dev/null; echo "stopped" ;;
  *) sed -n '2,10p' "$0" ;;
esac
