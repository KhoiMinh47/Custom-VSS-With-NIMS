# PHASE-07 HANDOFF

## Result

PASS_WITH_RISK

The one-camera RT-CV vertical slice passed detection, NvDCF tracking, broker
publication, Elasticsearch indexing, line-crossing smoke, reconnect,
TensorRT-cache reuse and a continuous 7,227-second soak. The approved Phase 07
UI extension also passed live MJPEG/canvas composition and RT-CV outage
fallback without starting Phase 08.

The risk suffix preserves the accepted AlmaLinux, Docker/Compose and driver
deviations and the experimental RTX PRO 5000 Blackwell topology. NVIDIA does
not validate this GPU for the selected VSS topology, and this handoff does not
claim otherwise. The result covers one physical camera only and is not
multi-camera capacity evidence.

### AI overlay stability correction

The original UI state proxy treated the metadata and optional vendor-metrics
requests as one all-or-nothing operation. One transient exception therefore
returned a disconnected payload, and the browser's 125 ms poll handler
immediately erased the last overlay. The corrected implementation:

- retries each upstream read up to three times with a bounded timeout;
- uses metadata `/debug/state` as the primary AI health signal and retains
  cached FPS/frame values when vendor metrics alone fails;
- treats an advancing vendor frame counter as connected during valid
  object-silent metadata intervals;
- requires three consecutive failed state polls before `unavailable`;
- distinguishes `connected`, `reconnecting`, `metadata_delayed`,
  `waiting_for_metadata` and `unavailable`;
- polls every 400 ms and retains the last boxes/tracks for at most five
  seconds; and
- raises the default metadata stale threshold from three to ten seconds.

## Scope completed

- Exactly one physical source: stable `camera_id=cam-01`,
  `store_id=store-001`.
- Secret-safe logical channel-102 H.264 1280x720/25 FPS AI relay derived from
  the credential-free VIOS proxy of physical H.265 channel 101.
- Pinned VSS 3.2.1 RT-CV image and project overlay.
- RT-DETR Warehouse 2D v1.0.2 FP16, batch 1, 640x640.
- Project-local TensorRT 10.14.1 engine built for GPU 0 and reused on restart.
- NvDCF tracking with track IDs in the stable metadata contract.
- NVIDIA protobuf metadata through Kafka `mdx-raw`.
- Stable JSON publication to `vss.rt-cv.frames` and idempotent indexing
  through Elasticsearch alias `mdx-raw`.
- Full-frame ROI and center-line crossing smoke rule; four actual crossing
  documents were present at final validation.
- Minimal metadata overlay, health endpoints and Prometheus metrics.
- Single-GPU admission check; no VLM, LLM or RT-Embed service was enabled.
- Smoke, reconnect, plane-isolation, secret-scan and two-hour soak evidence.
- Browser-only `/ai-overlay` compositor over the existing `/mjpeg` stream.
- Filtered same-origin `/api/ai-state` proxy with no RTSP URI or credentials.
- Responsive normalized boxes with class, confidence, track ID, UTC timestamp,
  FPS/frame counter, line-crossing indicator and AI connection state.
- Explicit connected, reconnecting, metadata-delayed and unavailable states
  that leave the Phase 06 live video running.
- Three-attempt upstream reads, a three-poll outage threshold, a ten-second
  metadata stale threshold and a bounded five-second last-box grace.
- Metadata `/debug/state` remains authoritative when the optional vendor
  metrics request fails temporarily.

## Architecture boundary

The Phase 07 services consume only the selected live 720p AI input. Neither the
RT-CV nor metadata container mounts `runtime/raw-video`, and no raw recording
is used to create metadata, events or embeddings. During final validation,
the Phase 06 physical main-stream recording was current while the Phase 07
raw-storage mount count was zero.

## Files created

- `config/deepstream/ds-detector-labels.txt`
- `config/deepstream/ds-kafka-config.txt`
- `config/deepstream/ds-main-config.txt`
- `config/deepstream/ds-pgie-config.yml`
- `config/deepstream/ds-nvdcf-tracker-config.yml`
- `config/analytics/cam-01.yaml`
- `deploy/compose/rtcv.compose.yml`
- `deploy/docker/rtcv-relay.Dockerfile`
- `services/rt-cv/contracts.py`
- `services/rt-cv/secure_rtsp_relay.py`
- `services/rt-cv/log_supervisor.py`
- `services/rt-cv/metadata_service.py`
- `services/rt-cv/README.md`
- `scripts/rtcv-lib.sh`
- `scripts/build-rtcv-relay-image.sh`
- `scripts/start-rtcv.sh`
- `scripts/healthcheck-rtcv.sh`
- `scripts/test-rtcv.sh`
- `scripts/test-rtcv-reconnect.sh`
- `scripts/soak-rtcv.sh`
- `scripts/analyze-rtcv-soak.py`
- `scripts/capture-rtcv-evidence.sh`
- `scripts/stop-rtcv.sh`
- `tests/unit/test_rtcv.py`
- `services/video-management/ai_overlay.py`
- `scripts/test-camera-ai-overlay.sh`
- `scripts/test-camera-ai-overlay-outage.sh`
- `tests/unit/test_ai_overlay.py`

