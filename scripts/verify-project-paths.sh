#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$PROJECT_ROOT/scripts/env.sh"

assert_under_project() {
  name="$1"
  value="$2"
  case "$value" in
    "$PROJECT_ROOT"|"$PROJECT_ROOT"/*) ;;
    *)
      echo "ERROR: $name escapes project root: $value"
      return 1
      ;;
  esac
}

variables=(
  VIRTUAL_ENV XDG_CACHE_HOME PIP_CACHE_DIR UV_CACHE_DIR
  UV_PYTHON_INSTALL_DIR COREPACK_HOME PNPM_HOME PNPM_STORE_DIR
  HF_HOME HUGGINGFACE_HUB_CACHE TRANSFORMERS_CACHE
  TORCH_HOME TRITON_CACHE_DIR NGC_CLI_HOME TMPDIR
  NIM_LLM_CACHE NIM_VLM_CACHE TENSORRT_CACHE
)

for name in "${variables[@]}"; do
  assert_under_project "$name" "${!name}"
done

test -x "$PROJECT_ROOT/.venv/bin/python"
"$PROJECT_ROOT/.venv/bin/python" - "$PROJECT_ROOT" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
prefix = pathlib.Path(sys.prefix).resolve()
if root not in (prefix, *prefix.parents):
    raise SystemExit(f"Python prefix escapes project: {prefix}")
print(f"Python {sys.version.split()[0]} prefix OK: {prefix}")
PY

if rg -n \
  'docker[[:space:]]+(system|image|builder|volume)[[:space:]]+prune|docker[[:space:]]+rmi|docker[[:space:]]+compose.*down[[:space:]]+-v' \
  "$PROJECT_ROOT/scripts"; then
  echo "ERROR: destructive Docker command found in scripts."
  exit 1
fi

if git -C "$PROJECT_ROOT" ls-files --error-unmatch .secrets/infra.env >/dev/null 2>&1; then
  echo "ERROR: local secret file is tracked by Git."
  exit 1
fi

echo "Project path and destructive-command guards PASS."
