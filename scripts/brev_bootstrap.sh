#!/usr/bin/env bash
# Paste-able bootstrap for a fresh Brev L40S. Starts the three NIM pulls.
set -uo pipefail
: "${NVIDIA_API_KEY:?export NVIDIA_API_KEY=nvapi-... first}"
echo "$NVIDIA_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin || exit 1
mkdir -p ~/.cache/nim
docker pull nvcr.io/nim/nvidia/llama-3.1-nemotron-nano-8b-v1:latest > /tmp/pull_llm.log 2>&1 &
docker pull nvcr.io/nim/nvidia/nv-embedqa-e5-v5:latest            > /tmp/pull_emb.log 2>&1 &
docker pull nvcr.io/nim/nvidia/nv-rerankqa-mistral-4b-v3:latest   > /tmp/pull_rrk.log 2>&1 &
echo "3 pulls running in background. Progress:  tail -f /tmp/pull_*.log"
wait; echo "ALL PULLS DONE"; docker images | grep -i nim
