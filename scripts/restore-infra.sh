#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/infra-lib.sh"

usage() {
  echo "Usage: $0 BACKUP_ID [--execute --target-db DATABASE]"
  echo "Default is a non-mutating validation dry-run."
}

[[ $# -ge 1 ]] || { usage; exit 2; }
backup_id="$1"
shift
execute=false
target_db=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) execute=true ;;
    --target-db)
      shift
      target_db="${1:-}"
      ;;
    *) usage; exit 2 ;;
  esac
  shift
done

backup_dir="$PROJECT_ROOT/runtime/backups/$backup_id"
test -f "$backup_dir/postgres/vss_control.dump"
test -f "$backup_dir/redis/dump.rdb"
test -f "$backup_dir/elasticsearch-snapshot-result.json"
(cd "$backup_dir" && sha256sum --check SHA256SUMS)
infra_compose exec -T postgres pg_restore --list \
  < "$backup_dir/postgres/vss_control.dump" >/dev/null
jq -e '.snapshot.state == "SUCCESS"' \
  "$backup_dir/elasticsearch-snapshot-result.json" >/dev/null

if [[ "$execute" != true ]]; then
  echo "Restore dry-run PASS for $backup_id. No data was changed."
  exit 0
fi

if [[ -z "$target_db" || ! "$target_db" =~ ^[a-zA-Z][a-zA-Z0-9_]*$ ]]; then
  echo "ERROR: --target-db must name a new validation database."
  exit 2
fi

exists="$(infra_compose exec -T postgres \
  psql -At --username "${POSTGRES_USER:-vss_app}" --dbname postgres \
  --command "SELECT 1 FROM pg_database WHERE datname='$target_db'")"
if [[ "$exists" == "1" ]]; then
  echo "ERROR: target database already exists; refusing to overwrite it."
  exit 1
fi

infra_compose exec -T postgres \
  createdb --username "${POSTGRES_USER:-vss_app}" "$target_db"
infra_compose exec -T postgres \
  pg_restore \
    --exit-on-error \
    --no-owner \
    --username "${POSTGRES_USER:-vss_app}" \
    --dbname "$target_db" \
  < "$backup_dir/postgres/vss_control.dump"

infra_compose exec -T postgres \
  psql -At \
    --username "${POSTGRES_USER:-vss_app}" \
    --dbname "$target_db" \
    --command "SELECT version FROM schema_migrations ORDER BY version;"

echo "PostgreSQL restore validation PASS in isolated database $target_db."
echo "The validation database is preserved for operator review."
