# PHASE-11 HANDOFF

## Result

PARTIAL

The user accepted this `PARTIAL` result and its hybrid-default recommendation
on 2026-07-29. This acceptance does not convert the missing accuracy evidence
into a PASS.

All Phase 11 technical exit criteria passed on one physical source,
`cam-01`. The pinned NVIDIA VSS RT-VLM 3.2.1 service read the live,
credential-free logical H.264 relay, sampled bounded chunks, called the cached
Cosmos3 NIM, published vendor `VisionLLM` protobuf, and produced queryable
structured direct-alert records and a review UI.

The result remains `PARTIAL` because there are no operator labels for the
direct results. Accuracy and false-alert rate cannot be claimed. Phase 08
remains deferred by explicit user direction.

## Direct use case

- Use case: visible person presence.
- Scope: `store-001` / `cam-01` only.
- Source: `rtsp://rtsp-relay:39554/Streaming/Channels/102`, an internal
  credential-free relay path. At the original benchmark it was fed from the
  VIOS main-stream fallback; from 2026-07-30 it prefers the recovered physical
  H.264 1280x720 channel-102 AI substream.
- Chunk: 8 seconds, no overlap.
- Sampling: five fixed frames per chunk.
- Model: `nvidia/cosmos3-nano-reasoner`, `bf16-final`.
- Output: `confirmed`, `rejected`, or `uncertain` with confidence/reason.
- RT-VLM input is live video only. It does not consume RT-CV metadata,
  Phase 09 candidates or raw storage.

## Scope completed

- Versioned direct prompt and JSON result contract.
- Pinned vendor RT-VLM deployment for one camera.
- Cosmos3 external-NIM mode with one VLM process and one-camera admission.
- Vendor protobuf Kafka topics and CPU result collector.
- Elasticsearch persistence with deterministic direct-alert IDs.
- State, alerts, feedback, evaluation, comparison and Prometheus APIs.
- Minimal review UI and hybrid-versus-direct report.
- GPU, latency, frame and token benchmark evidence.
- Safe direct start/stop with RT-CV serialization and automatic restoration.
- Approved Phase 10 hybrid-default/Phase 11 direct-opt-in runtime policy.
- Secret scans, raw-plane isolation, health checks and tests.

## Files created

- `services/rt-vlm-alert/contracts.py`
- `services/rt-vlm-alert/collector.py`
- `services/rt-vlm-alert/README.md`
- `config/prompts/rt-vlm-alert/person-presence.json`
- `config/elasticsearch/mapping-phase11-direct-alerts.json`
- `schemas/jsonschema/direct-rt-vlm-alert.schema.json`
- `deploy/compose/phase11.compose.yml`
- `scripts/phase11-lib.sh`
- `scripts/start-phase11.sh`
- `scripts/healthcheck-phase11.sh`
- `scripts/register-phase11-stream.py`
- `scripts/start-phase11-direct.sh`
- `scripts/stop-phase11-direct.sh`
- `scripts/stop-phase11.sh`
- `scripts/test-phase11.sh`
- `scripts/benchmark-phase11.sh`
- `scripts/capture-phase11-evidence.sh`
- `scripts/start-default-alerting.sh`
- `scripts/healthcheck-default-alerting.sh`
- `tests/unit/test_phase11.py`
- `tests/unit/test_alert_routing_policy.py`
- `docs/evals/rt-vlm-alert/README.md`
- `docs/evals/rt-vlm-alert/error-analysis.md`
- `docs/reports/hybrid-vs-direct-vlm.md`

## Files modified

- `Makefile`
- `README.md`
- `PROJECT_STATE.md`
- `phase.md`
- `scripts/bootstrap-project.sh`
- `scripts/rtcv-lib.sh`
- `scripts/test-rtcv.sh`
- `services/gpu-admission-controller/admission.py`
- `config/broker/topics.txt`
- `config/elasticsearch/bootstrap.sh`
- `config/prometheus/prometheus.yml`
- `config/runtime/single-gpu-poc.yaml`

## Images, model and admission

- VSS RT-VLM image:
  `nvcr.io/nvidia/vss-core/vss-rt-vlm:3.2.1` with digest
  `sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504`.
- Cosmos3 image:
  `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` with digest
  `sha256:19add3edaaa77c4030c75eb27d30939c29ca93807bb7af10a1876f05d520026c`.
- Cached profile:
  `e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3`.
- Cosmos3 reused cached artifacts; logs contain cached-copy reuse and HTTP 200
  inference evidence.
- Direct admission is denied while `ntc-vss-phase07-rtcv` runs. The benchmark
  stops only RT-CV/metadata, preserves the live relay/video plane, grants a
  `direct_rt_vlm` lease, and restores RT-CV afterward.
- The CPU protobuf collector uses the same pinned RT-VLM image without a GPU
  reservation. RT-CV admission excludes only this exact collector container,
  not the actual RT-VLM service.

This remains an experimental serialized profile on RTX PRO 5000 Blackwell. It
is not an NVIDIA-validated topology.

## Clean benchmark

- Actual clean Cosmos3 responses: 2.
- Verdicts: one `rejected`, one `confirmed`.
- Chunk duration: 8 seconds.
- Frame count: 5 for both results.
- Latency: 14,739 ms and 7,981 ms.
- VLM latency: 8,415 ms and 1,607 ms.
- Input tokens: 9,732 total.
- Output tokens: 56 total.
- Peak aggregate GPU memory: 46,348/48,935 MiB.
- Peak sampled GPU utilization: 100%.
- Peak sampled power: 303.67 W.
- OOM: none.
- Operator labels: 0; accuracy/false-alert status is
  `insufficient_labels`.

