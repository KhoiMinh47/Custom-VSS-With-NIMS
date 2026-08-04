#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$PROJECT_ROOT/artifacts/manifests/inventory-$timestamp"
mkdir -p "$destination"

docker images --digests > "$destination/docker-images.txt"
docker ps -a \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' \
  > "$destination/docker-containers.txt"
docker system df -v > "$destination/docker-disk.txt"
df -hT "$PROJECT_ROOT" > "$destination/project-filesystem.txt"

echo "$destination"
