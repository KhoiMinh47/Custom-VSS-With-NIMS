#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"

require_phase02_pass() {
  gate_file="$PROJECT_ROOT/artifacts/preflight/preflight-result.env"
  if [[ ! -f "$gate_file" ]] || ! grep -qx 'RESULT=PASS' "$gate_file"; then
    if [[ "${VSS_UNSUPPORTED_HOST_OVERRIDE:-}" == "ACKNOWLEDGED_BY_USER_2026-07-23" ]]; then
      echo "WARNING: continuing on an unsupported host by explicit user acknowledgement."
      return 0
    fi
    echo "BLOCKED: PHASE-02 preflight must be PASS."
    return 2
  fi
}

require_ngc_key() {
  if [[ -z "${NGC_API_KEY:-}" ]]; then
    echo "BLOCKED: NGC_API_KEY is not loaded in the current shell."
    return 2
  fi
}

require_project_disk_headroom() {
  llm_free_bytes="$(df -B1 --output=avail "$NIM_LLM_CACHE" | tail -n1 | tr -d ' ')"
  vlm_free_bytes="$(df -B1 --output=avail "$NIM_VLM_CACHE" | tail -n1 | tr -d ' ')"
  if [[ "$llm_free_bytes" -lt 250000000000 || "$vlm_free_bytes" -lt 250000000000 ]]; then
    echo "BLOCKED: less than 250 GB free on a NIM cache filesystem."
    return 2
  fi
}
