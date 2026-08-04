#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/infra-lib.sh"

test_id="persistence-$(date -u +%Y%m%dT%H%M%SZ)"

infra_compose exec -T postgres \
  psql --set ON_ERROR_STOP=1 \
    --username "${POSTGRES_USER:-vss_app}" \
    --dbname "${POSTGRES_DB:-vss_control}" \
    --command "INSERT INTO feature_flags(name, enabled, config)
               VALUES ('$test_id', true, '{\"source\":\"phase05\"}')
               ON CONFLICT (name) DO UPDATE SET enabled=EXCLUDED.enabled;" >/dev/null

infra_compose exec -T redis sh -ec \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli SET "$1" "$2" >/dev/null
   REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli SAVE >/dev/null' \
  sh "infra:$test_id" "$test_id"

curl --fail --silent \
  -X POST "http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/vss-system-events/_doc/$test_id?refresh=true" \
  -H 'Content-Type: application/json' \
  --data-binary "{\"@timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"schema_version\":\"1\",\"store_id\":\"poc-store-01\",\"camera_id\":\"system\",\"event_type\":\"infra_persistence_test\",\"correlation_id\":\"$test_id\",\"payload\":{\"test_id\":\"$test_id\"}}" >/dev/null

printf '%s\n' "$test_id" > "$PROJECT_ROOT/runtime/persistence-marker.txt"
infra_compose run --rm --no-deps \
  -v "$PROJECT_ROOT/runtime/persistence-marker.txt:/tmp/persistence-marker.txt:ro" \
  --entrypoint /bin/sh minio-init \
  -ec 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
       mc cp /tmp/persistence-marker.txt "local/vss-artifacts/persistence/'"$test_id"'.txt" >/dev/null'

infra_compose stop
infra_compose up -d
"$PROJECT_ROOT/scripts/healthcheck-infra.sh"

infra_compose exec -T postgres \
  psql -At \
    --username "${POSTGRES_USER:-vss_app}" \
    --dbname "${POSTGRES_DB:-vss_control}" \
    --command "SELECT enabled FROM feature_flags WHERE name='$test_id';" \
  | grep -qx t

infra_compose exec -T redis sh -ec \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli GET "$1"' \
  sh "infra:$test_id" \
  | grep -qx "$test_id"

curl --fail --silent \
  "http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/vss-system-events/_doc/$test_id" \
  | jq -e '._source.payload.test_id == "'"$test_id"'"' >/dev/null

infra_compose run --rm --no-deps \
  --entrypoint /bin/sh minio-init \
  -ec 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
       mc cat "local/vss-artifacts/persistence/'"$test_id"'.txt"' \
  | grep -qx "$test_id"

echo "Infrastructure restart persistence PASS for $test_id."