## Files modified

- `Makefile`
- `config/broker/topics.txt`
- `config/models/model-manifest.yaml`
- `config/prometheus/prometheus.yml`
- `config/runtime/single-gpu-poc.yaml`
- `scripts/camera-api.sh`
- `services/video-management/mjpeg_server.py`
- `services/video-management/README.md`
- `services/rt-cv/README.md`
- `README.md`
- `PROJECT_STATE.md`
- `phase.md`

## Commands executed

```text
./scripts/inventory.sh
docker compose -f deploy/compose/rtcv.compose.yml config --quiet
TensorRT trtexec --onnx=<approved RT-DETR ONNX> --saveEngine=<project cache>
  --stronglyTyped --skipInference --builderOptimizationLevel=3
./scripts/start-rtcv.sh
./scripts/test-rtcv.sh
./scripts/test-rtcv-reconnect.sh
./scripts/soak-rtcv.sh
./scripts/analyze-rtcv-soak.py ...
./scripts/capture-rtcv-evidence.sh
make camera-live
make camera-ai-overlay
make camera-ai-overlay-test
make camera-ai-overlay-outage-test
pytest -q
```

No image, builder, volume or Docker prune was run. No image/model/cache/volume
was deleted, and no download was required in Phase 07.

## Services, images and models affected

Running Phase 07 services:

- `ntc-vss-phase07-rtsp-relay`
- `ntc-vss-phase07-rtcv`
- `ntc-vss-phase07-metadata`

The project-local camera-live host process is also running on loopback port
8090 and serves `/mjpeg`, `/ai-overlay` and the filtered `/api/ai-state`.
Canvas composition adds no video re-encode or additional GPU workload.

All use the exact pinned release image:

```text
nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1
sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458
```

The release-managed application inside this image announces the intentional
3.2.0 perception asset. It was not retagged or replaced.

Detector and engine:

- RT-DETR Warehouse 2D v1.0.2 FP16 ONNX SHA-256:
  `0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267`
- TensorRT engine SHA-256:
  `52402a0a5d4a5e2d2fb41fe2bd6e3c39a29eb2e40fc9a9b778fcee5addd46271`
- Engine size: 90,225,876 bytes.
- TensorRT: 10.14.1; driver: 590.48.01; batch: 1; strongly typed FP16.
- Restart logs explicitly report `deserialized trt engine`; no rebuild occurred.

## Validation evidence

Primary:

- `artifacts/benchmarks/rtcv-1-camera/soak-20260728T111719Z/summary.json`
- `artifacts/benchmarks/rtcv-1-camera/soak-20260728T111719Z/metrics-summary.json`
- `artifacts/benchmarks/rtcv-1-camera/soak-20260728T111719Z/samples.jsonl`
- `artifacts/benchmarks/rtcv-1-camera/soak-20260728T111719Z/rtcv-runtime.jsonl`
- `artifacts/benchmarks/rtcv-1-camera/trtexec-build.txt`
- `artifacts/logs/phase07-rtcv-smoke.txt`
- `artifacts/logs/phase07-rtcv-reconnect.txt`
- `artifacts/logs/phase07-elasticsearch-sample.json`
- `artifacts/logs/phase07-line-crossing-sample.json`
- `artifacts/logs/phase07-debug-overlay.html`
- `artifacts/logs/phase07-plane-isolation.txt`
- `artifacts/logs/phase07-container-state.tsv`
- `artifacts/manifests/phase07-rtdetr-engine-sha256.txt`
- `artifacts/manifests/inventory-20260728T095205Z/`
- `artifacts/logs/phase07-ai-overlay-smoke.txt`
- `artifacts/logs/phase07-ai-overlay.html`
- `artifacts/logs/phase07-ai-overlay-headers.txt`
- `artifacts/logs/phase07-ai-overlay-state.json`
- `artifacts/logs/phase07-ai-overlay-outage.txt`

Two exploratory windows were invalidated because the first monitor treated an
object-free metadata interval as a pipeline stall. Kafka lag was zero while
the DeepStream frame counter continued to advance. The corrected final gate
uses the source frame counter for continuity; the invalidated evidence and
diagnostic assessments were preserved rather than deleted.

## Metrics

