SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help bootstrap verify-paths inventory infra-config infra-start infra-health infra-test infra-backup infra-stop video-build-source video-build-streamprocessing video-config video-prepare-simulated video-start video-health video-onboard video-probe-physical camera-save camera-probe camera-probe-ai camera-activate camera-mainstream camera-restore camera-clock-sync camera-snapshot camera-live camera-ai-overlay camera-ai-overlay-test camera-ai-overlay-outage-test camera-live-stop camera-live-status camera-status camera-clear video-test video-reconnect-test video-stop rtcv-config rtcv-start rtcv-health rtcv-test rtcv-reconnect-test rtcv-soak rtcv-evidence rtcv-stop behavior-config behavior-start behavior-health behavior-test behavior-stop alerts-default-start alerts-default-health alerts-policy-test phase10-config phase10-start phase10-health phase10-admit phase10-vlm-start phase10-vlm-stop phase10-test phase10-evidence phase10-stop phase11-config phase11-start phase11-health phase11-admit phase11-direct-start phase11-direct-stop phase11-test phase11-benchmark phase11-evidence phase11-stop phase12-config phase12-start phase12-health phase12-rt-embedding-start phase12-rt-embedding-stop phase12-siglip-start phase12-siglip-stop phase12-llm-start phase12-llm-stop phase12-critic-start phase12-critic-stop phase12-test phase12-evaluate phase12-evidence phase12-stop phase13-config phase13-start phase13-health phase13-vlm-start phase13-vlm-stop phase13-llm-start phase13-llm-stop phase13-test phase13-evaluate phase13-evidence phase13-stop phase15-config phase15-start phase15-health phase15-user phase15-gpu-worker-start phase15-gpu-worker-stop phase15-test phase15-backup phase15-restore-test phase15-evidence phase15-stop

