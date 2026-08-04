#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/video-lib.sh"
video_require_python

if [[ ! -t 0 ]]; then
  echo "ERROR: run this probe from an interactive terminal." >&2
  exit 1
fi

echo "Paste the RTSP URI; input is hidden and is never written to an artifact:"
"$VIDEO_PYTHON" "$PROJECT_ROOT/services/video-management/secure_rtsp_probe.py"
