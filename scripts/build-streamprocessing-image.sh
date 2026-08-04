#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base="nvcr.io/nvidia/vss-core/vss-vios-streamprocessing:3.2.1@sha256:c59f53396e8390734b6fc3559ffec6929d153499a6ec1410bf477402de983cff"
target="ntc-vss-retail-poc/vios-streamprocessing:3.2.1-phase06"

mkdir -p "$PROJECT_ROOT/.cache/buildkit/streamprocessing"

docker buildx build \
  --load \
  --build-arg "VSS_MEDIA_IMAGE=$base" \
  --cache-from "type=local,src=$PROJECT_ROOT/.cache/buildkit/streamprocessing" \
  --cache-to "type=local,dest=$PROJECT_ROOT/.cache/buildkit/streamprocessing,mode=max" \
  -f "$PROJECT_ROOT/deploy/docker/video-source.Dockerfile" \
  -t "$target" \
  "$PROJECT_ROOT"

docker image inspect "$target" \
  --format '{{.Id}}' \
  > "$PROJECT_ROOT/artifacts/manifests/phase06-streamprocessing-image-id.txt"
