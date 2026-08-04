#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
control_root="$PROJECT_ROOT/runtime/phase15/gpu-control"
pid_file="$control_root/worker.pid"
unit_name="ntc-vss-phase15-gpu-worker.service"

if systemctl --user is-active --quiet "$unit_name" 2>/dev/null; then
  systemctl --user stop "$unit_name"
  printf '%s\n' "" >"$pid_file"
  echo "Phase 15 GPU control worker stopped; active GPU workload was not changed."
  exit 0
fi

if [[ ! -s "$pid_file" ]]; then
  echo "Phase 15 GPU control worker is not running."
  exit 0
fi

worker_pid="$(<"$pid_file")"
if [[ ! "$worker_pid" =~ ^[0-9]+$ ]] || ! kill -0 "$worker_pid" 2>/dev/null; then
  printf '%s\n' "" >"$pid_file"
  echo "Phase 15 GPU control worker is already stopped."
  exit 0
fi

kill -TERM "$worker_pid"
deadline=$((SECONDS + 30))
while kill -0 "$worker_pid" 2>/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "GPU worker is finishing an active transition; it was left running to avoid interrupting the profile switch."
    exit 0
  fi
  sleep 1
done
printf '%s\n' "" >"$pid_file"
echo "Phase 15 GPU control worker stopped; active GPU workload was not changed."
