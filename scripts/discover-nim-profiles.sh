#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/model-gate-lib.sh"

require_phase02_pass
require_ngc_key
require_project_disk_headroom

LLM_IMAGE="${LLM_IMAGE:-nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1}"
VLM_IMAGE="${VLM_IMAGE:-nvcr.io/nim/nvidia/cosmos3-reasoner:1.7}"
manifest_dir="$PROJECT_ROOT/artifacts/manifests"
mkdir -p "$manifest_dir" "$NIM_LLM_CACHE" "$NIM_VLM_CACHE"

printf '%s' "$NGC_API_KEY" \
  | docker login nvcr.io --username '$oauthtoken' --password-stdin >/dev/null

docker pull "$LLM_IMAGE"
docker pull "$VLM_IMAGE"

docker image inspect "$LLM_IMAGE" --format '{{index .RepoDigests 0}}' \
  > "$manifest_dir/nemotron-image-digest.txt"
docker image inspect "$VLM_IMAGE" --format '{{index .RepoDigests 0}}' \
  > "$manifest_dir/cosmos3-image-digest.txt"

docker run --rm \
  --gpus all \
  -e NGC_API_KEY \
  -e NIM_CACHE_PATH=/opt/nim/.cache \
  -v "$NIM_LLM_CACHE:/opt/nim/.cache" \
  -u "$(id -u):$(id -g)" \
  "$LLM_IMAGE" list-model-profiles \
  > "$manifest_dir/nemotron-model-profiles.txt"

docker run --rm \
  --gpus all \
  --ipc host \
  --shm-size=32GB \
  --entrypoint /usr/local/bin/list-model-profiles \
  -e NGC_API_KEY \
  -e NIM_CACHE_PATH=/opt/nim/.cache \
  -v "$NIM_VLM_CACHE:/opt/nim/.cache" \
  -u "$(id -u):$(id -g)" \
  "$VLM_IMAGE" \
  > "$manifest_dir/cosmos3-model-profiles.txt"

echo "Profile discovery complete. Review compatible profile IDs before download."
