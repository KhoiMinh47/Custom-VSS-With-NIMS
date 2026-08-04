#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase11-lib.sh"

if docker ps --format '{{.Names}}' \
  | grep -Eq '^(ntc-vss-phase11-rt-vlm|ntc-vss-retail-poc-gpu-poc-cosmos3-1)$'; then
  "$PROJECT_ROOT/scripts/stop-phase11-direct.sh"
else
  phase11_revoke
fi
phase11_compose stop rt-vlm-results
phase11_stop_resource_monitor
echo "Phase 11 services stopped; Kafka, Elasticsearch, images and caches preserved."
