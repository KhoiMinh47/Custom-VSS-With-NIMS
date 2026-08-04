#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_SERVICE="ntc-vss-retail-poc"
CAMERA_ID="${CAMERA_ID:-physical-cam-01}"
TARGET_CAMERA_ID="${TARGET_CAMERA_ID:-cam-01}"
SECRET_TOOL="$(command -v secret-tool || true)"
KEYCTL="$(command -v keyctl || true)"
KERNEL_KEY_NAME="${SECRET_SERVICE}:v2:${CAMERA_ID}"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
SECRET_AGENT="$PROJECT_ROOT/services/video-management/camera_secret_agent.py"
SECRET_SOCKET="$PROJECT_ROOT/runtime/secrets/camera-secret.sock"
SECRET_PID="$PROJECT_ROOT/runtime/secrets/camera-secret.pid"
HYBRID_REGISTRY="$PROJECT_ROOT/config/cameras/cameras.hybrid.json"
SIMULATED_REGISTRY="$PROJECT_ROOT/config/cameras/cameras.simulated.json"
URI_MAP="$PROJECT_ROOT/.secrets/camera-uris.json"

usage() {
  echo "Usage: $0 save|probe|probe-ai|activate|mainstream|lease|restore|clear|status" >&2
}

lookup() {
  if [[ -n "$SECRET_TOOL" ]] && "$SECRET_TOOL" lookup service "$SECRET_SERVICE" camera "$CAMERA_ID" 2>/dev/null; then
    return 0
  fi
  if [[ -n "$KEYCTL" ]]; then
    key_id="$("$KEYCTL" search @u user "$KERNEL_KEY_NAME" 2>/dev/null || true)"
    if [[ -n "$key_id" ]] && "$KEYCTL" pipe "$key_id" 2>/dev/null; then
      return 0
    fi
  fi
  if "$PYTHON" "$SECRET_AGENT" get --socket "$SECRET_SOCKET" --pid "$SECRET_PID" 2>/dev/null; then
    return 0
  fi
  return 1
}

