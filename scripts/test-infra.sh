#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/infra-lib.sh"

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"

test_id="infra-smoke-$(date -u +%Y%m%dT%H%M%SZ)"

infra_compose exec -T postgres \
  psql --set ON_ERROR_STOP=1 \
    --username "${POSTGRES_USER:-vss_app}" \
    --dbname "${POSTGRES_DB:-vss_control}" \
    --command "SELECT version FROM schema_migrations WHERE version='001_control_plane';" \
  | grep -q 001_control_plane

infra_compose exec -T redis sh -ec \
  'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli SET infra:smoke "$1" EX 120 >/dev/null
   REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli GET infra:smoke' \
  sh "$test_id" \
  | grep -q "$test_id"

printf '%s\n' "$test_id" \
  | infra_compose exec -T kafka \
      /opt/kafka/bin/kafka-console-producer.sh \
      --bootstrap-server kafka:9092 \
      --topic vss.system.test

infra_compose exec -T kafka \
  /opt/kafka/bin/kafka-console-consumer.sh \
    --bootstrap-server kafka:9092 \
    --topic vss.system.test \
    --from-beginning \
    --max-messages 1 \
    --timeout-ms 15000 \
  | grep -q "$test_id"

vector_payload='{"@timestamp":"2026-01-01T00:00:00Z","schema_version":"1","store_id":"smoke","camera_id":"smoke","model_id":"Cosmos-Embed1-448p-anomaly-detection","model_version":"smoke","start_time":"2026-01-01T00:00:00Z","end_time":"2026-01-01T00:00:10Z","embedding":[1.0,0.0],"payload":{"test":true}}'
mapping_dims="$(curl --fail --silent http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/vss-video-embeddings-000001/_mapping | jq -r '.. | objects | select(has("embedding")) | .embedding.dims' | head -n1)"
[[ "$mapping_dims" == "768" ]]

curl --fail --silent \
  -X PUT "http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/infra-vector-smoke" \
  -H 'Content-Type: application/json' \
  --data-binary '{"mappings":{"properties":{"embedding":{"type":"dense_vector","dims":2,"index":true,"similarity":"cosine"}}}}' >/dev/null

curl --fail --silent \
  -X POST "http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/infra-vector-smoke/_doc?refresh=true" \
  -H 'Content-Type: application/json' \
  --data-binary "$vector_payload" >/dev/null

hits="$(curl --fail --silent \
  -X POST "http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/infra-vector-smoke/_search" \
  -H 'Content-Type: application/json' \
  --data-binary '{"knn":{"field":"embedding","query_vector":[1.0,0.0],"k":1,"num_candidates":1}}' \
  | jq -r '.hits.total.value')"
[[ "$hits" == "1" ]]

curl --fail --silent -X DELETE \
  "http://127.0.0.1:${ELASTICSEARCH_PORT:-9200}/infra-vector-smoke" >/dev/null

echo "Infrastructure smoke test PASS: PostgreSQL, Redis, Kafka and Elasticsearch vector search."
