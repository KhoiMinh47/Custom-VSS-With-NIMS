# PHASE-09 HANDOFF

## Result

PARTIAL

The Phase 09 technical path is complete for `cam-01`: stable RT-CV JSON
metadata is converted into queryable retail traffic events, persisted through
Kafka and Elasticsearch, and displayed in a minimal dashboard. Phase 08 was
explicitly deferred by the user and remains incomplete/unapproved.

The result is `PARTIAL` because the normalized ROI/line map is provisional and
there is no business-annotated real-camera ground truth for counting MAE/MAPE,
queue error or event precision/recall. Synthetic ground truth proves rule
logic, not real-camera accuracy or ten-camera capacity.

## Scope completed

- Directional line crossing and people entry/exit counts.
- ROI entry/exit and live occupancy.
- Dwell threshold and restricted-zone candidate events.
- Queue threshold/clear events with length and wait evidence.
- 16×9 metadata-derived heatmap.
- Stable versioned event schema with UTC, store/camera, source/analytics model
  versions, config version, deterministic ID and RT-CV metadata evidence.
- Idempotent frame handling, Elasticsearch upsert, Kafka event publication and
  DLQ fallback.
- Versioned normalized config API and minimal count/queue/heatmap dashboard.
- Health checks, Prometheus metrics, structured secret-safe logs and tests.
- No VLM/LLM/RT-Embed and no additional GPU reservation.

## Files created

- `services/behavior-analytics/contracts.py`
- `services/behavior-analytics/engine.py`
- `services/behavior-analytics/service.py`
- `services/behavior-analytics/README.md`
- `services/heatmap/heatmap.py`
- `services/heatmap/README.md`
- `config/analytics/cam-01.behavior.yaml`
- `schemas/jsonschema/behavior-event.schema.json`
- `deploy/compose/behavior-analytics.compose.yml`
- `scripts/behavior-lib.sh`
- `scripts/start-behavior-analytics.sh`
- `scripts/healthcheck-behavior-analytics.sh`
- `scripts/test-behavior-analytics.sh`
- `scripts/evaluate-behavior-analytics.py`
- `scripts/stop-behavior-analytics.sh`
- `tests/unit/test_behavior_analytics.py`
- `docs/evals/behavior-analytics/README.md`
- `docs/evals/behavior-analytics/error-analysis.md`

## Files modified

- `Makefile`
- `README.md`
- `config/elasticsearch/component-vss-common.json`
- `config/elasticsearch/template-events.json`
- `config/elasticsearch/bootstrap.sh`
- `config/prometheus/prometheus.yml`
- `PROJECT_STATE.md`
- `phase.md`

## Commands executed

```text
docker/disk/GPU non-destructive inventory
docker compose ... config --quiet
make behavior-start
make behavior-health
make behavior-test
make rtcv-health
make rtcv-test
pytest -q
Prometheus target and endpoint HTTP checks
```

No prune, image/model/cache deletion, global package installation or model
download occurred.

## Services/images/models affected

- New CPU-only container: `ntc-vss-phase09-behavior-analytics`.
- Image:
  `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1`
  digest
  `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`.
- RT-DETR FP16 and NvDCF remain unchanged and are the only Phase 09 metadata
  source.
- No VLM, LLM or RT-Embed service was started.

## Validation evidence

- `artifacts/logs/phase09-behavior-smoke.txt`
- `artifacts/logs/phase09-dashboard.html`
- `artifacts/logs/phase09-state.json`
- `artifacts/logs/phase09-config.json`
- `artifacts/evals/phase09/evaluation-report.json`
- `artifacts/evals/phase09/synthetic-frames.jsonl`
- `artifacts/evals/phase09/synthetic-events.jsonl`

## Metrics

- Unit/full project tests: 37 passed.
- Synthetic event coverage: 10/10 event types, 100%.
- Kafka → service → Elasticsearch: PASS.
- Persisted events at final check: 144 total; 36 live/non-evaluation and 108
  explicitly labeled evaluation events.
- Runtime after clean restart/gate: 8 frames, 20 events, zero consume,
  Elasticsearch and Kafka publish errors.
- Config API update/restart reuse: PASS, active config version 2.
- Prometheus target `phase09-behavior-analytics`: up.
- Dashboard/state/config endpoints: HTTP 200.
- GPU remained RT-CV-only; observed 9,774/48,935 MiB and 8% utilization.

## Known issues

- ROI/line/queue/restricted-zone mapping is provisional.
- No real-camera annotation set; accuracy KPI remains `PARTIAL`.
- Phase 08 scale/capacity evidence is absent by explicit user deferral.
- Phase 09 currently consumes one stable `cam-01` metadata stream and is not
  evidence of ten-camera physical behavior analytics.
- In-memory counters/heatmap reset on service restart; persisted events remain
  idempotent in Elasticsearch. Durable aggregate checkpointing is future work.

## Rollback

- `make behavior-stop` stops only the Phase 09 service and preserves images,
  Kafka, Elasticsearch and runtime config.
- Phase 07 RT-CV/video continues independently.
- The Elasticsearch mapping extension is additive and repeatable.
- No raw video data is changed or removed.

## Exact next phase

PHASE-10, only after explicit user review/approval of this `PARTIAL` handoff.
PHASE-08 remains deferred, not completed.

## Approval required

YES
