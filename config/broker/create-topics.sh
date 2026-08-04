#!/bin/bash
set -euo pipefail

BOOTSTRAP_SERVER="${KAFKA_BOOTSTRAP_SERVER:-kafka:9092}"
TOPICS_FILE="${TOPICS_FILE:-/config/topics.txt}"

while IFS='|' read -r topic partitions retention_ms; do
  case "$topic" in
    ""|\#*) continue ;;
  esac

  /opt/kafka/bin/kafka-topics.sh \
    --bootstrap-server "$BOOTSTRAP_SERVER" \
    --create \
    --if-not-exists \
    --topic "$topic" \
    --partitions "$partitions" \
    --replication-factor 1

  /opt/kafka/bin/kafka-configs.sh \
    --bootstrap-server "$BOOTSTRAP_SERVER" \
    --entity-type topics \
    --entity-name "$topic" \
    --alter \
    --add-config "retention.ms=$retention_ms"
done < "$TOPICS_FILE"

/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP_SERVER" --list
