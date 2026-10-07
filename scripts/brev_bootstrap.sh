#!/usr/bin/env bash
# Paste-able first command on a fresh Brev L40S: start the three NIM pulls.
#
#   export NVIDIA_API_KEY=nvapi-...    # or have it in .env already
#   bash scripts/brev_bootstrap.sh
#
# This is a thin wrapper over `scripts/start_nims.sh pull` and deliberately
# holds no image names of its own. It used to list all three itself, and the
# list had drifted: it pulled
#
#     nvcr.io/nim/nvidia/nv-rerankqa-mistral-4b-v3:latest
#
# which does not exist. That repository publishes only versioned tags - checked
# against the registry, its tag list is 1.0.0, 1.0.1, 1.0.2 and nothing else -
# so one of the three pulls died with `manifest unknown` while the other two
# succeeded, and the script printed ALL PULLS DONE regardless because the pulls
# ran in the background and their exit codes were never read.
#
# start_nims.sh has the correct pin and reports each pull's exit code. Two
# scripts naming the same images is how the wrong one gets pasted.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec bash scripts/start_nims.sh pull
