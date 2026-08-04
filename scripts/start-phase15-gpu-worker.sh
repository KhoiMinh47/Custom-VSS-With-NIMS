#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
control_root="$PROJECT_ROOT/runtime/phase15/gpu-control"
pid_file="$control_root/worker.pid"
log_file="$control_root/worker.log"
unit_name="ntc-vss-phase15-gpu-worker.service"

mkdir -p "$control_root/requests" "$control_root/processing" "$control_root/completed"

if systemctl --user is-active --quiet "$unit_name" 2>/dev/null; then
  worker_pid="$(systemctl --user show "$unit_name" -p MainPID --value)"
  printf '%s\n' "$worker_pid" >"$pid_file"
  echo "Phase 15 GPU control worker is already running (PID $worker_pid)."
  exit 0
fi

if [[ -s "$pid_file" ]]; then
  worker_pid="$(<"$pid_file")"
  if [[ "$worker_pid" =~ ^[0-9]+$ ]] && kill -0 "$worker_pid" 2>/dev/null; then
    echo "Phase 15 GPU control worker is already running (PID $worker_pid)."
    exit 0
  fi
fi

if systemctl --user show-environment >/dev/null 2>&1; then
  systemd-run --user \
    --unit="${unit_name%.service}" \
    --collect \
    --property=Type=simple \
    --property=Restart=on-failure \
    --property=RestartSec=3 \
    --property=TimeoutStopSec=1300 \
    --property=KillMode=mixed \
    --property="WorkingDirectory=$PROJECT_ROOT" \
    "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-control-worker/worker.py" \
    --control-root "$control_root" \
    --admission-root "$PROJECT_ROOT/runtime/gpu-admission" \
    --poll-seconds 2 \
    --log-file "$log_file" >/dev/null
  worker_pid="$(systemctl --user show "$unit_name" -p MainPID --value)"
else
  nohup "$PROJECT_ROOT/.venv/bin/python" \
    "$PROJECT_ROOT/services/gpu-control-worker/worker.py" \
    --control-root "$control_root" \
    --admission-root "$PROJECT_ROOT/runtime/gpu-admission" \
    --poll-seconds 2 \
    --log-file "$log_file" \
    >>"$log_file" 2>&1 &
  worker_pid=$!
fi
printf '%s\n' "$worker_pid" >"$pid_file"

deadline=$((SECONDS + 20))
until "$PROJECT_ROOT/.venv/bin/python" - "$control_root/worker.json" "$worker_pid" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
pid = int(sys.argv[2])
if not path.is_file():
    raise SystemExit(1)
value = json.loads(path.read_text(encoding="utf-8"))
raise SystemExit(0 if value.get("status") == "online" and value.get("pid") == pid else 1)
PY
do
  if ! kill -0 "$worker_pid" 2>/dev/null; then
    echo "ERROR: Phase 15 GPU control worker exited during startup." >&2
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "ERROR: Phase 15 GPU control worker did not report ready." >&2
    exit 1
  fi
  sleep 1
done

echo "Phase 15 GPU control worker is online (PID $worker_pid)."
