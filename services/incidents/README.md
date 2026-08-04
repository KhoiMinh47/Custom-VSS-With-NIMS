# Phase 10 incident service

This CPU-only service consumes non-evaluation candidates from
`vss.behavior.events`, creates a deterministic incident, and asks the VIOS
time-range API for a short MP4 with four seconds of pre-roll and post-roll.
The resulting selected clip is hashed, persisted under `runtime/incidents`,
and published to `vss.incidents.candidate`.

It never mounts or scans `runtime/raw-video`. Raw recording remains owned by
the Phase 06 video plane; this service can only receive prepared media through
the VIOS API. A clip preparation failure leaves the Kafka offset uncommitted so
the candidate remains retryable.

Endpoints:

- `http://localhost:39121/health/live`
- `http://localhost:39121/health/ready`
- `http://localhost:39121/api/v1/state`
- `http://localhost:39121/metrics`
- `POST http://localhost:39121/api/v1/candidates` for controlled replay of a
  real behavior-event contract during evaluation.
