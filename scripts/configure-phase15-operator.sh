#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
subject="${1:-}"
role="${2:-operator}"
target="$PROJECT_ROOT/.secrets/phase15/token-hashes.json"

if [[ ! "$subject" =~ ^[A-Za-z0-9._@+-]{2,120}$ ]]; then
  echo "Usage: bash scripts/configure-phase15-operator.sh SUBJECT [analyst|operator|model_engineer|admin]" >&2
  exit 2
fi
case "$role" in
  analyst|operator|model_engineer|admin) ;;
  *) echo "ERROR: unsupported Phase 15 role." >&2; exit 2 ;;
esac

read -r -s -p "Enter a new bearer token (minimum 24 characters): " operator_token
echo
if (( ${#operator_token} < 24 )); then
  unset operator_token
  echo "ERROR: token is too short." >&2
  exit 2
fi

mkdir -p "$(dirname "$target")"
chmod 700 "$(dirname "$target")"
printf '%s' "$operator_token" \
  | "$PROJECT_ROOT/.venv/bin/python" \
      "$PROJECT_ROOT/services/api/configure_token.py" "$target" "$subject" "$role"
unset operator_token
echo "Phase 15 token digest stored with mode 600; the plaintext token was not persisted."
