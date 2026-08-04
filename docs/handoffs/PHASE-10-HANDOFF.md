# PHASE-10 HANDOFF

## Result

PARTIAL

All Phase 10 technical exit criteria passed on `cam-01` with actual Cosmos3
inference: a Phase 09 candidate was retained, mapped to a deterministic
incident, resolved to a VIOS pre/post-roll clip, prepared for the VLM,
verified, persisted and displayed in the review UI. VLM outage durability,
cache reuse, retry/DLQ, feedback, confusion-matrix reporting, latency reporting
and the serialized no-OOM GPU profile were exercised.

The overall result remains `PARTIAL` because the evaluation has only one
operator feedback label and inherits the provisional Phase 09 ROI. This proves
the evaluation mechanism, not business precision/recall. Phase 08 remains
deferred by explicit user direction.

## Scope completed

- CPU candidate-incident service consuming non-evaluation
  `vss.behavior.events`.
- Stable incident IDs and versioned contracts carrying store, camera, UTC,
  source model and verification model data.
- Four-second pre-roll and post-roll selection through the VIOS time-range API.
- CPU media-preparation companion converting only selected clips to H.264
  1280x720 for Cosmos3.
- Event-driven Cosmos3 Nano Reasoner verification with structured
  `confirmed`, `rejected`, or `uncertain` output.
- Three-attempt retry, durable incident retention, `uncertain` fallback and
  `vss.dlq` publication.
- Elasticsearch incident/verified-alert persistence and Kafka verified-event
  publication.
- Review dashboard, selected-clip playback, feedback endpoint, confusion
  matrix and latency report.
- Local admission lease preventing RT-CV/Cosmos3 overlap.
- Health checks, metrics, secret-safe structured logs, tests and evidence.
- No continuous RT-VLM and no raw-storage mount in Phase 10 containers.

## Files created

- `services/incidents/{contracts.py,media.py,media_preparation.py,service.py,README.md}`
- `services/alert-verification/{contracts.py,vlm_client.py,service.py,README.md}`
- `services/gpu-admission-controller/admission.py`
- `config/prompts/alert-verification/verification.json`
- `config/elasticsearch/mapping-phase10-incidents.json`
- `schemas/jsonschema/{incident.schema.json,verified-alert.schema.json}`
- `deploy/compose/phase10.compose.yml`
- `scripts/{phase10-lib.sh,start-phase10.sh,healthcheck-phase10.sh}`
- `scripts/{start-phase10-vlm.sh,stop-phase10-vlm.sh,stop-phase10.sh}`
- `scripts/{test-phase10.sh,capture-phase10-evidence.sh}`
- `tests/unit/test_phase10.py`
- `docs/evals/alert-verification/{README.md,error-analysis.md}`

## Files modified

- `Makefile`
- `README.md`
- `PROJECT_STATE.md`
- `phase.md`
- `scripts/bootstrap-project.sh`
- `config/elasticsearch/component-vss-common.json`
- `config/elasticsearch/bootstrap.sh`
- `config/prometheus/prometheus.yml`
- `deploy/overlays/single-gpu-poc.compose.yml`

## Runtime and model profile

- CPU services:
  `ntc-vss-phase10-incidents`,
  `ntc-vss-phase10-media-preparation`, and
  `ntc-vss-phase10-alert-verification`.
- Incident/verifier CPU image:
  `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1` with digest
  `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`.
- Media-preparation reuses project overlay
  `ntc-vss-retail-poc/rtcv-relay:3.2.1-phase07`, local image ID
  `sha256:7829aa1d7de080a53279dbd52b0ff10f487a58085ede9ca2ceae7a3bec1f2314`.
- Cosmos3 image:
  `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` with digest
  `sha256:19add3edaaa77c4030c75eb27d30939c29ca93807bb7af10a1876f05d520026c`.
- Model: `nvidia/cosmos3-nano-reasoner`; approved cached profile
  `e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3`.
- The NIM reused cached artifacts; logs recorded cached-copy reuse and no
  model/profile download.
- `NIM_GPU_MEMORY_UTILIZATION=0.75`, maximum sequence count 1 and maximum
  batched tokens 4096.
- Observed aggregate GPU use reached 43,587/48,935 MiB without OOM.
- This is an experimental serialized profile on RTX PRO 5000 Blackwell; it is
  not an NVIDIA-validated topology.

Cosmos3 is intentionally stopped and its lease revoked at handoff. RT-CV is
restored and healthy. Phase 10 CPU services remain running so candidates are
durably selected and queued. The post-validation Elasticsearch snapshot at
2026-07-29T07:06:49Z contained 20 `queued_for_verification` documents; this
count may grow while live Phase 09 candidates arrive before the next admitted
VLM window.

