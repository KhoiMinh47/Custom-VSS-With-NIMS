#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/video-lib.sh"
source "$PROJECT_ROOT/scripts/infra-lib.sh"
video_require_python
require_infra_env
set -a
# shellcheck disable=SC1090
source "$INFRA_ENV_FILE"
set +a

"$VIDEO_PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" \
  --registry "$VIDEO_REGISTRY" \
  generate-simulated-secrets
"$VIDEO_PYTHON" "$PROJECT_ROOT/services/video-management/registry_cli.py" \
  --registry "$VIDEO_REGISTRY" onboard

infra_compose exec -T postgres psql -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  < "$PROJECT_ROOT/migrations/002_video_management.sql"

"$VIDEO_PYTHON" "$PROJECT_ROOT/services/video-management/seed_sql.py" \
  --registry "$VIDEO_REGISTRY" \
  | infra_compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"

camera_count="$(
  infra_compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT count(*) FROM cameras WHERE external_id LIKE 'cam-%';"
)"
if [[ "$camera_count" -ne 10 ]]; then
  echo "ERROR: expected 10 control-plane cameras, found $camera_count." >&2
  exit 1
fi
echo "Onboarded 10 camera references without persisting plaintext RTSP credentials."