help:
	@printf '%s\n' \
	  'bootstrap       Create project-local directories and Python 3.12 venv' \
	  'verify-paths    Verify cache/venv paths and safety guards' \
	  'inventory       Record non-destructive Docker/disk inventory' \
	  'infra-config    Validate resolved infrastructure Compose' \
	  'infra-start     Start Phase 05 infrastructure' \
	  'infra-health    Check Phase 05 health' \
	  'infra-test      Run infrastructure and persistence smoke tests' \
	  'infra-backup    Create a project-local infrastructure backup' \
	  'infra-stop      Stop infrastructure while preserving all data/images' \
	  'video-build-source  Build the project-owned NVStreamer media overlay' \
	  'video-build-streamprocessing  Build the VIOS StreamProcessing media overlay' \
	  'video-config    Validate Phase 06 video-management Compose/config' \
	  'video-prepare-simulated  Prepare ten project-local replay sources' \
	  'video-start     Start the Phase 06 VIOS video plane' \
	  'video-health    Check all Phase 06 video services' \
	  'video-onboard   Register the ten configured sources' \
	  'video-probe-physical  Secret-safe probe of one physical RTSP camera' \
	  'camera-save     Save one RTSP URI in the system keyring' \
	  'camera-probe    Probe the saved physical camera' \
	  'camera-probe-ai Probe physical channel 102 H.264 AI substream' \
	  'camera-activate  Replace simulated cam-01 with the physical camera' \
	  'camera-mainstream Switch cam-01 to H.265 2560x1440 main stream' \
	  'camera-clock-sync Sync the physical camera clock to the server' \
	  'camera-restore  Restore simulated cam-01' \
	  'camera-snapshot  Save one JPEG frame from the physical camera' \
	  'camera-live     Start VS Code/browser live MJPEG preview' \
	  'camera-ai-overlay Start/check cam-01 live AI overlay on port 8090' \
	  'camera-ai-overlay-test Test page, canvas, metadata progress and secrets' \
	  'camera-ai-overlay-outage-test Prove video survives an RT-CV outage' \
	  'camera-live-stop Stop live MJPEG preview' \
	  'camera-status   Check whether the keyring entry exists' \
	  'camera-clear    Remove the keyring entry' \
	  'video-test      Run Phase 06 smoke tests and save evidence' \
	  'video-reconnect-test  Prove recording resumes after source loss' \
	  'video-stop      Stop video services while preserving recordings/images' \
	  'rtcv-config     Validate Phase 07 single-camera Compose/config' \
	  'rtcv-start      Start cam-01 RT-DETR/NvDCF vertical slice' \
	  'rtcv-health     Check RT-CV, broker metadata and index readiness' \
	  'rtcv-test       Run Phase 07 end-to-end smoke tests' \
	  'rtcv-reconnect-test  Test selected AI source loss/recovery' \
	  'rtcv-soak       Run the required two-hour Phase 07 soak' \
	  'rtcv-evidence   Capture final Phase 07 runtime evidence' \
	  'rtcv-stop       Stop Phase 07 containers without deleting data/images' \
	  'behavior-config Validate Phase 09 behavior analytics Compose' \
	  'behavior-start  Start Phase 09 behavior analytics on port 39110' \
	  'behavior-health Check Phase 09 service and state contract' \
	  'behavior-test   Run Phase 09 analytics/evaluation smoke tests' \
	  'behavior-stop   Stop Phase 09 while preserving data/images' \
	  'alerts-default-start Activate Phase 10 hybrid and disable direct RT-VLM' \
	  'alerts-default-health Verify the stable hybrid alerting policy/runtime' \
	  'alerts-policy-test Test hybrid-default/direct-opt-in policy contracts' \
	  'phase10-config  Validate Phase 10 incident/verifier Compose' \
	  'phase10-start   Start CPU incident queue and review UI' \
	  'phase10-health  Check Phase 10 services and queue state' \
	  'phase10-admit   Evaluate local Cosmos3 admission without overlap' \
	  'phase10-vlm-start Start cached Cosmos3 after admission is granted' \
	  'phase10-vlm-stop Stop Cosmos3 and revoke lease; preserve cache' \
	  'phase10-test    Run Phase 10 contract/runtime smoke tests' \
	  'phase10-evidence Capture Phase 10 state, evaluation and secret-safe logs' \
	  'phase10-stop    Stop Phase 10 CPU services and preserve evidence' \
	  'phase11-config  Validate Phase 11 direct RT-VLM Compose' \
	  'phase11-start   Start Phase 11 CPU result collector and review UI' \
	  'phase11-health  Check the Phase 11 collector and direct-mode state' \
	  'phase11-admit   Evaluate direct RT-VLM admission (RT-CV must be stopped)' \
	  'phase11-direct-start Start Cosmos3 + RT-VLM for cam-01 under admission' \
	  'phase11-direct-stop Stop direct mode, preserve caches and restore RT-CV' \
	  'phase11-test    Run Phase 11 contracts, UI, isolation and secret tests' \
	  'phase11-benchmark Run actual two-chunk direct RT-VLM benchmark' \
	  'phase11-evidence Capture Phase 11 comparison and secret-safe evidence' \
	  'phase11-stop    Stop Phase 11 while preserving data/images/caches' \
	  'phase12-config  Validate Phase 12 search and GPU profile Compose' \
	  'phase12-start   Start Phase 12 CPU search API/UI on port 39310' \
	  'phase12-health  Check search contracts, indices, UI and metrics' \
	  'phase12-rt-embedding-start Start cached Cosmos-Embed1 admitted window' \
	  'phase12-rt-embedding-stop Stop RT-Embedding and restore RT-CV' \
	  'phase12-siglip-start Start cached SigLIP2 admitted window' \
	  'phase12-siglip-stop Stop SigLIP2 and restore RT-CV' \
	  'phase12-llm-start Start Nemotron decomposition admitted window' \
	  'phase12-llm-stop Stop Nemotron and restore RT-CV' \
	  'phase12-critic-start Start Cosmos3 critic admitted window' \
	  'phase12-critic-stop Stop critic and restore RT-CV' \
	  'phase12-test    Run Phase 12 contracts/isolation/runtime tests' \
	  'phase12-evaluate Run the bounded Phase 12 query-set evaluation' \
	  'phase12-evidence Capture Phase 12 state/results and secret-safe logs' \
	  'phase12-stop    Stop Phase 12 while preserving vectors/caches/evidence' \
	  'phase13-config  Validate Phase 13 summary/report Compose' \
	  'phase13-start   Start Phase 13 durable CPU queue/API on port 39410' \
	  'phase13-health  Check queue, API, dashboard, evidence policy and metrics' \
	  'phase13-vlm-start Start admitted Cosmos3 selected-clip caption window' \
	  'phase13-vlm-stop Stop Cosmos3, preserve checkpoints and restore RT-CV' \
	  'phase13-llm-start Start admitted Nemotron summary/Q&A window' \
	  'phase13-llm-stop Stop Nemotron, preserve results and restore RT-CV' \
	  'phase13-test    Run Phase 13 contracts/runtime/isolation tests' \
	  'phase13-evaluate Run actual caption/summary/Q&A/report evaluation' \
	  'phase13-evidence Capture Phase 13 state and secret-safe evidence' \
	  'phase13-stop    Stop Phase 13 while preserving all jobs/results/caches' \
	  'phase15-config  Validate Phase 15 unified app Compose' \
	  'phase15-start   Start unified control room on port 39510' \
	  'phase15-health  Check registry, dashboard, RBAC and metrics' \
	  'phase15-user SUBJECT=name ROLE=operator Configure a digest-only user token' \
	  'phase15-gpu-worker-start Start allowlisted host GPU control worker' \
	  'phase15-gpu-worker-stop Stop worker without changing active workload' \
	  'phase15-test    Run UI/API/security/isolation/restore tests' \
	  'phase15-backup  Back up Phase 15 registry, UI and audit data' \
	  'phase15-restore-test Verify backup in an isolated temporary directory' \
	  'phase15-evidence Capture Phase 15 state and secret-safe evidence' \
	  'phase15-stop    Stop only the unified app and preserve all data'