## Validation performed

```text
make phase10-config
make phase10-start
make phase10-health
make phase10-admit
make phase10-vlm-start
make phase10-test
make phase10-evidence
make phase10-vlm-stop
make rtcv-start
make rtcv-health
make rtcv-test
make behavior-health
make video-health
pytest -q
Prometheus target, HTTP endpoint, mount-isolation and credential-log checks
```

No prune, image/model/cache deletion, global package installation or
unapproved profile download occurred.

## Evidence

- `artifacts/logs/phase10-smoke.txt`
- `artifacts/logs/phase10-dashboard.html`
- `artifacts/logs/phase10-gpu-profile.txt`
- `artifacts/logs/phase10-cosmos3-cache-and-inference.txt`
- `artifacts/logs/phase10-container-mounts.txt`
- `artifacts/evals/phase10/source-behavior-candidate.json`
- `artifacts/evals/phase10/incident-submit.json`
- `artifacts/evals/phase10/incident-state-final.json`
- `artifacts/evals/phase10/verifier-state-final.json`
- `artifacts/evals/phase10/evaluation-report-final.json`
- `artifacts/evals/phase10/verified-alerts-final.json`
- `artifacts/evals/phase10/outage-candidate.json`
- `artifacts/evals/phase10/outage-incident-submit.json`

## Measured result

- Actual successful Cosmos3 verdicts: two `rejected`.
- Unique verified-alert documents in evaluation: three, including retained
  `uncertain` audit evidence.
- Latency samples: count 3, p50 3,451 ms, min 390 ms, max 11,243 ms.
- Human feedback: one `rejected->rejected` label.
- Elasticsearch snapshot at 2026-07-29T07:06:49Z: 23 incident documents,
  including 20 queued; three unique verified-alert documents.
- Confusion-matrix endpoint: HTTP 200 and populated.
- Dashboard, alerts, evaluation, incident state and metrics: HTTP 200.
- Prometheus Phase 10 incident and alert-verification targets: up.
- Full project tests: 48 passed; Phase 10 unit tests: 11 passed.
- VLM outage test: a new candidate remained persisted as
  `queued_for_verification`; live video remained healthy.
- Secret scans and raw-plane mount isolation: PASS.

## Issues found and resolved

1. Cosmos3 rejects source clips with a dimension above 2048. Three initial
   2560x1440 attempts exhausted retries and remain auditable as `uncertain`
   plus DLQ. A CPU companion now prepares only the VIOS-selected clip as H.264
   1280x720. Subsequent inference returned HTTP 200.
2. `NIM_DISABLE_MODEL_DOWNLOAD=true` also prevented required workspace
   materialization. It was removed; the NIM then reused cached artifacts, as
   recorded in the cache log.
3. The default 0.90 NIM memory reservation did not fit beside the video plane.
   The approved serialized profile uses 0.75 and does not overlap RT-CV.
4. The verifier initially used Kafka `latest`, which could skip an outage
   backlog. It now uses `earliest`; deterministic Elasticsearch upserts keep
   replay repeatable.
5. Existing strict incident mappings lacked required event fields. Bootstrap
   now applies an additive repeatable mapping update; no index/data was
   deleted.

## Known limits

- Accuracy is not established: one label is insufficient for precision,
  recall or false-alert claims.
- Phase 09 ROI calibration and real-camera ground truth remain provisional.
- Phase 08 physical multi-camera capacity evidence is absent by explicit
  deferral.
- Only `cam-01` is in this Phase 10 proof.
- RT-CV and Cosmos3 must remain serialized; admission is a startup gate, and
  running Cosmos3 leaves less than 15% GPU memory headroom.
- Pending candidates require a later admitted VLM window; they are not lost
  while Cosmos3 is stopped.
- Initial DLQ entries are intentionally retained as audit evidence.

## Rollback

- `make phase10-vlm-stop` stops Cosmos3 and revokes the local lease while
  preserving its cache.
- `make phase10-stop` stops Phase 10 CPU services and preserves clips, Kafka,
  Elasticsearch, evidence, images and caches.
- Phase 07 video/RT-CV and Phase 09 behavior services remain independent.
- Elasticsearch changes are additive and repeatable.
- No raw recording is modified or removed.

## Exact next phase

PHASE-11 only after explicit user review and approval of this `PARTIAL`
handoff. PHASE-08 remains deferred, incomplete and unapproved.

## Approval required

YES
