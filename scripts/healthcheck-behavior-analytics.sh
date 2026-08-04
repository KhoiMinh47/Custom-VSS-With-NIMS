#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
deadline=$((SECONDS + 120))
until curl --fail --silent --max-time 5 \
  http://127.0.0.1:39110/health/ready >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: Phase 09 behavior analytics did not become ready." >&2
    exit 1
  fi
  sleep 2
done

"$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import json
from urllib.request import urlopen
with urlopen("http://127.0.0.1:39110/api/v1/state", timeout=10) as response:
    state = json.load(response)
assert state["schema_version"] == "1.0.0"
assert state["store_id"] == "store-001"
assert state["camera_id"] == "cam-01"
print(
    f'Phase 09 healthy: camera_id={state["camera_id"]} '
    f'frames={state["frames_processed"]} events={state["events_emitted"]}'
)
PY
