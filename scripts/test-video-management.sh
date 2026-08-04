#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/video-lib.sh"
video_require_python

artifact="$PROJECT_ROOT/artifacts/logs/phase06-video-management-smoke.txt"
mkdir -p "$(dirname "$artifact")"

{
  echo "phase=PHASE-06"
  echo "schema_version=1.0.0"
  echo "tested_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  "$VIDEO_PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" \
    --registry "$VIDEO_REGISTRY" validate
  "$PROJECT_ROOT/scripts/healthcheck-video-management.sh"
  "$PROJECT_ROOT/scripts/onboard-cameras.sh"
  curl --fail --silent http://127.0.0.1:30888/vst/api/v1/sensor/streams \
    > "$PROJECT_ROOT/artifacts/logs/phase06-vios-streams.json"
  curl --fail --silent http://127.0.0.1:30888/vst/api/v1/sensor/status \
    > "$PROJECT_ROOT/artifacts/logs/phase06-vios-status.json"
  echo "vios_streams_file=artifacts/logs/phase06-vios-streams.json"
  echo "vios_status_file=artifacts/logs/phase06-vios-status.json"
  "$PROJECT_ROOT/scripts/probe-live-video.sh"
  "$VIDEO_PYTHON" "$PROJECT_ROOT/services/video-management/runtime_check.py"
  echo "result=PASS"
} | tee "$artifact"