bootstrap:
	@bash scripts/bootstrap-project.sh

verify-paths:
	@bash scripts/verify-project-paths.sh

inventory:
	@bash scripts/inventory.sh

infra-config:
	@source scripts/infra-lib.sh && infra_compose config --quiet

infra-start:
	@bash scripts/start-infra.sh

infra-health:
	@bash scripts/healthcheck-infra.sh

infra-test:
	@bash scripts/test-infra.sh
	@bash scripts/test-infra-persistence.sh

infra-backup:
	@bash scripts/backup-infra.sh

infra-stop:
	@bash scripts/stop-infra.sh

video-build-source:
	@bash scripts/build-video-source-image.sh

video-build-streamprocessing:
	@bash scripts/build-streamprocessing-image.sh

video-config:
	@source scripts/video-lib.sh && video_compose config --quiet

video-prepare-simulated:
	@bash scripts/prepare-simulated-cameras.sh

video-start:
	@bash scripts/start-video-management.sh

video-health:
	@bash scripts/healthcheck-video-management.sh

video-onboard:
	@bash scripts/onboard-cameras.sh

video-probe-physical:
	@bash scripts/probe-physical-camera.sh

camera-save:
	@bash scripts/camera-api.sh save

camera-probe:
	@bash scripts/camera-api.sh probe

camera-probe-ai:
	@bash scripts/camera-api.sh probe-ai

camera-activate:
	@bash scripts/camera-api.sh activate

camera-mainstream:
	@bash scripts/camera-api.sh mainstream

camera-clock-sync:
	@.venv/bin/python services/video-management/camera_clock_sync.py runtime/secrets/camera-secret.sock

camera-restore:
	@bash scripts/camera-api.sh restore

camera-snapshot:
	@bash scripts/camera-snapshot.sh

camera-live:
	@bash scripts/camera-live.sh start

camera-ai-overlay:
	@bash scripts/camera-live.sh overlay

camera-ai-overlay-test:
	@bash scripts/test-camera-ai-overlay.sh

camera-ai-overlay-outage-test:
	@bash scripts/test-camera-ai-overlay-outage.sh

camera-live-stop:
	@bash scripts/camera-live.sh stop

camera-live-status:
	@bash scripts/camera-live.sh status

camera-status:
	@bash scripts/camera-api.sh status

camera-clear:
	@bash scripts/camera-api.sh clear

video-test:
	@bash scripts/test-video-management.sh

video-reconnect-test:
	@bash scripts/test-video-reconnect.sh

video-stop:
	@bash scripts/stop-video-management.sh

rtcv-config:
	@source scripts/rtcv-lib.sh && rtcv_compose config --quiet

rtcv-start:
	@bash scripts/start-rtcv.sh

rtcv-health:
	@bash scripts/healthcheck-rtcv.sh

rtcv-test:
	@bash scripts/test-rtcv.sh

rtcv-reconnect-test:
	@bash scripts/test-rtcv-reconnect.sh

rtcv-soak:
	@bash scripts/soak-rtcv.sh

rtcv-evidence:
	@bash scripts/capture-rtcv-evidence.sh

rtcv-stop:
	@bash scripts/stop-rtcv.sh

behavior-config:
	@source scripts/behavior-lib.sh && behavior_compose config --quiet

behavior-start:
	@bash scripts/start-behavior-analytics.sh

behavior-health:
	@bash scripts/healthcheck-behavior-analytics.sh

behavior-test:
	@bash scripts/test-behavior-analytics.sh

behavior-stop:
	@bash scripts/stop-behavior-analytics.sh

alerts-default-start:
	@bash scripts/start-default-alerting.sh

alerts-default-health:
	@bash scripts/healthcheck-default-alerting.sh

