#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/behavior-lib.sh"
behavior_compose stop
echo "Stopped Phase 09 behavior analytics; image, config, Kafka, Elasticsearch and runtime state were preserved."