- Soak result: PASS.
- Duration: 7,227 seconds.
- Successful samples: 239/239.
- DeepStream frame delta: 179,930.
- Observed/vendor FPS: 25.0 average; 24.997 minimum.
- Vendor latency: 2.141 ms average, 5.093 ms p95, 6.410 ms maximum.
- Frame-counter resets: 0.
- Non-advancing samples: 0.
- Runtime drop warnings: 0.
- Runtime stream/decode errors: 0.
- Metadata decode, Kafka publish and Elasticsearch error deltas: 0.
- Maximum GPU memory used: 6,945 MiB.
- Maximum GPU utilization observed by the 30-second sampler: 4%.
- Container restarts: 0; OOM-killed: false for all three services.
- Elasticsearch `cam-01` documents at original soak closure: 49,426.
- Elasticsearch `cam-01` documents at UI-extension final gate: 83,263.
- Final line-crossing smoke documents: 4.
- Unit tests: 30 passed.
- Prometheus target `phase07-rtcv`: up.
- AI overlay endpoint: HTTP 200.
- UI composition contract: `/mjpeg` source plus canvas layer present.
- Live metadata progression before the outage gate: metadata frames 9,071 to
  9,077, vendor frame counter 45,712 to 45,742, track ID 115 observed.
- RT-CV outage: UI unavailable warning passed while MJPEG delivered
  13,819,904 bytes; the existing endpoint-level recovery assertion passed.

Post-gate runtime note: after the destructive-free Phase 07 stop/start used by
the outage test, all three containers and their readiness endpoints returned
healthy and `cam-01` remained registered, but vendor `stream-stats` remained
empty and the secure relay reported that the physical channel-102 source could
not prepare media. A second clean stop/start and relay restart did not restore
frames. The independent channel-101 MJPEG remained live (13,533,184 bytes in
three seconds), and the corrected frontend accurately showed
`waiting_for_metadata` instead of falsely claiming fresh AI. This physical
AI-substream recovery condition is reported as a current runtime limitation;
it is not masked by historical metadata or mocks.

Runtime recovery update on 2026-07-29: physical channel 102 continued to reject
RTSP SETUP, while the VIOS-managed channel-101 proxy remained live. The secure
relay was changed to consume that credential-free proxy and transcode H.265
2560x1440 to an internal logical channel 102 at H.264 1280x720/25 FPS before
RT-CV. After restart, metadata progressed again, vendor metrics reported
24.997 FPS with an advancing frame counter, and `/api/ai-state` returned
`connected`. Main-stream recording and raw-storage isolation were not changed.
Logical channel 102 is project-managed and is not evidence that the physical
camera's firmware channel 102 recovered.

Current-source update on 2026-07-30: a new secret-safe probe of the physical
channel 102 passed authentication, RTP receive, H.264 decode and reported
1280x720. The secure relay now prefers that physical channel and republishes
H.264 with clean periodic keyframes; channel 101 remains the independent H.265
2560x1440 recording/live stream and a fallback only if the physical secret
lease is unavailable. The failed 2026-07-29 attempts above remain audit
history, not current source status.

Current physical-source evidence:
`artifacts/logs/phase07-physical-ai-substream-probe.txt`.

The VSS metrics API does not expose an absolute input-frame-drop counter.
Therefore the Phase 07 drop gate records monotonic source-frame continuity
plus explicit runtime drop/decode/stream signals. With `dummy-payload=0`,
metadata publication is object-driven; a detection-silent interval is not a
source frame drop.

## Known issues and risks

- RTX PRO 5000 Blackwell remains experimental for this VSS topology and is not
  NVIDIA-validated.
- The host remains outside NVIDIA's documented VSS 3.2.1 OS,
  Docker/Compose and driver baseline.
- This is one physical camera evidence only. It must not be presented as
  ten-camera throughput or physical-scale stability.
- The upstream NvDCF config produces an `Unknown param:
  vpiBackend4DcfTracker` warning in the release image. Tracking, IDs and the
  soak passed; the upstream parameter was retained and the warning preserved.
- The image also logs optional early-message/error-propagation initialization
  warnings while the Kafka metadata path remains functional.
- The warehouse detector was smoke-validated for person detection/tracking,
  not accuracy-benchmarked for this store.
- The UI background and AI relay both derive from the VIOS-managed channel-101
  stream. The relay scales the AI input to 1280x720; normalized coordinates
  preserve display alignment, but the MJPEG and AI consumers are not
  frame-locked. A five-second grace limits cached boxes, while the metadata
  stale threshold is ten seconds.
- Browser polling targets 2.5 updates per second, while effective visual
  updates remain bounded by object-driven metadata and the existing 8 FPS
  MJPEG preview.

## Rollback

- `scripts/stop-rtcv.sh` stops only Phase 07 containers.
- Images, the ONNX model, TensorRT engine, Kafka data, Elasticsearch documents,
  Phase 06 recordings and all bind-mounted data are preserved.
- Revert the project overlay/config files to restore configuration.
- No automated destructive cleanup or cache deletion exists.

## Exact next phase

PHASE-08, only after user review and explicit approval of this handoff.

## Approval required

YES.
