#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"

state="$(curl --fail --silent --show-error http://127.0.0.1:39310/api/v1/state)"
"$PROJECT_ROOT/.venv/bin/python" - "$state" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert value["schema_version"] == "1.0.0"
assert value["store_id"] == "store-001"
assert value["ready"] is True
assert value["video_model"]["dimension"] == 768
assert value["object_model"]["dimension"] == 1152
print(json.dumps(value, separators=(",", ":")))
PY
curl --fail --silent http://127.0.0.1:39310/dashboard | grep -q "Phase 12"
curl --fail --silent http://127.0.0.1:39310/metrics | grep -q "phase12_search_ready"
echo "Phase 12 search API, dashboard, vector contracts and metrics are healthy."
