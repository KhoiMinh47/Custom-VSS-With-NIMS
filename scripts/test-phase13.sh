#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase13-lib.sh"
evidence="$PROJECT_ROOT/artifacts/logs/phase13-smoke.txt"

mkdir -p "$PROJECT_ROOT/artifacts/logs"
phase13_compose config --quiet
"$PROJECT_ROOT/.venv/bin/python" -m pytest -q \
  "$PROJECT_ROOT/tests/unit/test_phase13.py"
"$PROJECT_ROOT/scripts/healthcheck-phase13.sh"

latest="$(curl --fail --silent http://127.0.0.1:39410/api/v1/jobs)"
"$PROJECT_ROOT/.venv/bin/python" - "$latest" <<'PY' | tee "$evidence"
import json
import sys

value = json.loads(sys.argv[1])
completed = [job for job in value["jobs"] if job["status"] == "completed"]
assert len(completed) >= 2
assert any(job["source_type"] == "selected_video" for job in completed)
assert any(job["source_type"] == "time_window" for job in completed)
for job in completed:
    assert job["summary"]["evidence"]
    assert all(item["asset_uri"].startswith("selected-clip://") for item in job["summary"]["evidence"])
print(json.dumps({"phase13": "PASS", "completed_jobs": len(completed)}, separators=(",", ":")))
PY

if rg -n -i \
  '(ngc_api_key|camera_password|rtsp://[^[:space:]@]+:[^[:space:]@]+@)' \
  "$PROJECT_ROOT/services/summarization" \
  "$PROJECT_ROOT/services/reporting" \
  "$PROJECT_ROOT/config/prompts/summarization" \
  "$PROJECT_ROOT/config/prompts/reporting" \
  "$PROJECT_ROOT/deploy/compose/phase13.compose.yml" \
  "$evidence"; then
  echo "ERROR: credential-like content found in Phase 13 artifacts." >&2
  exit 1
fi
if rg -n 'runtime/raw-video' \
  "$PROJECT_ROOT/services/summarization" \
  "$PROJECT_ROOT/services/reporting" \
  "$PROJECT_ROOT/deploy/compose/phase13.compose.yml"; then
  echo "ERROR: Phase 13 code or Compose references recording storage." >&2
  exit 1
fi
echo "Phase 13 contracts, resume, evidence, refusal, report and isolation tests passed."
