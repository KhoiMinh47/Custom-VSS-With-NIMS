#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
output="$PROJECT_ROOT/artifacts/benchmarks/phase15-vss-ui/after"
mkdir -p "$output" "$PROJECT_ROOT/.cache/tmp"

curl --fail --silent "http://127.0.0.1:39510/api/v1/overview?refresh=true" >"$output/overview.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/ports >"$output/ports.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/tools >"$output/tools.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/workspace >"$output/workspace.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/workspace/cameras >"$output/cameras.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/workspace/analytics/state >"$output/analytics.json"
curl --fail --silent "http://127.0.0.1:39510/api/v1/workspace/alerts?source=all&limit=200" >"$output/alerts.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/workspace/search/state >"$output/search-state.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/workspace/summaries/state >"$output/summary-state.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/workspace/summaries/jobs >"$output/summary-jobs.json"
curl --fail --silent http://127.0.0.1:39510/api/v1/workspace/reports >"$output/reports.json"
curl --fail --silent http://127.0.0.1:39510/metrics >"$output/metrics.txt"
curl --fail --silent http://127.0.0.1:39510/ >"$output/vss-ui.html"
curl --fail --silent http://127.0.0.1:39510/__ENV.js >"$output/vss-ui-env.js"
curl --fail --silent http://127.0.0.1:39510/compat/vst/api/v1/sensor/list >"$output/vss-ui-sensors.json"
curl --fail --silent 'http://127.0.0.1:39510/compat/mdx/incidents?vlmVerified=false&fromTimestamp=2020-01-01T00%3A00%3A00.000Z&toTimestamp=2030-01-01T00%3A00%3A00.000Z&maxResultSize=100' >"$output/vss-ui-incidents.json"
curl --fail --silent http://127.0.0.1:39510/openapi.json >"$output/openapi.json"
curl --silent --dump-header "$output/vss-ui-headers.txt" --output /dev/null \
  http://127.0.0.1:39510/

search_status="$(curl --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Origin: http://127.0.0.1:39510' \
  --data '{"schema_version":"1.0.0","store_id":"store-001","query":"people waiting in a queue","mode":"manual","route":"action","camera_ids":["cam-01"],"source_type":"all","top_k":3,"similarity_threshold":0,"critic_verification":false}' \
  --output "$output/search-smoke.json" \
  --write-out '%{http_code}' \
  http://127.0.0.1:39510/api/v1/workspace/search)"
case "$search_status" in
  200|202|503) ;;
  *) echo "ERROR: search smoke returned HTTP $search_status." >&2; exit 1 ;;
esac
printf '%s\n' "$search_status" >"$output/search-smoke.status"

summary_id="$("$PROJECT_ROOT/.venv/bin/python" - "$output/summary-jobs.json" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for job in value.get("jobs", []):
    if job.get("status") == "completed":
        print(job.get("job_id", ""))
        break
PY
)"
if [[ "$summary_id" =~ ^[0-9a-f]{64}$ ]]; then
  curl --fail --silent \
    --request POST \
    --header 'Content-Type: application/json' \
    --header 'Origin: http://127.0.0.1:39510' \
    --data "{\"schema_version\":\"1.0.0\",\"store_id\":\"store-001\",\"summary_id\":\"$summary_id\",\"question\":\"man black t-shirt gray pants\",\"idempotency_key\":\"phase15-evidence-grounded-qa\"}" \
    http://127.0.0.1:39510/api/v1/workspace/summaries/qa \
    >"$output/qa-grounded-smoke.json"
  curl --fail --silent \
    --request POST \
    --header 'Content-Type: application/json' \
    --header 'Origin: http://127.0.0.1:39510' \
    --data "{\"schema_version\":\"1.0.0\",\"store_id\":\"store-001\",\"summary_id\":\"$summary_id\",\"question\":\"What was the person's passport number?\",\"idempotency_key\":\"phase15-evidence-refused-qa\"}" \
    http://127.0.0.1:39510/api/v1/workspace/summaries/qa \
    >"$output/qa-refused-smoke.json"
