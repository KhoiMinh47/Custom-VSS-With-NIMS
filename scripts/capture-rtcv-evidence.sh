#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/rtcv-lib.sh"
logs="$PROJECT_ROOT/artifacts/logs"
manifests="$PROJECT_ROOT/artifacts/manifests"
mkdir -p "$logs" "$manifests"

"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"

containers=(
  ntc-vss-phase07-rtsp-relay
  ntc-vss-phase07-rtcv
  ntc-vss-phase07-metadata
)
: > "$logs/phase07-container-state.tsv"
for container in "${containers[@]}"; do
  docker inspect "$container" \
    --format '{{.Name}}{{"\t"}}{{.State.Status}}{{"\t"}}{{.RestartCount}}{{"\t"}}{{.State.OOMKilled}}{{"\t"}}{{.Image}}' \
    >> "$logs/phase07-container-state.tsv"
done

docker logs ntc-vss-phase07-rtcv \
  > "$logs/phase07-rtcv-runtime.jsonl" 2>&1
docker logs ntc-vss-phase07-rtsp-relay \
  > "$logs/phase07-rtsp-relay-runtime.jsonl" 2>&1
docker logs ntc-vss-phase07-metadata \
  > "$logs/phase07-metadata-runtime.jsonl" 2>&1

if grep -Eiq 'rtsp://[^/@[:space:]]+:[^/@[:space:]]+@' \
  "$logs/phase07-rtcv-runtime.jsonl" \
  "$logs/phase07-rtsp-relay-runtime.jsonl" \
  "$logs/phase07-metadata-runtime.jsonl"; then
  echo "ERROR: credential-bearing RTSP URI found in captured logs." >&2
  exit 1
fi
if grep -Eiq 'out of memory|oomkilled|cuda_error_out_of_memory' \
  "$logs/phase07-rtcv-runtime.jsonl" \
  "$logs/phase07-metadata-runtime.jsonl"; then
  echo "ERROR: an OOM signal was found in the Phase 07 runtime." >&2
  exit 1
fi
if awk -F '\t' '$3 != 0 || $4 != "false" {exit 1}' \
  "$logs/phase07-container-state.tsv"; then
  :
else
  echo "ERROR: a Phase 07 container restarted or was OOM-killed." >&2
  exit 1
fi

docker image inspect "$RTCV_IMAGE" \
  --format '{{json .RepoDigests}}' \
  > "$manifests/phase07-rtcv-image-repodigests.json"
nvidia-smi \
  --query-gpu=timestamp,name,uuid,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu,power.draw \
  --format=csv \
  > "$logs/phase07-gpu-final.csv"

echo "phase07_evidence_capture=PASS restart_count=0 oom=false secret_scan=clean"
