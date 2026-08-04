#!/usr/bin/env bash
set -euo pipefail

# Keep the browser-facing/control-plane APIs independent from GPU profile
# lifecycle.  GPU start/stop scripts may pause RT-CV or an AI provider, but
# they must never leave 39510/39420/39410/39310 unavailable.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"
source "$PROJECT_ROOT/scripts/phase13-lib.sh"
source "$PROJECT_ROOT/scripts/phase15-lib.sh"

mkdir -p "$PROJECT_ROOT/runtime/locks"
exec 9>"$PROJECT_ROOT/runtime/locks/control-plane.lock"
flock -w 60 9

phase15_compose config --quiet
phase12_compose config --quiet
phase13_compose config --quiet

# These are CPU/control-plane services.  Do not use a GPU compose profile or
# recreate/stop any model container here.
phase15_compose up -d media-intake vlm-test vss-ui phase15-api
phase12_compose up -d search
phase13_compose up -d summarization

phase15_wait_http "http://127.0.0.1:39420/health/ready" 45 "media intake"
phase15_wait_http "http://127.0.0.1:39511/" 90 "NVIDIA VSS UI"
phase15_wait_http "http://127.0.0.1:39510/health/ready" 45 "Phase 15 unified API"
phase15_wait_http "http://127.0.0.1:39520/health/ready" 45 "Phase 15 VLM-test control plane"
phase12_wait_http "http://127.0.0.1:39310/health/ready" 45 "Phase 12 search API"
phase13_wait_http "http://127.0.0.1:39410/health/ready" 45 "Phase 13 summarization API"

echo "Control plane ready: 39310 search, 39410 summarization, 39420 media intake, 39510 gateway, 39511 NVIDIA VSS UI, 39520 VLM-test"
