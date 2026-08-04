#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase13-lib.sh"

state="$(curl --fail --silent --show-error http://127.0.0.1:39410/api/v1/state)"
"$PROJECT_ROOT/.venv/bin/python" - "$state" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert value["schema_version"] == "1.0.0"
assert value["store_id"] == "store-001"
assert value["ready"] is True
assert value["evidence_policy"]["accepted_uri"] == "selected-clip://"
print(json.dumps(value, separators=(",", ":")))
PY
curl --fail --silent http://127.0.0.1:39410/dashboard | grep -q "Phase 13"
curl --fail --silent http://127.0.0.1:39410/metrics \
  | grep -q "phase13_summarization_ready 1"
echo "Phase 13 queue, API, dashboard, evidence policy and metrics are healthy."