fi

media_id="$("$PROJECT_ROOT/.venv/bin/python" - "$output/alerts.json" <<'PY'
import json
import re
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for alert in value.get("alerts", []):
    reference = str((alert.get("evidence") or {}).get("reference", ""))
    match = re.fullmatch(r"selected-clip://([0-9a-f]{64})\.mp4", reference)
    if alert.get("media_available") and match:
        print(match.group(1))
        break
PY
)"
if [[ "$media_id" =~ ^[0-9a-f]{64}$ ]]; then
  curl --fail --silent \
    --header 'Range: bytes=0-1023' \
    --dump-header "$output/media-range-headers.txt" \
    --output /dev/null \
    "http://127.0.0.1:39510/api/v1/workspace/media/$media_id.mp4"
fi

live_tmp="$(mktemp -d "$PROJECT_ROOT/.cache/tmp/phase15-live-evidence.XXXXXX")"
trap 'rm -rf -- "$live_tmp"' EXIT
touch "$live_tmp/live.mjpeg"
live_status=0
curl --silent --show-error --max-time 5 \
  --dump-header "$output/live-headers.txt" \
  --output "$live_tmp/live.mjpeg" \
  http://127.0.0.1:39510/api/v1/workspace/cameras/cam-01/live.mjpeg \
  || live_status=$?
if [[ "$live_status" -ne 0 && "$live_status" -ne 28 ]]; then
  echo "ERROR: live evidence request failed with curl status $live_status." >&2
  exit "$live_status"
fi
wc -c <"$live_tmp/live.mjpeg" >"$output/live-bytes.txt"

curl --fail --silent http://127.0.0.1:9090/api/v1/targets >"$output/prometheus-targets.json"
docker inspect ntc-vss-phase15-api --format '{{json .Mounts}}' >"$output/mounts.json"
docker inspect ntc-vss-phase15-api \
  --format '{"network_mode":{{json .HostConfig.NetworkMode}},"device_requests":{{json .HostConfig.DeviceRequests}},"devices":{{json .HostConfig.Devices}}}' \
  >"$output/container-isolation.json"
docker inspect ntc-vss-phase15-ui \
  --format '{"mounts":{{json .Mounts}},"network_mode":{{json .HostConfig.NetworkMode}},"device_requests":{{json .HostConfig.DeviceRequests}},"devices":{{json .HostConfig.Devices}}}' \
  >"$output/ui-container-isolation.json"
docker inspect ntc-vss-phase15-ui \
  --format '{{json .Config.Image}}' >"$output/ui-image.json"
ss -ltnp | rg ':3951[01]\b' >"$output/loopback-listener.txt"
docker logs --since 60m ntc-vss-phase15-api 2>&1 | tail -500 >"$output/service.log"
docker logs --since 60m ntc-vss-phase15-ui 2>&1 | tail -500 >"$output/ui-service.log"
"$PROJECT_ROOT/.venv/bin/python" - "$output/service.log" >"$output/structured-log-validation.txt" <<'PY'
import json
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
for number, line in enumerate(lines, 1):
    try:
        json.loads(line)
    except (TypeError, ValueError) as error:
        raise SystemExit(f"invalid JSON log line {number}: {error}") from error
print(f"structured log parse: {len(lines)} JSON lines")
PY
cp "$PROJECT_ROOT/runtime/phase15/gpu-control/worker.json" \
  "$output/gpu-control-worker.json"
tail -500 "$PROJECT_ROOT/runtime/phase15/gpu-control/worker.log" \
  >"$output/gpu-control-worker.log"
nvidia-smi \
  --query-gpu=timestamp,name,memory.total,memory.used,memory.free,utilization.gpu,power.draw \
  --format=csv,noheader >"$output/gpu-state.csv"
