#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/model-gate-lib.sh"

require_phase02_pass
require_ngc_key

: "${LLM_PROFILE_ID:?Set the verified LLM profile ID}"
: "${VLM_PROFILE_ID:?Set the verified VLM profile ID}"
: "${LLM_IMAGE_PINNED:?Set the pinned LLM image digest}"
: "${VLM_IMAGE_PINNED:?Set the pinned VLM image digest}"

benchmark_dir="$PROJECT_ROOT/artifacts/benchmarks/nim-smoke-test"
mkdir -p "$benchmark_dir"

cleanup() {
  docker logs vss-poc-nemotron-smoke \
    > "$benchmark_dir/nemotron-container.log" 2>&1 || true
  docker logs vss-poc-cosmos3-smoke \
    > "$benchmark_dir/cosmos3-container.log" 2>&1 || true
  docker stop vss-poc-nemotron-smoke vss-poc-cosmos3-smoke >/dev/null 2>&1 || true
  docker rm vss-poc-nemotron-smoke vss-poc-cosmos3-smoke >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_ready() {
  local url="$1"
  local attempts="$2"
  local attempt

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error "$url"; then
      return 0
    fi
    sleep 5
  done

  echo "Timed out waiting for $url after $((attempts * 5)) seconds." >&2
  return 1
}

docker run -d --name vss-poc-nemotron-smoke \
  --gpus all \
  --shm-size=16GB \
  -e NGC_API_KEY \
  -e NIM_MODEL_PROFILE="$LLM_PROFILE_ID" \
  -e NIM_MAX_MODEL_LEN="${LLM_MAX_MODEL_LEN:-32768}" \
  -e NIM_MAX_NUM_SEQS="${LLM_MAX_NUM_SEQS:-4}" \
  -e NIM_CACHE_PATH=/opt/nim/.cache \
  -v "$NIM_LLM_CACHE:/opt/nim/.cache" \
  -u "$(id -u):$(id -g)" \
  -p 127.0.0.1:30081:8000 \
  "$LLM_IMAGE_PINNED" >/dev/null
wait_ready http://127.0.0.1:30081/v1/health/ready 60
curl --fail --silent http://127.0.0.1:30081/v1/models \
  > "$benchmark_dir/nemotron-models.json"
docker logs vss-poc-nemotron-smoke \
  > "$benchmark_dir/nemotron-container.log" 2>&1
docker stop vss-poc-nemotron-smoke >/dev/null
docker rm vss-poc-nemotron-smoke >/dev/null

docker run -d --name vss-poc-cosmos3-smoke \
  --gpus all \
  --ipc host \
  --shm-size=32GB \
  -e NGC_API_KEY \
  -e NIM_MODEL_PROFILE="$VLM_PROFILE_ID" \
  -e NIM_MAX_MODEL_LEN="${VLM_MAX_MODEL_LEN:-32768}" \
  -e NIM_CACHE_PATH=/opt/nim/.cache \
  -v "$NIM_VLM_CACHE:/opt/nim/.cache" \
  -u "$(id -u):$(id -g)" \
  -p 127.0.0.1:30082:8000 \
  "$VLM_IMAGE_PINNED" >/dev/null
wait_ready http://127.0.0.1:30082/v1/health/ready 90
curl --fail --silent http://127.0.0.1:30082/v1/models \
  > "$benchmark_dir/cosmos3-models.json"
docker logs vss-poc-cosmos3-smoke \
  > "$benchmark_dir/cosmos3-container.log" 2>&1
docker stop vss-poc-cosmos3-smoke >/dev/null
docker rm vss-poc-cosmos3-smoke >/dev/null

echo "Individual NIM smoke tests PASS. No NIM container remains running."
