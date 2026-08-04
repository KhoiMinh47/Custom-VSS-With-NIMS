# PHASE-06 HANDOFF

## Result

PASS_WITH_RISK

All Phase 06 runtime gates passed with one physical camera and nine simulated
sources. The risk suffix preserves the previously accepted AlmaLinux,
Docker/Compose, driver and experimental RTX PRO 5000 Blackwell deviations.
This result does not claim NVIDIA support for the host or GPU.

The operator-supplied physical camera is stable `cam-01`. Channel 101 is its
H.265 2560x1440/25 FPS main stream for VIOS recording/live; channel 102 remains
the logical H.264 1280x720/25 FPS AI substream for later inference phases.
`cam-02` through `cam-10` remain simulated replay sources. The committed
hybrid registry contains only secret references; no credential-bearing URI is
committed or written to an artifact.

## Scope completed

- Versioned one-store/ten-camera registry with stable camera IDs, UTC
  contracts, main/AI stream roles and secret references.
- NVIDIA VIOS Sensor, StreamProcessing, Ingress, PostgreSQL and Redis services.
- NVIDIA NVStreamer-based ten-source simulated camera profile.
- Project overlays that reinstall the media libraries NVIDIA removes from the
  published runtime while retaining the exact pinned 3.2.1 base digests.
- Idempotent single-pod Sensor-to-StreamProcessing registration adapter.
- Continuous raw recording independent of AI services.
- Live RTSP, recorded snapshot and time-range clip validation.
- Reconnect/backoff contract and functional source-loss/recovery test.
- Repeatable Phase 06 control-plane migration plus explicit rollback SQL.
- Health, onboard, smoke, reconnect, start and data-preserving stop scripts.
- Secret-safe, stdin-only physical RTSP receive/decode probe.
- Hybrid registry and explicit physical-camera activation/simulated rollback.
- Local MJPEG live-preview service for VS Code Simple Browser.
- Camera OSD clock synchronization command using authenticated ISAPI.

## Architecture boundary

The Phase 06 compose starts only the video/raw-storage plane. Raw recordings
are used by VIOS media selection and preparation APIs only. No raw-storage
path writes metadata, events, embeddings, summaries or reports, and no
inference service is present in the compose.

## Key files

- `config/cameras/cameras.simulated.json`
- `config/cameras/cameras.hybrid.json`
- `config/cameras/camera-registry.schema.json`
- `deploy/compose/video-management.compose.yml`
- `deploy/docker/video-source.Dockerfile`
- `services/video-management/`
- `migrations/002_video_management.sql`
- `migrations/002_video_management.rollback.sql`
- `scripts/build-video-source-image.sh`
- `scripts/build-streamprocessing-image.sh`
- `scripts/prepare-simulated-cameras.sh`
- `scripts/start-video-management.sh`
- `scripts/onboard-cameras.sh`
- `scripts/probe-live-video.sh`
- `scripts/test-video-management.sh`
- `scripts/test-video-reconnect.sh`
- `scripts/camera-live.sh`
- `scripts/stop-video-management.sh`
- `docs/reports/camera-onboarding-report.md`

## Validation

Observed:

- Unit tests: 15 passed.
- Video services healthy: 6/6.
- Sources, online sensors, live proxies and recording timelines: 10/10 each
  (one physical plus nine simulated).
- Raw segments written for every stream with UTC paths/timelines.
- Picture API returned a valid 640x360 JPEG.
- Clip API returned a valid MP4 for a UTC time range.
- Live RTSP receive probe remained connected for the test window.
- Reconnect test: recording bytes stabilized during outage and increased
  after source restart.
- Physical `cam-01`: authenticated H.265 RTP receive/decode, VIOS proxy,
  recording, snapshot and clip-by-time at 2560x1440/25 FPS.
- Idempotent migration/onboarding rerun passed.

Evidence:

- `artifacts/logs/phase06-video-management-smoke.txt`
- `artifacts/logs/phase06-reconnect.txt`
- `artifacts/logs/phase06-physical-camera-probe.txt`
- `artifacts/logs/phase06-vios-streams.json`
- `artifacts/logs/phase06-vios-status.json`
- `artifacts/manifests/phase06-image-sources.tsv`
- `artifacts/manifests/inventory-20260728T022421Z/`

## Known issues

- VIOS Sensor status remained `online` during the brief simulated source
  outage, despite recording quiescence. Recording recovery passed, but
  offline telemetry needs a Phase 07+ health-adapter decision.
- Simulated main and AI stream references resolve to the same replay file.
  Physical cameras should supply distinct RTSP profiles where available.
- Ten-source workflow evidence uses one physical and nine simulated sources.
  It is not evidence of ten-physical-camera capacity or soak stability; those
  gates remain `PARTIAL` until physical URLs are available and tests are rerun.
- The derived media overlays are identified by local immutable image IDs and
  pinned source digests; they are not yet published to a registry.
- The host remains outside NVIDIA's documented support matrix.

## Rollback

- `scripts/stop-video-management.sh` stops Phase 06 containers without deleting
  images, VIOS state, raw recordings, clips or snapshots.
- `migrations/002_video_management.rollback.sql` is an explicit,
  operator-triggered database rollback. Back up Phase 05 PostgreSQL first.
- Reverting the compose/config overlay restores deployment configuration;
  no automated destructive cleanup is provided.

## Exact next phase

PHASE-07, only after user review and approval of this handoff.

## Approval required

YES.