case "${1:-}" in
  save)
    if [[ ! -t 0 ]]; then
      echo "ERROR: run save from an interactive terminal." >&2
      exit 1
    fi
    printf 'Paste RTSP URI (input hidden): '
    stty -echo
    IFS= read -r uri
    stty echo
    printf '\n'
    if [[ "$uri" != rtsp://* ]]; then
      echo "ERROR: value must start with rtsp://" >&2
      exit 1
    fi
    if [[ -n "$SECRET_TOOL" ]] && printf '%s\n' "$uri" | "$SECRET_TOOL" store --label="NVIDIA VSS camera $CAMERA_ID" service "$SECRET_SERVICE" camera "$CAMERA_ID" >/dev/null 2>&1; then
      backend="system-keyring"
    elif printf '%s\n' "$uri" | "$PYTHON" "$SECRET_AGENT" start \
      --socket "$SECRET_SOCKET" --pid "$SECRET_PID" >/dev/null; then
      backend="in-memory-secret-agent"
    elif [[ -n "$KEYCTL" ]]; then
      key_id="$(printf '%s\n' "$uri" | "$KEYCTL" padd user "$KERNEL_KEY_NAME" @u 2>/dev/null || true)"
      if [[ -z "$key_id" ]] || ! "$KEYCTL" setperm "$key_id" 0x3f3f0000 2>/dev/null; then
        echo "ERROR: could not create a readable volatile kernel key." >&2
        exit 1
      fi
      backend="volatile-kernel-keyring"
    else
      echo "ERROR: no usable secret store is available." >&2
      exit 1
    fi
    unset uri
    echo "Saved camera credential as reference camera://keyring/$CAMERA_ID ($backend)."
    ;;
  probe)
    proxy_uri="$("$PYTHON" - <<'PY'
import json
from urllib.request import urlopen

try:
    with urlopen("http://127.0.0.1:30888/vst/api/v1/sensor/streams", timeout=5) as response:
        wrappers = json.load(response)
    for wrapper in wrappers:
        for values in wrapper.values():
            if not isinstance(values, list):
                continue
            for stream in values:
                if (
                    isinstance(stream, dict)
                    and stream.get("name") == "cam-01"
                    and str(stream.get("url", "")).startswith("rtsp://")
                ):
                    print(stream["url"])
                    raise SystemExit(0)
except Exception:
    pass
PY
)"
    if [[ -n "$proxy_uri" ]]; then
      printf '%s\n' "$proxy_uri" \
        | "$PYTHON" "$PROJECT_ROOT/services/video-management/secure_rtsp_probe.py"
      unset proxy_uri
    elif ! lookup | "$PYTHON" "$PROJECT_ROOT/services/video-management/secure_rtsp_probe.py"; then
      echo "ERROR: keyring lookup or physical RTSP probe failed." >&2
      exit 1
    fi
    ;;
  probe-ai)
    mkdir -p "$PROJECT_ROOT/artifacts/logs"
    if ! lookup | "$PYTHON" -c \
      'import re,sys; u=sys.stdin.read().strip(); print(re.sub(r"/Streaming/Channels/(?:101|102)$", "/Streaming/Channels/102", u, flags=re.I))' \
      | "$PYTHON" "$PROJECT_ROOT/services/video-management/secure_rtsp_probe.py" \
      | tee "$PROJECT_ROOT/artifacts/logs/phase07-physical-ai-substream-probe.txt"; then
      echo "ERROR: physical AI substream 102 probe failed." >&2
      exit 1
    fi
    ;;
  activate)
    "$PROJECT_ROOT/scripts/healthcheck-video-management.sh"
    "$PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" \
      --registry "$HYBRID_REGISTRY" validate
    "$PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" \
      --registry "$HYBRID_REGISTRY" generate-simulated-secrets --output "$URI_MAP"
    if ! lookup | "$PYTHON" -c \
      'import re,sys; u=sys.stdin.read().strip(); print(re.sub(r"/Streaming/Channels/(?:101|102)$", "/Streaming/Channels/101", u, flags=re.I))' \
      | "$PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" \
      --registry "$HYBRID_REGISTRY" activate-camera \
      --camera-id "$TARGET_CAMERA_ID" --secrets "$URI_MAP"; then
      echo "ERROR: physical activation failed; restoring the simulated camera." >&2
      "$PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" \
        --registry "$HYBRID_REGISTRY" onboard --secrets "$URI_MAP" || true
      exit 1
    fi
    "$PYTHON" "$PROJECT_ROOT/services/video-management/render_live_playlist.py" \
      --output "$PROJECT_ROOT/artifacts/phase06-live-streams.m3u"
    echo "camera_activation=$TARGET_CAMERA_ID:physical"
    ;;
  mainstream)
    uri="$(lookup)"
    if [[ "$uri" != rtsp://* ]]; then
      echo "ERROR: saved camera URI is unavailable." >&2
      exit 1
    fi
    if [[ "$uri" == */Streaming/Channels/102 ]]; then
      uri="${uri%/Streaming/Channels/102}/Streaming/Channels/101"
    fi
    printf '%s\n' "$uri" | "$PYTHON" "$SECRET_AGENT" start \
      --socket "$SECRET_SOCKET" --pid "$SECRET_PID" >/dev/null
    unset uri
    "$0" activate
    "$PROJECT_ROOT/scripts/camera-live.sh" stop >/dev/null 2>&1 || true
    "$PROJECT_ROOT/scripts/camera-live.sh" start
    echo "camera_stream=$TARGET_CAMERA_ID:mainstream-2560x1440-h265"
    ;;
  lease)
    if ! lookup | "$PYTHON" "$SECRET_AGENT" start \
      --socket "$SECRET_SOCKET" --pid "$SECRET_PID" >/dev/null; then
      echo "ERROR: could not materialize the runtime-only camera secret lease." >&2
      exit 1
    fi
    echo "camera_secret_lease=$TARGET_CAMERA_ID:available"
    ;;
  restore)
    "$PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" \
      --registry "$SIMULATED_REGISTRY" generate-simulated-secrets --output "$URI_MAP"
    "$PYTHON" - "$URI_MAP" <<'PY' | "$PYTHON" \
      "$PROJECT_ROOT/services/video-management/registry_cli.py" \
      --registry "$SIMULATED_REGISTRY" activate-camera \
      --camera-id "$TARGET_CAMERA_ID" --secrets "$URI_MAP"
import json
import sys
from pathlib import Path

print(json.loads(Path(sys.argv[1]).read_text())["camera://phase06/cam-01/main"])
PY
    "$PYTHON" "$PROJECT_ROOT/services/video-management/render_live_playlist.py" \
      --output "$PROJECT_ROOT/artifacts/phase06-live-streams.m3u"
    echo "camera_activation=$TARGET_CAMERA_ID:simulated"
    ;;
  clear)
    "$SECRET_TOOL" clear service "$SECRET_SERVICE" camera "$CAMERA_ID" >/dev/null 2>&1 || true
    if [[ -n "$KEYCTL" ]]; then
      key_id="$("$KEYCTL" search @u user "$KERNEL_KEY_NAME" 2>/dev/null || true)"
      [[ -z "$key_id" ]] || "$KEYCTL" unlink "$key_id" @u >/dev/null 2>&1 || true
    fi
    "$PYTHON" "$SECRET_AGENT" stop --socket "$SECRET_SOCKET" --pid "$SECRET_PID" \
      >/dev/null 2>&1 || true
    echo "Cleared keyring entry for $CAMERA_ID."
    ;;
  status)
    if lookup >/dev/null 2>&1; then
      echo "camera_keyring=$CAMERA_ID:available"
    else
      echo "camera_keyring=$CAMERA_ID:missing"
      exit 1
    fi
    ;;
  *)
    usage
    exit 2
    ;;
esac
