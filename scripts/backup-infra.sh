#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/infra-lib.sh"

backup_id="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
backup_dir="$PROJECT_ROOT/runtime/backups/$backup_id"
mkdir -p "$backup_dir/postgres" "$backup_dir/redis" "$backup_dir/minio"

infra_compose exec -T postgres \
  pg_dump \
    --format=custom \
    --username "${POSTGRES_USER:-vss_app}" \
    --dbname "${POSTGRES_DB:-vss_control}" \
  > "$backup_dir/postgres/vss_control.dump"

infra_compose exec -T redis sh -ec \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning SAVE >/dev/null'
infra_compose exec -T redis cat /data/dump.rdb \
  > "$backup_dir/redis/dump.rdb"

snapshot_name="snapshot-${backup_id,,}"
curl --fail --silent \
  -X PUT "http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/_snapshot/project-local" \
  -H 'Content-Type: application/json' \
  --data-binary '{"type":"fs","settings":{"location":"/mnt/snapshots","compress":true}}' >/dev/null
curl --fail --silent \
  -X PUT "http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/_snapshot/project-local/$snapshot_name?wait_for_completion=true" \
  -H 'Content-Type: application/json' \
  --data-binary '{"include_global_state":false}' \
  > "$backup_dir/elasticsearch-snapshot-result.json"

infra_compose run --rm --no-deps \
  -v "$backup_dir/minio:/backup" \
  --entrypoint /bin/sh minio-init \
  -ec 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
       mc mirror --overwrite local/vss-artifacts /backup/vss-artifacts'

sha256sum \
  "$backup_dir/postgres/vss_control.dump" \
  "$backup_dir/redis/dump.rdb" \
  "$backup_dir/elasticsearch-snapshot-result.json" \
  > "$backup_dir/SHA256SUMS"

echo "$backup_dir"
