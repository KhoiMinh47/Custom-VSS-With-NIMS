# ADR-006: Infrastructure data plane

- Status: Accepted for PoC
- Date: 2026-07-23

## Decision

Use PostgreSQL for control-plane state, Elasticsearch for event and vector
search, Apache Kafka in KRaft mode as the primary event broker, Redis for
control/cache state, and MinIO for clip/snapshot-compatible object storage.
Prometheus and Grafana provide the Phase 05 observability baseline.

All persistent data is bind-mounted below `runtime/`. Host ports bind to
`127.0.0.1` by default. Internal application services will use the Compose
network and service DNS names.

## Rationale

Kafka preserves compatibility with the target NVIDIA streaming architecture.
Redis remains available for short-lived control state but is not treated as the
canonical event log. S3-compatible object storage keeps the media interface
portable without coupling analytics directly to raw-video storage.

## Consequences

- Single-node services are appropriate only for this one-store PoC.
- Elasticsearch security is disabled only inside the local trusted-network PoC
  boundary; external exposure requires the later security phase.
- Kafka replication factor is one, so host loss is not tolerated.
- Production pilot sizing requires HA, TLS and authentication.

## Rollback

Stop the Compose services with `scripts/stop-infra.sh`. This preserves all
images and project-local runtime data. Revert the Compose/config files to the
previous reviewed revision if configuration rollback is required.
