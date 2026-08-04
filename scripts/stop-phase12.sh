#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase12-lib.sh"

# Stop only the optional GPU services.  The CPU search API is part of this
# compose file and must remain available while an embedding/SigLIP window is
# torn down.
phase12_compose --profile rt-embedding --profile siglip stop \
  rt-embedding siglip-object-embedding
for lease in \
  phase12-rt-embedding.lease phase12-siglip.lease \
  phase12-llm.lease phase12-critic.lease; do
  phase12_revoke "$PROJECT_ROOT/runtime/gpu-admission/$lease" >/dev/null
done
echo "Phase 12 services stopped; vectors, evidence, engines, caches and images preserved."
