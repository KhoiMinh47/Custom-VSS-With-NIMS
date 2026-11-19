# ADR-008: Loopback-safe Prometheus relay for the Phase 15 API

## Status

Proposed on 2026-11-19. **Not approved and not implemented.** The
`phase15-unified-api` Prometheus target remains a pending Phase 15 gate.

## Context

`phase15-api` runs with `network_mode: host` and binds only to
`127.0.0.1:39510`. Its `/metrics` endpoint works from the host, but the
Prometheus container on the `ntc-vss-retail-infra` bridge network still
targets `phase15-api:8080`. That DNS name and port belonged to the old
bridge deployment, so the scrape cannot succeed.

Constraints from `AGENTS.md`, the Phase 15 handoff and the recovery runbook:

- do not bind Phase 15 to `0.0.0.0` or broaden the trusted-loopback bind;
- do not weaken trusted-loopback access or add permissive CORS;
- do not pull new images without inventory and pinning;
- stop and rollback must preserve data.

## Options considered

| Option | Result |
| --- | --- |
| Bind the API to `0.0.0.0` or the Docker bridge gateway | Rejected: it broadens the trusted-loopback admin surface. |
| Run Prometheus with `network_mode: host` | Rejected: it breaks service-DNS targets for every other job and moves Prometheus off the isolated infra network. |
| Pushgateway or node-exporter textfile collector | Rejected for now: each needs a new image and still needs a network path. |
| **Unix-socket metrics relay** | **Proposed.** No new TCP listener on the host and no change to the loopback bind. |

## Proposed design

1. **Metrics-only Unix socket in `phase15-api`.** Next to its existing TCP
   listener, the API serves `GET /metrics` on
   `/runtime/phase15/metrics/api.sock`. This maps to the host directory
   `runtime/phase15/metrics/`, which the existing `runtime/phase15` bind mount
   already covers. Every other method or path on the socket returns `404`. The
   socket file is created with mode `0660`, and the server removes a stale
   socket only if it is a socket file it owns.
2. **`phase15-metrics-relay` container.** A small stdlib-Python relay in
   `deploy/compose/phase15.compose.yml`:
   - reuses the already-pulled, digest-pinned
     `vss-behavior-analytics:3.2.1@sha256:f3fd84f9…` image that `phase15-api`
     uses, so nothing new is pulled;
   - joins only the external `ntc-vss-retail-infra` network and publishes
     **no** host port;
   - mounts only `runtime/phase15/metrics/` read-only, with no Docker socket,
     GPU device, raw video, secrets or model cache;
   - listens on `:8080` inside the infra network and forwards only `GET /metrics`
     to the Unix socket. It has a bounded response size and timeout, rejects
     any other request, and emits structured JSON logs;
   - exposes `/health/live` for the Compose health check.
3. **Prometheus target.** Change the `phase15-unified-api` job to
   `phase15-metrics-relay:8080`. No other job changes.

## Security properties

- The host listener set is unchanged: the API stays on `127.0.0.1:39510` only.
- Only containers on the infra bridge network can read the metrics.
- The metrics exposition contains counters and gauges only, with no tokens,
  camera credentials, RTSP URLs or user content. Implementation must add a
  unit check that rejects secret-like content in the exposition.
- The relay cannot mutate anything because it has no write path.

## Rollback

Stop the relay with `docker compose ... stop phase15-metrics-relay`, never
`down -v`. Then point the Prometheus job back at the pending target and reload
it through `--web.enable-lifecycle`. The socket directory is harmless when
unused. No data, image or volume is removed.

## Validation required after approval

- `ss -ltn` shows no new host TCP listener;
- `curl http://127.0.0.1:39510/metrics` is unchanged;
- the Prometheus target `phase15-unified-api` reports `up == 1`;
- a non-`GET /metrics` request through the relay is rejected;
- unit tests cover the socket server, the relay allowlist and secret scanning.

Until these checks are run, the gate stays `PARTIAL`, and unit mocks must not be
cited as scrape evidence.