Phase 10 hybrid comparison at the same handoff has three latency samples,
p50 3,451 ms, max 11,243 ms and one operator label. These small, differently
triggered samples are runtime evidence, not a statistical accuracy comparison.

## Commands and validation

```text
non-destructive Docker/disk/GPU inventory
make phase11-config
make phase11-start
make phase11-health
make phase11-admit (expected denial while RT-CV ran)
make phase11-test
make phase11-benchmark
make phase11-evidence
make alerts-default-start
make alerts-default-health
make alerts-policy-test
make rtcv-health
make rtcv-test
make behavior-health
make phase10-health
make video-health
pytest -q
HTTP, Prometheus, Kafka, Elasticsearch, mount and credential checks
```

No prune, image/model/cache deletion, volume deletion, global package
installation or new model download occurred.

## Validation result

- Full project test suite after policy acceptance: 61 passed.
- Phase 11 unit tests: 9 passed.
- Alert-routing policy tests: 4 passed.
- Phase 11 Compose, collector/UI, plane-isolation and secret gates: PASS.
- Expected admission denial while RT-CV was active: PASS.
- Two-clean-chunk actual direct benchmark: PASS.
- Cosmos3 cache reuse and HTTP 200 inference: PASS.
- RT-CV restore and Phase 07 full smoke test: PASS.
- Phase 09, Phase 10 CPU services and video plane: healthy.
- Phase 11 dashboard/APIs/metrics: HTTP 200.
- Prometheus target `phase11-rt-vlm-results`: up.
- Browser AI overlay after direct-mode shutdown: `AI connected`, about 25 FPS.

## Evidence

- `artifacts/benchmarks/rt-vlm-alert/benchmark.json`
- `artifacts/benchmarks/rt-vlm-alert/gpu-samples.json`
- `artifacts/benchmarks/rt-vlm-alert/direct-alerts.json`
- `artifacts/benchmarks/rt-vlm-alert/collector-state.json`
- `artifacts/benchmarks/rt-vlm-alert/stream-state.json`
- `artifacts/benchmarks/rt-vlm-alert/collector-state-final.json`
- `artifacts/benchmarks/rt-vlm-alert/direct-alerts-final.json`
- `artifacts/benchmarks/rt-vlm-alert/evaluation-final.json`
- `artifacts/benchmarks/rt-vlm-alert/comparison-final.json`
- `artifacts/logs/phase11-smoke.txt`
- `artifacts/logs/phase11-dashboard.html`
- `artifacts/logs/phase11-direct-benchmark.txt`
- `artifacts/logs/phase11-rt-vlm.log`
- `artifacts/logs/phase11-cosmos3-cache-and-inference.txt`
- `artifacts/logs/phase11-container-mounts.txt`

## Issues found and resolved

1. The host-only relay health URL was not published. The direct start gate now
   checks readiness inside the relay container.
2. The CPU protobuf collector uses the RT-VLM image but has no GPU
   reservation. The Phase 07 admission scan initially classified it as a GPU
   workload; the exact collector name is now excluded while the real RT-VLM
   container remains forbidden.
3. Eight frames exceeded Cosmos3's maximum of five images per prompt and
   returned HTTP 422. Five fixed frames is now enforced in prompt, Compose,
   registration, tests and the clean benchmark gate. Initial error records
   remain as audit evidence.
4. The RT-VLM image reported an optional `PyNvVideoCodec`/`libavcodec.so.61`
   mismatch and used an available fallback. Final chunks still produced
   Cosmos3 HTTP 200 responses and valid protobuf results.
5. The first benchmark counter could include an empty error message. The hard
   gate now requires two new non-empty VLM responses, positive VLM latency and
   no more than five frames.

## Known limits

- Zero direct operator labels; no accuracy, precision, recall or false-alert
  claim is supported.
- Only one physical camera and one semantic use case were tested.
- Peak VRAM leaves about 2.6 GiB headroom; direct mode must not overlap RT-CV
  or be extrapolated to ten cameras.
- Continuous direct mode has higher GPU/token duty than event-driven hybrid
  verification.
- Optional vendor codec warnings remain even though the tested fallback
  produced valid results.
- Phase 08 physical ten-camera capacity evidence remains absent.

## Current runtime

- RT-CV, metadata, relay, Phase 09, Phase 10 CPU services and video plane:
  healthy.
- Cosmos3: stopped.
- Direct RT-VLM: stopped.
- Direct admission lease: revoked.
- Stable alert policy: Phase 10 hybrid default.
- Phase 10 CPU incident/review services: healthy, durable queue waiting for an
  admitted verification window.
- Phase 11 result collector/review UI: healthy.
- Kafka/Elasticsearch evidence and model/image caches: preserved.

## Post-handoff dashboard enhancement

On 2026-07-30 the existing review UI gained a read-only runtime resource
panel for host CPU/RAM, GPU utilization/VRAM and the Phase 11 containers. A
project-local host monitor publishes only numeric resource data under
`runtime/phase11-monitor`; the collector mounts that directory read-only. No Docker
socket, GPU device or camera credential was granted to the collector. This
observability enhancement does not change the accepted Phase 11 result,
stream, model or alert-routing policy.

## Rollback

- `make phase11-direct-stop` removes the direct stream, stops RT-VLM and
  Cosmos3, revokes the lease and restores RT-CV.
- `make phase11-stop` additionally stops the CPU collector.
- Both commands preserve Kafka, Elasticsearch, images, caches and evidence.
- No raw recording is modified or removed.

## Exact next phase

PHASE-12 only after a new explicit user instruction. PHASE-08 remains
deferred, incomplete and unapproved.

## Approval required

NO for PHASE-11; the `PARTIAL` result and runtime recommendation were accepted
on 2026-07-29. A separate explicit instruction is still required to begin
PHASE-12.
