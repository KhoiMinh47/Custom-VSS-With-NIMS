#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/video-lib.sh"
video_require_python

mkdir -p \
  "$PROJECT_ROOT/runtime/raw-video" \
  "$PROJECT_ROOT/runtime/clips" \
  "$PROJECT_ROOT/runtime/snapshots" \
  "$PROJECT_ROOT/runtime/simulated-cameras" \
  "$PROJECT_ROOT/runtime/vios/config" \
  "$PROJECT_ROOT/runtime/vios/data" \
  "$PROJECT_ROOT/runtime/vios/nginx-logs" \
  "$PROJECT_ROOT/runtime/vios/nvstreamer" \
  "$PROJECT_ROOT/runtime/vios/postgres" \
  "$PROJECT_ROOT/runtime/vios/redis" \
  "$PROJECT_ROOT/runtime/vios/temp"

"$VIDEO_PYTHON" "$PROJECT_ROOT/services/video-management/render_vios_config.py"
"$VIDEO_PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" validate

if ! docker image inspect ntc-vss-retail-poc/video-source:3.2.1-phase06 >/dev/null 2>&1; then
  "$PROJECT_ROOT/scripts/build-video-source-image.sh"
fi
if ! docker image inspect ntc-vss-retail-poc/vios-streamprocessing:3.2.1-phase06 >/dev/null 2>&1; then
  "$PROJECT_ROOT/scripts/build-streamprocessing-image.sh"
fi

sample="$PROJECT_ROOT/runtime/simulated-cameras/cam-01.mp4"
if [[ ! -s "$sample" ]]; then
  docker run --rm --gpus all \
    -v "$PROJECT_ROOT/runtime/simulated-cameras:/output" \
    --entrypoint /bin/bash \
    nvcr.io/nvidia/vss-core/vss-vios-nvstreamer:3.2.1 \
    -lc 'gst-launch-1.0 -e videotestsrc num-buffers=600 is-live=false pattern=ball ! video/x-raw,width=640,height=360,framerate=10/1 ! nvvideoconvert ! video/x-raw\(memory:NVMM\),format=NV12 ! nvv4l2h264enc bitrate=1000000 ! h264parse ! mp4mux ! filesink location=/output/cam-01.mp4'
fi

for index in $(seq -w 2 10); do
  target="$PROJECT_ROOT/runtime/simulated-cameras/cam-$index.mp4"
  if [[ ! -s "$target" ]]; then
    cp --reflink=auto "$sample" "$target"
  fi
done

count="$(find "$PROJECT_ROOT/runtime/simulated-cameras" -maxdepth 1 -type f -name 'cam-*.mp4' -size +0c | wc -l)"
if [[ "$count" -ne 10 ]]; then
  echo "ERROR: expected 10 simulated videos, found $count." >&2
  exit 1
fi
echo "Prepared $count project-local simulated camera sources."
