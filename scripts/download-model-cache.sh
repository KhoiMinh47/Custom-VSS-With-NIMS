#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/model-gate-lib.sh"

require_phase02_pass
require_ngc_key
require_project_disk_headroom

: "${LLM_PROFILE_ID:?Set from reviewed nemotron-model-profiles.txt}"
: "${VLM_PROFILE_ID:?Set from reviewed cosmos3-model-profiles.txt}"

LLM_IMAGE="${LLM_IMAGE:-nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1}"
VLM_IMAGE="${VLM_IMAGE:-nvcr.io/nim/nvidia/cosmos3-reasoner:1.7}"
manifest_dir="$PROJECT_ROOT/artifacts/manifests"

grep -Fq -- "$LLM_PROFILE_ID" "$manifest_dir/nemotron-model-profiles.txt"
grep -Fq -- "$VLM_PROFILE_ID" "$manifest_dir/cosmos3-model-profiles.txt"

docker run --rm \
  --gpus all \
  -e NGC_API_KEY \
  -e NIM_CACHE_PATH=/opt/nim/.cache \
  -v "$NIM_LLM_CACHE:/opt/nim/.cache" \
  -u "$(id -u):$(id -g)" \
  "$LLM_IMAGE" download-to-cache -p "$LLM_PROFILE_ID"

docker run --rm \
  --gpus all \
  --ipc host \
  --shm-size=32GB \
  --entrypoint /usr/local/bin/download-to-cache \
  -e NGC_API_KEY \
  -e NIM_CACHE_PATH=/opt/nim/.cache \
  -v "$NIM_VLM_CACHE:/opt/nim/.cache" \
  -u "$(id -u):$(id -g)" \
  "$VLM_IMAGE" -p "$VLM_PROFILE_ID"

find -L "$PROJECT_ROOT/.cache/nim" -type f -printf '%P\t%s\n' \
  | sort > "$manifest_dir/model-cache-inventory.tsv"
du -shL "$PROJECT_ROOT/.cache/nim/"* \
  > "$manifest_dir/nim-cache-sizes.txt"

echo "Selected NIM profiles downloaded to project-local cache."
