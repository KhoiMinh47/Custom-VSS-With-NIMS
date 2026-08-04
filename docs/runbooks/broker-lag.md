# Kafka broker lag

## Symptom

Event dashboards become stale while camera/video services remain healthy.

## Detection

- Check Prometheus broker targets and Phase 09 input age.
- Inspect consumer group lag with the pinned Kafka container tooling.
- Check `vss.dlq` size and oldest message age.

## Immediate mitigation

Do not restart the video plane. Pause lower-priority batch producers if lag is
growing, then restart only the affected idempotent consumer.

## Root-cause checklist

- Broker disk pressure and partition health.
- Consumer errors/rebalance loop.
- Elasticsearch latency causing downstream backpressure.
- Duplicate or poison message entering retries.

## Recovery validation

Lag must trend to zero, consumers must keep stable group membership and event
timestamps must remain ordered.

## Data-loss assessment

Compare producer offsets, committed offsets and DLQ records. Never purge Kafka
data as a recovery shortcut.
