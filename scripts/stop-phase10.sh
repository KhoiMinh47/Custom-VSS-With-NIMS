#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase10-lib.sh"
phase10_compose stop
echo "Phase 10 services stopped; incidents, selected clips, images and caches preserved."
