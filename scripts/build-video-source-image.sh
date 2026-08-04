#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base="nvcr.io/nvidia/vss-core/vss-vios-nvstreamer:3.2.1@sha256:7074784d32f996734ef091405f14965573d40257d843bba29d7ca2ef36f58e4d"
target="ntc-vss-retail-poc/video-source:3.2.1-phase06"

mkdir -p "$PROJECT_ROOT/.cache/buildkit/video-source"

docker buildx build \
  --load \
  --build-arg "VSS_MEDIA_IMAGE=$base" \
  --cache-from "type=local,src=$PROJECT_ROOT/.cache/buildkit/video-source" \
  --cache-to "type=local,dest=$PROJECT_ROOT/.cache/buildkit/video-source,mode=max" \
  -f "$PROJECT_ROOT/deploy/docker/video-source.Dockerfile" \
  -t "$target" \
  "$PROJECT_ROOT"

docker image inspect "$target" \
  --format '{{.Id}}' \
  > "$PROJECT_ROOT/artifacts/manifests/phase06-video-source-image-id.txt"
