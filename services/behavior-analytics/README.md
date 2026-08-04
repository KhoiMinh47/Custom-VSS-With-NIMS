# Phase 09 behavior analytics

This project overlay consumes the stable JSON `vss.rt-cv.frames` topic from
Phase 07. It never reads or mounts raw video storage. The service runs CPU-only
inside the digest-pinned VSS 3.2.1 behavior analytics image.

Implemented rules for `cam-01`:

- line crossing and directional entry/exit count;
- normalized ROI entry/exit and occupancy;
- dwell threshold and restricted-zone candidates;
- queue length and estimated wait evidence;
- metadata-derived 16×9 heatmap;
- deterministic event IDs, Kafka publication, Elasticsearch persistence and
  DLQ fallback.

Run:

```bash
make behavior-config
make behavior-start
make behavior-health
make behavior-test
```

Endpoints:

- Dashboard: `http://127.0.0.1:39110/dashboard`
- State: `http://127.0.0.1:39110/api/v1/state`
- Events: `http://127.0.0.1:39110/api/v1/events`
- Versioned config: `GET/PUT http://127.0.0.1:39110/api/v1/config`
- Health: `/health/live`, `/health/ready`
- Prometheus: `/metrics`

`PUT /api/v1/config` accepts JSON only, requires `config_version` to increment
exactly by one, preserves `store_id`/`camera_id`, validates normalized
coordinates and writes the override under `runtime/behavior-analytics/`.
Restore the committed config by stopping the service, moving the runtime
override aside, and starting the service again.

The committed ROI/line mapping is provisional. Synthetic evaluation proves
rule behavior and the external Kafka/Elasticsearch path; it is not evidence of
real-camera counting or queue accuracy.
