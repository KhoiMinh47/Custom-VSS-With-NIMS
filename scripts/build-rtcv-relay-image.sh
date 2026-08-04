#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base="nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1@sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458"
target="ntc-vss-retail-poc/rtcv-relay:3.2.1-phase07"

DOCKER_BUILDKIT=0 docker build \
  --build-arg "VSS_RTCV_IMAGE=$base" \
  -f "$PROJECT_ROOT/deploy/docker/rtcv-relay.Dockerfile" \
  -t "$target" \
  "$PROJECT_ROOT"

docker image inspect "$target" \
  --format '{{.Id}}' \
  > "$PROJECT_ROOT/artifacts/manifests/phase07-rtcv-relay-image-id.txt"
