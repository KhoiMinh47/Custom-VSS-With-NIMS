#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

vlm_test_state="$(curl --fail --silent --show-error http://127.0.0.1:39520/api/v1/state)"
"$PROJECT_ROOT/.venv/bin/python" - "$vlm_test_state" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert value["schema_version"] == "1.0.0"
assert value["store_id"] == "store-001"
assert value["raw_video_plane_independent"] is True
assert value["upload_store_policy"] == "staging_until_explicit_save_after_vlm"
PY

overview="$(curl --fail --silent --show-error http://127.0.0.1:39510/api/v1/overview?refresh=true)"
"$PROJECT_ROOT/.venv/bin/python" - "$overview" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert value["schema_version"] == "1.0.0"
assert value["store_id"] == "store-001"
assert value["phase"] == "PHASE-15"
assert value["phase14_status"] == "LOCKED_BY_USER"
assert isinstance(value["ready"], bool)
assert value["managed_ports"] >= 10
assert value["architecture"]["raw_video_plane_independent"] is True
assert value["architecture"]["docker_socket_mounted_by_app"] is False
ports = [service["port"] for service in value["services"] if service["port"] is not None]
assert len(ports) == len(set(ports))
by_id = {service["id"]: service for service in value["services"]}
assert by_id["vss-ui"]["status"] == "healthy"
print(json.dumps({"services": len(value["services"]), "counts": value["counts"]}, separators=(",", ":")))
PY

ui_html="$(curl --fail --silent http://127.0.0.1:39510/)"
grep -q "VSS BLUEPRINT" <<<"$ui_html"
grep -q "NV-logo" <<<"$ui_html"
grep -q "/_next/" <<<"$ui_html"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:39510/dashboard)" = "308"

env_script="$(curl --fail --silent http://127.0.0.1:39510/__ENV.js)"
grep -q "NEXT_PUBLIC_ENABLE_ALERTS_TAB" <<<"$env_script"
grep -q "NEXT_PUBLIC_ENABLE_SEARCH_TAB" <<<"$env_script"
grep -q "NEXT_PUBLIC_ENABLE_VIDEO_MANAGEMENT_TAB" <<<"$env_script"
if grep -Eqi '(NGC_API_KEY|rtsp://[^[:space:]@]+:[^[:space:]@]+@)' <<<"$env_script"; then
  echo "ERROR: secret-like content found in browser runtime configuration." >&2
  exit 1
fi

sensors="$(curl --fail --silent http://127.0.0.1:39510/compat/vst/api/v1/sensor/list)"
"$PROJECT_ROOT/.venv/bin/python" - "$sensors" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert len(value) == 1
assert value[0]["name"] == "cam-01"
assert value[0]["sensorId"]
assert set(value[0]) == {"name", "sensorId", "state"}
PY

incidents="$(curl --fail --silent 'http://127.0.0.1:39510/compat/mdx/incidents?vlmVerified=false&fromTimestamp=2020-01-01T00%3A00%3A00.000Z&toTimestamp=2030-01-01T00%3A00%3A00.000Z&maxResultSize=10')"
"$PROJECT_ROOT/.venv/bin/python" - "$incidents" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert value["schema_version"] == "1.0.0"
assert value["store_id"] == "store-001"
assert isinstance(value["incidents"], list)
assert all(item["store_id"] == "store-001" for item in value["incidents"])
assert all(item["camera_id"] == "cam-01" for item in value["incidents"])
PY

chat="$(curl --fail --silent \
  --header 'Content-Type: application/json' \
  --header 'Origin: http://127.0.0.1:39510' \
  --data '{"messages":[{"role":"user","content":"GPU status"}],"chatCompletionURL":"http://untrusted.invalid/"}' \
  http://127.0.0.1:39510/api/chat)"
grep -q "admission-controlled" <<<"$chat"
if grep -q "untrusted.invalid" <<<"$chat"; then
  echo "ERROR: browser-controlled chat upstream was not ignored." >&2
  exit 1
fi

# Real-time Alerts: control-plane read only. Listing rules never starts a VLM.
realtime_rules="$(curl --fail --silent http://127.0.0.1:39510/compat/alert-bridge/api/v1/realtime)"
"$PROJECT_ROOT/.venv/bin/python" - "$realtime_rules" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert isinstance(value, (list, dict))
PY
# A cross-origin rule mutation must be rejected before reaching the upstream.
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header 'Content-Type: application/json' \
  --header 'Origin: http://untrusted.invalid' \
  --data '{}' \
  http://127.0.0.1:39510/compat/alert-bridge/api/v1/realtime)" = "400"

curl --fail --silent http://127.0.0.1:39510/openapi.json | grep -q "3.1.0"
curl --fail --silent http://127.0.0.1:39510/metrics | grep -q "phase15_unified_api_ready 1"
cameras="$(curl --fail --silent http://127.0.0.1:39510/api/v1/workspace/cameras)"
"$PROJECT_ROOT/.venv/bin/python" - "$cameras" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
assert value["schema_version"] == "1.0.0"
assert value["store_id"] == "store-001"
assert value["source_mode"] == "physical_camera_only"
assert value["count"] == 1
assert value["cameras"][0]["camera_id"] == "cam-01"
assert value["cameras"][0]["source_type"] == "physical"
PY

headers="$(curl --silent --dump-header - --output /dev/null http://127.0.0.1:39510/ | tr -d '\r')"
grep -qi "content-security-policy:.*webassets.nvidia.com" <<<"$headers"
grep -qi "content-security-policy:.*media-src 'self' blob:" <<<"$headers"
grep -qi "content-security-policy:.*object-src 'none'" <<<"$headers"

session="$(curl --fail --silent http://127.0.0.1:39510/api/v1/session)"
"$PROJECT_ROOT/.venv/bin/python" - "$session" <<'PY'
import json
import sys

assert json.loads(sys.argv[1]) == {
    "subject": "trusted-loopback",
    "role": "admin",
    "authenticated": True,
}
PY

test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:39510/api/v1/admission)" = "200"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:39510/api/v1/gpu-control)" = "200"
"$PROJECT_ROOT/.venv/bin/python" - "$PROJECT_ROOT/runtime/phase15/gpu-control/worker.json" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert value["status"] == "online"
assert value["gpu"]["memory_total_mib"] > 0
PY

test "$(docker inspect ntc-vss-phase15-ui --format '{{len .Mounts}}')" = "0"
test "$(docker inspect ntc-vss-phase15-ui --format '{{json .HostConfig.DeviceRequests}}')" = "null"
echo "Phase 15 NVIDIA VSS UI, same-origin adapters, gateway, registry and metrics are healthy."
