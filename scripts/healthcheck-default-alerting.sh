#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$PROJECT_ROOT/scripts/healthcheck-rtcv.sh"
"$PROJECT_ROOT/scripts/healthcheck-behavior-analytics.sh"
"$PROJECT_ROOT/scripts/healthcheck-phase10.sh"

running_gpu="$(
  docker ps --format '{{.Names}}' \
    | grep -E \
      '^(ntc-vss-phase11-rt-vlm|ntc-vss-retail-poc-gpu-poc-cosmos3-1)$' \
    || true
)"
if [[ -n "$running_gpu" ]]; then
  echo "ERROR: direct/local VLM is running in the stable hybrid profile." >&2
  exit 1
fi

for lease in \
  "$PROJECT_ROOT/runtime/gpu-admission/direct-rt-vlm.lease" \
  "$PROJECT_ROOT/runtime/gpu-admission/local-vlm.lease"; do
  if [[ -e "$lease" ]]; then
    echo "ERROR: stale VLM admission lease exists in the stable hybrid profile." >&2
    exit 1
  fi
done

"$PROJECT_ROOT/.venv/bin/python" - "$PROJECT_ROOT/config/runtime/single-gpu-poc.yaml" <<'PY'
import sys
from pathlib import Path

import yaml

policy = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))["alerting"]
assert policy["default_mode"] == "hybrid_candidate_verification"
direct = policy["direct_rt_vlm"]
assert direct["startup"] == "explicit_only"
assert direct["enabled_by_default"] is False
assert direct["selected_cameras"] == ["cam-01"]
assert direct["max_concurrent_cameras"] == 1
print("alert_policy=hybrid_default direct_rt_vlm=opt_in camera=cam-01")
PY