find "$PROJECT_ROOT/runtime/gpu-admission" -maxdepth 1 -type f -name '*.lease' \
  -printf '%f\n' | sort >"$output/lease-files.txt"
{
  printf 'bad_host=%s\n' "$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --header 'Host: attacker.invalid' \
    http://127.0.0.1:39510/api/v1/workspace/cameras)"
  printf 'cross_site_get=%s\n' "$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --header 'Sec-Fetch-Site: cross-site' \
    http://127.0.0.1:39510/api/v1/workspace/cameras)"
  printf 'unknown_media=%s\n' "$(curl --silent --output /dev/null --write-out '%{http_code}' \
    http://127.0.0.1:39510/api/v1/workspace/media/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4)"
  printf 'permissive_cors_headers=%s\n' "$(curl --silent --head \
    http://127.0.0.1:39510/ | rg -i '^access-control-allow' || true)"
} >"$output/security-smoke.txt"

"$PROJECT_ROOT/.venv/bin/python" -m pytest -q >"$output/unit-tests.txt"
"$PROJECT_ROOT/.venv/bin/python" -m py_compile \
  "$PROJECT_ROOT/services/api/service.py" \
  "$PROJECT_ROOT/services/api/vss_ui.py"
printf '%s\n' "Python adapter compile: PASS" >"$output/adapter-check.txt"
git -C "$PROJECT_ROOT/third_party/video-search-and-summarization" rev-parse HEAD \
  >"$output/upstream-ui-commit.txt"
git -C "$PROJECT_ROOT/third_party/video-search-and-summarization" describe --tags --exact-match \
  >"$output/upstream-ui-tag.txt"
"$PROJECT_ROOT/.venv/bin/python" -m json.tool \
  "$PROJECT_ROOT/schemas/openapi/phase15.openapi.json" >/dev/null
printf '%s\n' "OpenAPI JSON parse: PASS" >"$output/openapi-validation.txt"
docker compose -f "$PROJECT_ROOT/deploy/compose/phase15.compose.yml" config --quiet
printf '%s\n' "Docker Compose resolution: PASS" >"$output/compose-validation.txt"
sha256sum \
  "$PROJECT_ROOT/apps/vss-ui/README.md" \
  "$PROJECT_ROOT/apps/vss-ui/SOURCE-MANIFEST.json" \
  "$PROJECT_ROOT/config/ui/vss-ui.env" \
  "$PROJECT_ROOT/third_party/video-search-and-summarization/services/ui/apps/nv-metropolis-bp-vss-ui/components/Home.tsx" \
  "$PROJECT_ROOT/third_party/video-search-and-summarization/services/ui/packages/nv-metropolis-bp-vss-ui/search/lib-src/SearchComponent.tsx" \
  "$PROJECT_ROOT/services/api/service.py" \
  "$PROJECT_ROOT/services/api/vss_ui.py" \
  "$PROJECT_ROOT/services/api/workspace.py" \
  "$PROJECT_ROOT/services/search/service.py" \
  "$PROJECT_ROOT/services/summarization/service.py" \
  "$PROJECT_ROOT/schemas/openapi/phase15.openapi.json" \
  >"$output/source-sha256.txt"
{
  echo "No installed browser/browser automation was available during this refinement."
  echo "No browser package or image was downloaded solely for screenshots."
  echo "Visual screenshots, console inspection, keyboard-only validation, and"
  echo "1920x1080, 1440x900, 1024x768, 768x1024, 390x844 viewport captures"
  echo "remain an external PARTIAL gate."
} >"$output/browser-evidence-limitation.txt"

if rg -n -i \
  '(authorization[^[:space:]]*[[:space:]]*[:=][[:space:]]*bearer[[:space:]]+[a-z0-9._-]{8,}|bearer[[:space:]]+[a-z0-9._-]{20,}|ngc_api_key|camera_password|rtsp://[^[:space:]@]+:[^[:space:]@]+@)' \
  "$output"; then
  echo "ERROR: credential-like content found in Phase 15 evidence." >&2
  exit 1
fi
echo "Phase 15 NVIDIA VSS UI secret-safe evidence captured under $output"
