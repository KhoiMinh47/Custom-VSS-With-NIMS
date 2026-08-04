#!/usr/bin/env bash
set -euo pipefail

deadline=$((SECONDS + 180))
until curl --fail --silent --max-time 5 \
  http://127.0.0.1:39210/health/ready >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: Phase 11 result collector did not become ready." >&2
    exit 1
  fi
  sleep 2
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:39210/api/v1/state", timeout=10) as response:
    state = json.load(response)
assert state["schema_version"] == "1.0.0"
assert state["store_id"] == "store-001"
assert state["camera_id"] == "cam-01"
assert state["model_id"] == "nvidia/cosmos3-nano-reasoner"
print(
    f'Phase 11 collector healthy: direct={state["direct_rt_vlm_status"]} '
    f'persisted={state["persisted"]}'
)
PY