alerts-policy-test:
	@.venv/bin/python -m pytest -q tests/unit/test_alert_routing_policy.py

phase10-config:
	@source scripts/phase10-lib.sh && phase10_compose config --quiet

phase10-start:
	@bash scripts/start-phase10.sh

phase10-health:
	@bash scripts/healthcheck-phase10.sh

phase10-admit:
	@.venv/bin/python services/gpu-admission-controller/admission.py grant --lease runtime/gpu-admission/local-vlm.lease

phase10-vlm-start:
	@bash scripts/start-phase10-vlm.sh

phase10-vlm-stop:
	@bash scripts/stop-phase10-vlm.sh

phase10-test:
	@bash scripts/test-phase10.sh

phase10-evidence:
	@bash scripts/capture-phase10-evidence.sh

phase10-stop:
	@bash scripts/stop-phase10.sh

phase11-config:
	@source scripts/phase11-lib.sh && phase11_compose config --quiet

phase11-start:
	@bash scripts/start-phase11.sh

phase11-health:
	@bash scripts/healthcheck-phase11.sh

phase11-admit:
	@.venv/bin/python services/gpu-admission-controller/admission.py grant --profile direct_rt_vlm --lease runtime/gpu-admission/direct-rt-vlm.lease

phase11-direct-start:
	@bash scripts/start-phase11-direct.sh

phase11-direct-stop:
	@bash scripts/stop-phase11-direct.sh

phase11-test:
	@bash scripts/test-phase11.sh

phase11-benchmark:
	@bash scripts/benchmark-phase11.sh

phase11-evidence:
	@bash scripts/capture-phase11-evidence.sh

phase11-stop:
	@bash scripts/stop-phase11.sh

phase12-config:
	@source scripts/phase12-lib.sh && phase12_compose config --quiet

phase12-start:
	@bash scripts/start-phase12.sh

phase12-health:
	@bash scripts/healthcheck-phase12.sh

phase12-rt-embedding-start:
	@bash scripts/start-phase12-rt-embedding.sh

phase12-rt-embedding-stop:
	@bash scripts/stop-phase12-rt-embedding.sh

phase12-siglip-start:
	@bash scripts/start-phase12-siglip.sh

phase12-siglip-stop:
	@bash scripts/stop-phase12-siglip.sh

phase12-llm-start:
	@bash scripts/start-phase12-llm.sh

phase12-llm-stop:
	@bash scripts/stop-phase12-llm.sh

phase12-critic-start:
	@bash scripts/start-phase12-critic.sh

phase12-critic-stop:
	@bash scripts/stop-phase12-critic.sh

phase12-test:
	@bash scripts/test-phase12.sh

phase12-evaluate:
	@.venv/bin/python scripts/evaluate-phase12-search.py

phase12-evidence:
	@bash scripts/capture-phase12-evidence.sh

phase12-stop:
	@bash scripts/stop-phase12.sh

phase13-config:
	@source scripts/phase13-lib.sh && phase13_compose config --quiet

phase13-start:
	@bash scripts/start-phase13.sh

phase13-health:
	@bash scripts/healthcheck-phase13.sh

phase13-vlm-start:
	@bash scripts/start-phase13-vlm.sh

phase13-vlm-stop:
	@bash scripts/stop-phase13-vlm.sh

phase13-llm-start:
	@bash scripts/start-phase13-llm.sh

phase13-llm-stop:
	@bash scripts/stop-phase13-llm.sh

phase13-test:
	@bash scripts/test-phase13.sh

phase13-evaluate:
	@bash scripts/evaluate-phase13.sh

phase13-evidence:
	@bash scripts/capture-phase13-evidence.sh

phase13-stop:
	@bash scripts/stop-phase13.sh

phase15-config:
	@source scripts/phase15-lib.sh && phase15_compose config --quiet

phase15-start:
	@bash scripts/start-phase15.sh

phase15-health:
	@bash scripts/healthcheck-phase15.sh

phase15-user:
	@bash scripts/configure-phase15-operator.sh "$(SUBJECT)" "$(ROLE)"

phase15-gpu-worker-start:
	@bash scripts/start-phase15-gpu-worker.sh

phase15-gpu-worker-stop:
	@bash scripts/stop-phase15-gpu-worker.sh

phase15-test:
	@bash scripts/test-phase15.sh

phase15-backup:
	@bash scripts/backup-phase15.sh

phase15-restore-test:
	@bash scripts/test-phase15-restore.sh

phase15-evidence:
	@bash scripts/capture-phase15-evidence.sh

phase15-stop:
	@bash scripts/stop-phase15.sh
