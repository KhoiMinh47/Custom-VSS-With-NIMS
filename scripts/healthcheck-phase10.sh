#!/usr/bin/env bash
set -euo pipefail

deadline=$((SECONDS + 120))
for port in 39121 39120; do
  until curl --fail --silent --max-time 5 \
    "http://127.0.0.1:${port}/health/ready" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: Phase 10 service on port ${port} did not become ready." >&2
      exit 1
    fi
    sleep 2
  done
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import json
from urllib.request import urlopen
with urlopen("http://127.0.0.1:39121/api/v1/state", timeout=10) as response:
    incidents = json.load(response)
with urlopen("http://127.0.0.1:39120/api/v1/state", timeout=10) as response:
    verification = json.load(response)
assert incidents["schema_version"] == verification["schema_version"] == "1.0.0"
assert incidents["camera_id"] == verification["camera_id"] == "cam-01"
print(
    f'Phase 10 healthy: incidents={incidents["incidents_prepared"]} '
    f'verified={verification["verified"]} admission={verification["admission_status"]}'
)
PY
