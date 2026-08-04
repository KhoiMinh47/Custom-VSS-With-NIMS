#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"

phase12_compose --profile siglip stop siglip-object-embedding
phase12_revoke "$PROJECT_ROOT/runtime/gpu-admission/phase12-siglip.lease"
phase12_restore_realtime_gpu
echo "SigLIP2 stopped; engine/index preserved and RT-CV restored."
