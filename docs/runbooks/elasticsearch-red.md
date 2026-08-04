# Elasticsearch red or unavailable

## Symptom

Search, caption, summary or event APIs report persistence errors.

## Detection

- Query `/_cluster/health` through loopback.
- Review disk usage and shard allocation.
- Check the Phase 15 Elasticsearch service tile and Prometheus targets.

## Immediate mitigation

Preserve queues and stop new non-critical indexing. Do not delete indices,
volumes or project data. Take a project-local snapshot before any migration.

## Root-cause checklist

- Disk watermark.
- Unassigned primary shard.
- Mapping rejection.
- JVM pressure or host filesystem permissions.

## Recovery validation

Cluster reaches at least yellow, repeatable bootstrap succeeds, and a
read/write smoke document passes in the intended index.

## Data-loss assessment

Compare queue checkpoints with indexed document counts and snapshot metadata.
Use the documented restore workflow; never recreate an index silently.
