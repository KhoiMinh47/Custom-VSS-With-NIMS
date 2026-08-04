#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/phase11-lib.sh"

"$PROJECT_ROOT/scripts/healthcheck-infra.sh"
"$PROJECT_ROOT/scripts/healthcheck-video-management.sh"
mkdir -p \
  "$PROJECT_ROOT/runtime/gpu-admission" \
  "$PROJECT_ROOT/artifacts/benchmarks/rt-vlm-alert" \
  "$PROJECT_ROOT/artifacts/logs"

for specification in \
  "vss.rt-vlm.captions 1 604800000" \
  "vss.rt-vlm.incidents 1 2592000000" \
  "vss.rt-vlm.errors 1 7776000000"; do
  read -r topic partitions retention <<<"$specification"
  docker exec ntc-vss-retail-poc-kafka-1 \
    /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server kafka:9092 \
    --create --if-not-exists \
    --topic "$topic" --partitions "$partitions" --replication-factor 1 >/dev/null
  docker exec ntc-vss-retail-poc-kafka-1 \
    /opt/kafka/bin/kafka-configs.sh \
    --bootstrap-server kafka:9092 \
    --entity-type topics --entity-name "$topic" \
    --alter --add-config "retention.ms=$retention" >/dev/null
done

ELASTICSEARCH_URL=http://127.0.0.1:9200 \
  CONFIG_DIR="$PROJECT_ROOT/config/elasticsearch" \
  sh "$PROJECT_ROOT/config/elasticsearch/bootstrap.sh"
phase11_compose config --quiet
phase11_start_resource_monitor
phase11_compose up -d rt-vlm-results
curl --fail --silent --show-error -X POST \
  http://127.0.0.1:9090/-/reload >/dev/null
"$PROJECT_ROOT/scripts/healthcheck-phase11.sh"
