#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
SERVER="$PROJECT_ROOT/services/video-management/mjpeg_server.py"
SOCKET="$PROJECT_ROOT/runtime/secrets/camera-secret.sock"
PID_FILE="$PROJECT_ROOT/runtime/secrets/camera-live.pid"
LOG="$PROJECT_ROOT/runtime/logs/camera-live.log"
PORT="${CAMERA_LIVE_PORT:-8090}"

case "${1:-start}" in
  start)
    if [[ ! -S "$SOCKET" ]]; then
      echo "ERROR: save the camera first: make camera-save" >&2
      exit 1
    fi
    if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
      echo "camera_live=already_running mjpeg=http://127.0.0.1:$PORT/mjpeg ai_overlay=http://127.0.0.1:$PORT/ai-overlay"
      exit 0
    fi
    mkdir -p "$PROJECT_ROOT/runtime/logs" "$PROJECT_ROOT/runtime/secrets"
    setsid nohup "$PYTHON" "$SERVER" --port "$PORT" --secret-socket "$SOCKET" \
      >"$LOG" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if ! kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
      echo "ERROR: live preview failed to start; see runtime/logs/camera-live.log" >&2
      exit 1
    fi
    echo "camera_live=running mjpeg=http://127.0.0.1:$PORT/mjpeg ai_overlay=http://127.0.0.1:$PORT/ai-overlay"
    ;;
  stop)
    if [[ -f "$PID_FILE" ]]; then
      pid="$(<"$PID_FILE")"
      if kill -0 "$pid" 2>/dev/null; then kill "$pid"; fi
      rm -f "$PID_FILE"
    fi
    echo "camera_live=stopped"
    ;;
  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
      echo "camera_live=running mjpeg=http://127.0.0.1:$PORT/mjpeg ai_overlay=http://127.0.0.1:$PORT/ai-overlay"
    else
      echo "camera_live=stopped"
      exit 1
    fi
    ;;
  overlay)
    "$0" start
    if ! curl --fail --silent --show-error \
      "http://127.0.0.1:$PORT/ai-overlay" >/dev/null; then
      echo "ERROR: AI overlay endpoint is unavailable." >&2
      exit 1
    fi
    echo "camera_ai_overlay=http://127.0.0.1:$PORT/ai-overlay"
    ;;
  *)
    echo "Usage: $0 start|stop|status|overlay" >&2
    exit 2
    ;;
esac
