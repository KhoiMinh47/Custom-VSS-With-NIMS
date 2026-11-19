# PHASE-15 HANDOFF — unified VSS workspace refinement

## 2026-11-19 Real-time Alerts wiring completion (source only, current)

This entry finishes the source-level follow-ups to the Real-time Alerts gateway
commit `1e27702`. By explicit user instruction, **nothing was executed**: no
container, model or NIM was started, and no unit test, healthcheck, backup or
restore test was run. Every item below is unvalidated source and is not runtime
evidence.

- Operations: `scripts/start-phase15.sh` starts `alert-realtime-redis` and
  `alert-realtime` and waits for `127.0.0.1:9080/api/v1/realtime`.
  `scripts/stop-phase15.sh` stops both with `docker compose stop` only.
- Recovery: `scripts/backup-phase15.sh` archives
  `scripts/alert-realtime-start.py`, and `scripts/test-phase15-restore.sh`
  verifies it with `test -s` and `cmp`.
- Health: `scripts/healthcheck-phase15.sh` reads the same-origin rule list. It
  also asserts that a cross-origin `POST` is rejected with `400` before it
  reaches the upstream.
- Gateway audit: `POST /compat/alert-bridge/api/v1/realtime[/{id}]` now sets
  `workspace_attempt`, so rejected or failed create attempts are audited the
  same way as other workspace mutations. Same-origin, JSON and size checks were
  already enforced by `_read_json`.
- Registry: `config/application/service-registry.json` version 5 adds
  `realtime-alert-rules` (`alerts`, port `9080`, `loopback-api`, `always_on`).
  Listing rules never admits a VLM.
- Contract: OpenAPI `1.6.0` documents the list, create, read and delete
  realtime-rule routes. The version assertion in
  `tests/unit/test_phase15.py` was updated to `1.6.0`; it has not been run. No
  new unit tests were written, at the user's request.
- Prometheus: [ADR-008](../decisions/ADR-008-phase15-metrics-relay.md) proposes
  a Unix-socket metrics relay with no new host listener and no change to the
  loopback bind. It is **proposed only**. `config/prometheus/prometheus.yml`
  marks the legacy target as a pending gate.

Before relying on these changes, run `make phase15-test`,
`make phase15-health` and `make phase15-restore-test`. Phase 15 remains
`PARTIAL`.

## 2026-08-05 Real-time Alerts URL repair

The NVIDIA Real-time Alerts screen was showing `Alerts API URL is not
configured` because the browser environment did not define
`NEXT_PUBLIC_ALERTS_API_URL`. The project environment now points the screen
to the same-origin Phase 15 gateway at
`/compat/alert-bridge/api/v1`; the gateway delegates only the fixed
loopback `/api/v1/realtime` rule routes to the pinned VSS Alert Verification
3.2.0 service. The 3.2.0 tag is intentional in the VSS 3.2.1 deployment
assets.

Runtime verification after recreating the UI/API containers:

- the rendered UI environment contains the same-origin alert URL;
- `GET /compat/alert-bridge/api/v1/realtime` returns HTTP 200 with an empty
  rule list;
- malformed rule input is returned as an upstream validation error rather
  than the previous generic invalid-response message.

The screen is therefore fixed at the control-plane/configuration boundary,
but this is not a full real-time inference PASS. The current direct RT-VLM
endpoint is ready while its Cosmos3 provider is stopped; the project
admission check also reports the GPU occupied by other registered workloads.
Creating a rule has not been presented as successful evidence. Realtime-rule
persistence is currently disabled in this compatibility overlay because the
upstream service's Elasticsearch client is incompatible with the project's
Elasticsearch 8.17 endpoint, so any temporary rule state is not durable.

## 2026-08-04 documentation consolidation and current checkpoint

The GitHub-facing documentation has been consolidated around one current
source of truth. `README.md` now describes the complete architecture, NVIDIA
models/NIMs, storage and event infrastructure, every implemented pipeline,
GPU admission, grouped phases and safe operation. `PROJECT_STATE.md` is the
concise current runtime checkpoint. The new `docs/README.md`,
`docs/architecture/PIPELINES.md` and
`docs/architecture/SERVICES-AND-MODELS.md` separate current architecture from
historical handoffs, reports and evaluation evidence.

At this checkpoint the unified UI/control-plane services are healthy, the
physical-only registry contains stable `cam-01`, the camera source and realtime
RT-CV are offline/unavailable, GPU providers are on-demand with no project
lease, and the shared reserve is 5120 MiB. VLM Test upload file-batch RT-CV →
VLM is technically proven; VLM Test Realtime remains implemented but requires
a newly persisted real candidate. The full unit/regression suite after this
documentation consolidation reports `172 passed`; the relative-link audit
reports zero broken links across project-owned Markdown files.

## 2026-08-04 cam-01 Streaming visibility correction

Video Management now enables RTSP stream filtering so the stable `cam-01`
source is not hidden by the upstream `showRtsps=false` default. The legacy
`+ Add RTSP` control is hidden by the project overlay; operators use the
project-owned `+ Upload Stream` control instead. The live replay adapter
returns credential-free stream cards for the VIOS inventory.

## 2026-08-04 Video Management single-pane/theme correction

The Video Management section switch now hides the upstream streaming main pane
before showing VLM Processed Videos, so the two views are never split on one
screen. The VLM section follows the upstream light/dark theme state and keeps
the same toolbar-level workflow.

## 2026-08-04 Video Management stream and VLM sections

The gateway now injects a project-owned `+ Upload Stream` button beside
`+ Upload Video` in Video Management. It opens a same-origin RTSP source
manager backed by VIOS inventory, sensor add and sensor delete operations.
Video Management also has `Streaming` and `VLM Processed Videos` sections; the
latter reads only media explicitly saved to the VLM Test Store and can launch a
repeat VLM run. Inventory is credential-free: URLs and credentials are not
returned to the browser or written to the project camera registry, and stable
`cam-01` is protected from deletion. Focused tests cover URL scrubbing and
stable-camera protection.

## 2026-08-04 header controls placement

The GPU and VLM Test launchers are positioned in the top header, immediately
to the left of the dark/light theme control. The GPU panel opens below the
header; narrow screens use a lower fallback position to avoid overlap.

## 2026-08-04 LLM/VLM web power controls

The VSS HTML now injects a project-owned GPU control overlay alongside the VLM
Test overlay. It shows separate LLM and VLM controls with green online/gray
offline indicators, transient notifications and 3-second state polling.

The backend exposes `GET /api/v1/gpu-control/models` and
`POST /api/v1/gpu-control/models/{llm|vlm}`. POST requests require explicit
confirmation and are queued through the host GPU worker, admission controller,
allowlisted start scripts and audit log. The model-specific OFF scripts revoke
the correct leases without restoring RT-CV. RT-CV is therefore started only by
the upload → RT-CV → VLM test workflow.

Runtime verification passed for LLM ON → OFF: Nemotron became healthy, the
control API reported `online`, then the OFF action stopped its container,
revoked `phase13-llm.lease`, reported `offline`, and left RT-CV stopped.

## 2026-08-04 VLM standard profile restored

The temporary low-memory VLM Test experiment has been removed from the active
launch path. Upload and retry now always use the reviewed standard Cosmos3
profile: `NIM_GPU_MEMORY_UTILIZATION=0.65`, `NIM_MAX_MODEL_LEN=32768`,
`NIM_MAX_NUM_SEQS=1` and `NIM_MAX_NUM_BATCHED_TOKENS=4096`. The earlier `0.40`
experiment remains historical evidence only and is not a supported runtime
mode.

## 2026-08-04 shared GPU reserve changed to 5 GiB

The operator-requested admission headroom is now `5120 MiB` (5 GiB) for both
LLM and VLM profiles. This changes the serialized admission gate only; it does
not lower Cosmos3's standard model/context profile or alter model weights.

The LLM was then re-admitted through `start-phase13-llm.sh`. Nemotron Nano 9B
v2 became healthy at `127.0.0.1:30081`, and a live gateway chat request
returned a real answer. At the checkpoint, `6266 MiB` remained free and the
`5120 MiB` reserve was satisfied. LLM and VLM remain mutually exclusive under
the single-GPU policy.

## 2026-08-04 automatic upload RT-CV → VLM workflow (latest)

The upload path is now automatic. On upload completion the BFF queues a
host-side `run_vlm_test` command. The GPU worker stops exact known GPU
containers and revokes their leases without calling the physical-camera
restore helper, grants the internal `rtcv_file_batch` admission budget, and
starts `deploy/compose/rtcv-file-batch.compose.yml` using the pinned VSS
RT-CV 3.2.1 image. The batch source is the staged MP4/MKV file; it consumes
actual `mdx-raw` protobuf frames and creates a candidate only when RT-CV
reports a detected object. No mock candidate and no raw-storage-to-metadata
shortcut are used.

After the candidate is persisted, the batch container and lease are stopped.
`start-phase10-vlm.sh` then admits and starts the cached Cosmos3 profile, and
the VLM-test service verifies the same staged video through the mounted
staging plane. The VLM lease is cleaned up after completion, while the job
remains staging-only until the operator presses Save to Store. The UI also
exposes `rtcv-start` for older blocked jobs or a retry.

Live evidence from upload `7334768614080.mp4`: 236 RT-CV frames, 364 objects,
one real candidate, Cosmos3 VLM completed with `uncertain`, worker command
completed, and zero active GPU leases after cleanup. The initial runtime
attempt exposed and fixed a read-only nested bind mount, then a VLM
`_request_json` keyword-only call bug. Repository tests: 166 passed after the
implementation and 61 focused checks after adding the workflow coverage.

The Upload overlay now starts the upload immediately on file selection or
drop; the separate `Upload (n)` button was removed. A candidate-bearing job's
`Retry VLM` action now queues the `vlm_only` host-worker workflow so it cannot
skip the GPU admission boundary. If admission is denied, the job remains
`waiting_for_gpu` and no Store asset is created.

An opt-in low-memory experiment was also added through
`VLM_TEST_GPU_MEMORY_UTILIZATION` (with reduced context defaults). On the
current host, `0.40` loaded the 16.6 GiB Cosmos3 weights but NIM reported
`Available KV cache memory: -4.57 GiB`; the engine exited before inference.
The experiment was cleaned up with zero active leases. This is evidence that
the unrelated GPU NIMs must be released before a low-memory Cosmos3 test can
run; it is not evidence of a successful VLM result.

## 2026-08-04 launcher and chat runtime fix (latest)

The VLM Test launcher was moved out of the React-managed NVIDIA header and
sidebar. `services/api/vlm_test_overlay.js` now mounts a high-z-index,
body-level fixed `VLM Test` control and the gateway injects it as
`overlay.js?v=3`; this keeps the control visible after hydration and when the
global Chat drawer covers the main workspace. The drawer's Upload view lists
the two currently staged upload jobs and their truthful
`BLOCKED · RT-CV file adapter pending` state instead of appearing empty.

The Chat integration gap was also closed. The BFF now has a fixed loopback
Nemotron upstream at `127.0.0.1:30081`, uses the NVIDIA UI's configured
`/compat/chat/stream` SSE route, and calls the provider only when an active
operator lease has profile `local_llm`, `search_llm` or `summarization_llm`.
The current diagnostic runtime has the pinned `summarization_llm` lease and a
healthy `nvidia/nvidia-nemotron-nano-9b-v2` container. Reasoning delimiters are
removed before the final answer is returned to the browser. Chat still does
not start or switch providers from browser input.

This diagnostic window remains serialized: RT-CV and Cosmos3 VLM are not
admitted at the same time. The live workflow completion is now evidenced by
the latest checkpoint above; production accuracy and physical-camera recovery
remain open. Validation: repository tests, Python/JavaScript syntax checks,
and the live Phase 15 healthcheck passed.

## 2026-08-04 VLM Test extension (current)

This is the user-requested extension of the pinned NVIDIA VSS UI. The official
reference describes the Search, Alerts, Video Management and persistent chat
surfaces, including MP4/MKV multi-file drag-and-drop upload, optional upload
configuration, per-file progress and the upload/RTSP management controls. The
local upstream source is already present at the exact VSS `v3.2.1` commit, so
it was not recloned or modified. See the official reference at
`https://docs.nvidia.com/vss/latest/vss-ui.html`.

The upstream Video Management UI remains the visual baseline. The project adds
`services/api/vlm_test_overlay.js`, injected by the gateway into the upstream
HTML, for the VLM Test workflow. Its Upload, Realtime and Store views use the
same-origin Phase 15 gateway and keep the upstream upload dialog's file type,
multi-file, drag/drop, add-more, progress and cancel behavior intact. The
feature is controlled by `VLM_TEST_UPLOAD_MODE=true` in the Phase 15 Compose
API, so the Video Management browser upload is staged in the VLM-test plane;
it does not create a persistent media-intake/Store asset before VLM completes.

Backend flow:

- `vlm-test` listens on loopback `39520` and owns staging, job state, explicit
  candidate attachment, VLM launch, Store listing and media serving.
- Upload jobs remain `staging_only` and are automatically sent through the
  project-owned RT-CV file-batch overlay. The overlay uses actual RT-CV Kafka
  detections to produce a candidate; if there is no detection, the job is
  explicitly `no_rtcv_candidate`. No mock candidate/result is generated.
- Realtime launch accepts only a real Phase 10 incident candidate, copies its
  selected clip into VLM-test staging, then calls the existing serialized
  `local_vlm` verifier. The clip is not added to Store at this point.
- A completed result is saved to Store only through the explicit Save action.
  Store Launch creates a retest job against that post-VLM asset without making
  a second raw-storage path. Rejected and uncertain results remain visible and
  require the same explicit operator decision to save.
- All job/candidate/result contracts carry `store_id`, stable `camera_id`, UTC
  timestamps, schema version, model/version fields and content SHA-256. The
  VLM-test service has no raw-recording mount and never reads raw storage.

The service uses the existing GPU admission boundary and serializes RT-CV,
test VLM and Phase 10 verification. Providers are stopped again after the
bounded workflow; the captured run used a real provider lease and GPU-backed
inference, while the extension remains `PARTIAL` for accuracy and hardware
support claims.

Validation for this extension:

- focused Phase 15 suite: 57 passed;
- VLM Test contract suite: 2 passed;
- Python compilation, JavaScript syntax, OpenAPI JSON and Compose resolution
  passed;
- source provenance remains the exact upstream commit and release image
  digest recorded in `apps/vss-ui/SOURCE-MANIFEST.json`.

## 2026-08-04 NVIDIA VSS UI replacement (current)

This checkpoint supersedes the earlier project-owned seven-route browser shell
described later in this historical handoff. `apps/dashboard` was removed from
the active tree. The browser now receives NVIDIA's unmodified
`nv-metropolis-bp-vss-ui`, including its packaged Search, Alerts and Video
Management screens and its persistent/resizable chat drawer.

Exact provenance:

- repository tag `v3.2.1`, commit
  `7640d917047cf7b0fd3085eefb8282754b56bc94`;
- app source:
  `third_party/video-search-and-summarization/services/ui/apps/nv-metropolis-bp-vss-ui`;
- package source:
  `third_party/video-search-and-summarization/services/ui/packages/nv-metropolis-bp-vss-ui`;
- release image:
  `nvcr.io/nvidia/vss-core/vss-agent-ui:3.2.0@sha256:6362151a839067f517766f1997a19c302296fe80b9b0251aaee8f16b379503d9`.

The 3.2.0 UI image tag is intentional in NVIDIA's VSS 3.2.1 deployment
assets. It was not retagged or presented as a separate baseline. The source
and image record is `apps/vss-ui/SOURCE-MANIFEST.json`.

Runtime layout:

- public same-origin gateway and UI: `127.0.0.1:39510`;
- private NVIDIA Next.js process: `127.0.0.1:39511`;
- non-secret feature flags: `config/ui/vss-ui.env`;
- bounded adapters: `services/api/vss_ui.py`;
- Compose: `deploy/compose/phase15.compose.yml`.

OpenAPI 3.1 contract version `1.5.0` documents the NVIDIA UI compatibility
routes in addition to the existing workspace contracts.

The UI and gateway are CPU-only. The UI container has zero mounts and no GPU
device request. The gateway mounts no raw recording storage, selected-media
directory, camera credential, Docker socket, GPU device or model cache. VST
access is restricted to stable sensor inventory and media
selection/preparation/presentation. Search and incident records come only from
the existing AI/search services, so no raw-storage-to-metadata/event/embedding/
summary/report path was introduced. Every transformed record preserves
`store_id=store-001`, stable `camera_id`, UTC time, schema version and relevant
model version.

RTSP onboarding remains disabled because its upstream contract does not match
the project's secret-reference and validated media intake policies. The
NVIDIA Video Management upload is enabled through the VLM-test staging overlay
described above; it does not use the persistent media-intake Store path before
VLM. Dashboard and Map tabs are disabled because no compatible same-origin
Kibana/Map contract is approved. Browser-controlled
`chatCompletionURL` is ignored by the gateway; opening or using chat never
starts a GPU model automatically.

Validation completed:

- `57 passed` in `tests/unit/test_phase15.py` and `164 passed` in the complete
  repository regression run;
- Phase 15 healthcheck passed against the live UI and adapters;
- official Search/Alerts/Video Management runtime flags were present in
  `/__ENV.js` with no credential-like content;
- a real `cam-01` VST thumbnail returned JPEG bytes;
- a real bounded VST selection returned a sanitized same-origin URL and
  `206 Partial Content` for bytes `0-1023/5657445`;
- Compose resolution, container isolation, structured logs and isolated
  backup restore passed.

Current evidence is isolated under
`artifacts/benchmarks/phase15-vss-ui/after/`; the older
`phase15-ui-refinement` directory remains preserved as historical custom-shell
evidence and is not mixed with this replacement checkpoint.

Final verified recovery archive:
`runtime/backups/phase15/phase15-control-plane-20260804T022803Z.tar.gz`.
Its adjacent SHA-256 check passed and the isolated restore test passed.

No browser executable/automation was installed, so screenshot, console,
keyboard-only and multi-viewport evidence remains `PARTIAL`. The physical
camera/live service is currently unavailable because the approved runtime-only
camera secret is absent; the UI reports that condition and no mock was used.

For shared GPU headroom, the project stop scripts stopped the exact Cosmos3,
RT-Embedding, SigLIP and Direct RT-VLM providers and revoked their leases
without deleting any image, engine, index, cache, volume or data. Only the
Direct RT-VLM result collector remains, without a GPU device. Final VRAM was
42,080 MiB free of 48,935 MiB and the admission snapshot reported zero policy
violations. No unidentified or teammate process was stopped. The provider stop
operations succeeded, but each script's final RT-CV restore helper returned
nonzero because the approved runtime-only physical camera secret is absent.
The pre-existing RT-CV container remains up with zero registered source, so its
Phase 07 health gate is still `PARTIAL`; the Phase 15 NVIDIA UI/gateway health
passes. RTX PRO 5000 Blackwell remains an experimental,
non-NVIDIA-validated topology for this deployment.

## Result

`PARTIAL`

This handoff records a refinement of Phase 15. It is not Phase 16. Phase 16
has not started. Phase 14 remains `LOCKED_BY_USER`, incomplete and unapproved.
Phase 08 remains deferred, incomplete and unapproved. The last approved phase
remains Phase 13.

The former launcher-oriented dashboard has been replaced in source by a
zero-build, responsive NVIDIA VSS-style operations workspace on the single
browser origin:

```text
http://127.0.0.1:39510/dashboard
```

The workspace now has seven deep-linkable areas:

```text
#/overview
#/cameras
#/search
#/summary
#/alerts
#/reports
#/system
```

Camera, search, selected-media summary/Q&A, alerts, reports and the contextual
AI drawer use project-owned same-origin `/api/v1/workspace` adapters. Primary
workflows no longer use iframes or open other dashboard ports. Technical
services, ports, phase state, admission and GPU control are confined to
System.

The implementation status and runtime validation status are separate:

- Source implementation and targeted Phase 15 unit/contract tests are
  complete.
- The Phase 15 container is running and healthy on `127.0.0.1:39510`.
  Same-origin camera/live/media, search, selected-media Q&A and report state
  were exercised against the real running backends; after-state evidence was
  captured.
- Latest runtime checkpoint (2026-08-03): the CPU control plane is healthy on
  `39310`, `39410`, `39420` and `39510`, and Phase 10 alert services are
  healthy. RT-CV/camera-live is currently unavailable because the runtime-only
  physical camera secret reference is missing; no credential was fabricated.
  Restore it with the approved keyring flow before claiming realtime health.
- Visual browser, console, keyboard-only and viewport validation remain open
  because no installed browser or browser-automation tool is available.

Latest Video Management runtime repair (2026-08-04):

- Native upstream RTSP deletion calls are now adapted at
  `/compat/agent/api/v1/rtsp-streams/delete/{name}`. The gateway resolves the
  display name against the credential-free VIOS inventory and delegates to
  the stable-id deletion guard; `cam-01` remains protected.
- `cam-01` cards now use the project-owned `/api/v1/workspace/cameras/cam-01/live.mjpeg`
  presentation and expose an `Open Live` action, avoiding the upstream
  storage-timeline/VOD preview that was observed 1–2 minutes behind. The
  local presentation uses a 100 ms jitter buffer and leaky frame queue. It is
  low-latency, not a mathematical zero-latency guarantee.
- The camera-live process was started and the same-origin MJPEG endpoint
  returned HTTP 200 with a live multipart response. RT-CV metadata remains a
  separate on-demand/admission-controlled service and was not started as part
  of this UI repair.

Latest backend/runtime repair (2026-08-03):

- The real upload job `5564ae70…` exposed a race in which the UI saw a granted
  caption lease while Cosmos3 was still warming up and surfaced a generic
  service-unavailable error. The BFF now returns a durable queued state for
  provider standby, the UI labels the provider `warming`, and periodic summary
  refresh updates the action when the provider becomes ready. The job produced
  one real caption and is now `queued_summary`.
- GPU admission now requires a hard `10240 MiB` reserve, applies a serialized
  VLM launch budget, and runs a post-readiness reserve verification. The
  user-requested Cosmos3 window uses the pinned cache, valid compilation JSON
  and `gpu_memory_utilization=0.65`; live `nvidia-smi` verification reports
  `13452 MiB` free. External GPU processes were not stopped or modified.
- Summary provider state is intentionally still `standby` until the operator
  confirms the fixed Nemotron profile. This is an on-demand state, not a
  missing backend. The camera/RT-CV restore remains `PARTIAL` because the
  runtime-only physical camera secret is unavailable.

## Product outcome

The workspace shell follows the pinned upstream VSS 3.2.1 UI structure from
`third_party/video-search-and-summarization/services/ui`: a 75px light header,
260px toolkit-style workspace rail, New chat/folder/search controls, compact
neutral tab buttons, a mode-controls area and Import/Export/Settings footer.
Project-owned seven-route navigation, real same-origin adapters and the
persistent/resizable evidence assistant remain in that shell. The Overview
route still leads with Video Input, Summarization Prompt, Object Tracking
Prompt, Reset, Summarize media and Launch Agent controls. The shell uses local
CSS/system fonts and local SVG icons, with no CDN, external font, gradient,
iframe or generic external workflow launcher.

The Launchable-looking controls are backed by this project's contracts:

- Video Input uploads only to the CPU-only media-intake service, which validates
  MP4/MKV, H.264, size, filename and SHA-256 before preparing selected media.
- Summarize media and Launch Agent create a persisted Phase 13 job through the
  same-origin BFF with `store_id`, stable `camera_id`, UTC bounds, schema
  version, asset URI and content SHA-256.
- Prompt/model fields are displayed as server-controlled because Phase 13 does
  not authorize browser prompt or model overrides. They are never silently
  sent as unsupported fields.
- Opening Agent attaches the persisted summary context to the real evidence
  assistant; creating a job does not start a model or switch a GPU profile.
  After the operator confirms a managed summary profile, the host worker owns
  the bounded GPU window and restores realtime when that exact job checkpoint
  completes.

The shell includes:

- store, UTC/local clocks, global health, GPU mode, theme, refresh and session
  controls;
- semantic landmarks, skip link, visible focus, live regions, dialogs and
  keyboard/Escape handling;
- responsive layouts for desktop, tablet and mobile;
- explicit loading, empty, offline, retry, provider-standby, queued-for-GPU,
  partial, no-evidence and failure states;
- DOM construction through `textContent`/`createTextNode`, not API-derived
  `innerHTML`;
- same-origin media URLs derived only from validated stable IDs.

No NVIDIA logo was added. The header identifies NTC and says the application
is powered by NVIDIA VSS 3.2.1 on an experimental single-GPU topology. It does
not imply NVIDIA validation or certification.

## Real and feature-gated capabilities

| Area | Implemented against a real contract | Deliberately feature-gated |
| --- | --- | --- |
| Overview | Minimal NVIDIA-style single workflow: upload/prepared video, persisted VLM job, inline caption/summary answer and the next admitted GPU action in the same view | No synthetic result when an upstream does not supply it; prompt/model overrides remain server-controlled |
| Camera | Active credential-free physical-only registry and VIOS registration/state for stable `cam-01`; the camera wall is no longer public navigation | Replay fixtures remain recoverable for historical tests but are not active sources or default Compose services |
| Search | Existing action, attribute, fusion and agent/auto search; stable camera IDs; UTC/score BFF post-filters; bounded top-K; critic normalization; exact selected-clip playback | Browser image-search selection is gated because no safe frame/bbox discovery contract exists, although the backend image route remains available |
| Summary & Q&A | Persisted Phase 13 selected-clip/time-window jobs plus validated uploaded MP4 preparation, selection, quarantine/restore, state/actions/retry, evidence/timestamps, coverage gaps and grounded/refused Q&A | MKV remux, raw/live-stream summary, image summary, client prompt/model overrides, arbitrary chunking and highlights have no contract |
| Alerts | Hybrid/direct lists, exact evidence modal, feedback, versioned queue update and audited/idempotent tombstone/restore with retained media references | Direct feedback, acknowledge/assign, and rule/zone create/delete/reshape are not claimed |
| Reports | Existing incident/shift/daily records, exact-context creation, deduplicated interactive evidence playback scoped to report/store, sanitized Markdown and JSON/Markdown download | PDF |
| Global AI drawer | Exact camera/clip/alert/search/summary context chips; evidence-first selected-media resolution; exact single-asset summary reuse or real Phase 13 job preparation; structured required-profile actions; deterministic read-only system router; semantic search only without exact evidence; grounded/refused Q&A; local greeting guidance; session-scoped history and cancel/timeout states | It is not an unrestricted chatbot, does not expose chain-of-thought, does not stream when the backend does not stream and never starts or switches a model merely by opening/asking |
| System & GPU | Service/port registry, phase status, audit, telemetry, leases, fixed profile catalog, explicit confirmation, serialized host worker and realtime recovery action | No arbitrary command/profile/path; unknown leases fail closed |

The minimal upload view derives required summary provenance without exposing
camera/time fields: `cam-01` is fixed, upload `created_at` is the UTC start and
same-origin MP4 metadata supplies duration/UTC end. Candidate cards expose the
existing confirmed soft-delete path; deletion tombstones the alert while
retaining evidence and references.

Direct RT-VLM alerts are answer-only when their authoritative contract has
`media_available=false`; the UI does not synthesize a clip URL or render a
broken video box. Hybrid records render a player only for an allowlisted
selected-media ID. Overview job/provider state re-renders on the 15-second
poll, and the upload selector orders the latest prepared asset first.

“Implemented against a real contract” means the browser and BFF call the
existing service contract without mock data. It does not mean every provider
was running during this refinement. Provider standby and service-down results
must remain visible and must not be relabeled as completed inference.

## Same-origin BFF

The browser calls only port 39510. `services/api/workspace.py` contains fixed
adapters for:

- camera presentation on 8090;
- VIOS/VST inventory and selected pictures on 30888;
- behavior analytics on 39110;
- alert verification on 39120;
- incidents/selected-media preparation on 39121;
- direct RT-VLM results on 39210;
- semantic search on 39310;
- summarization/Q&A/reports on 39410.
- CPU-only uploaded-media intake/preparation/quarantine on 39420.

`#/sources` is retired and redirects to `#/cameras`. Camera renders only
registered stream sources. Alert/summary/report selected clips are evidence,
not sources, and are visible only in their owning workflows.

## Blueprint-aligned service lifecycle

The public NVIDIA Blueprint separates realtime intelligence, downstream
analytics and agent/offline workflows. This project keeps the same boundary
while exposing one browser origin:

| Plane | Services/ports | Default state | Transition rule |
| --- | --- | --- | --- |
| Video/control | RTSP relay 39554, camera/live 8090, RT-CV 39000/39080, behavior 39110, alert/incident 39120/39121 | Always on (or replay/registered-source state) | RT-CV may be paused only during an explicitly confirmed GPU window; relay/video playback remains available |
| CPU control plane | Search 39310, summarization/Q&A 39410, media intake 39420, unified BFF 39510 | Always on | `scripts/ensure-control-plane.sh` reconciles these without starting any GPU profile |
| GPU/on-demand | RT-Embedding 39320, SigLIP 39321, Cosmos3/Nemotron 30082/30081, direct RT-VLM 39200/39210 | Standby/off until admitted | A single confirmed lease starts a fixed profile; no browser action silently switches it. Managed jobs stop/revoke the provider after their checkpoint and restore RT-CV |

All published project ports bind to loopback. The browser calls only 39510;
the BFF uses fixed allowlisted adapters for internal ports. The Blueprint card
and repository do not imply that every model container is continuously loaded;
on-demand admission is the safe single-GPU behavior for this experimental
RTX PRO 5000 Blackwell topology.

Uploaded files enter a separate project-owned media plane:

```text
browser on 39510
  -> fixed media-intake adapter on 39420
  -> validated active upload + prepared-media manifest
  -> read-only `uploaded-media://` mount in Phase 13
```

The Phase 15 unified API has no upload/raw-media mount. MP4/MKV MIME,
container and H.264 markers, filename, size and SHA-256 are validated.
Supported MP4 is prepared for Summary. MKV remains catalogued but explicitly
non-summary-ready because no remux binary exists in the pinned runtime.

`POST /api/v1/workspace/assistant/evidence` accepts one bounded exact
clip/alert/search-result/summary context. For clip and alert contexts it:

- resolves the asset through the in-memory allowlist populated only by trusted
  selected-media workflows;
- verifies exact camera, UTC bounds and content SHA-256 provenance;
- reuses only a completed summary whose asset set is exactly that one clip;
- otherwise creates or returns the real persisted single-clip Phase 13 job;
- returns `summary_caption` for queued caption work or `summary_reasoning` for
  queued summary/Q&A provider standby;
- never calls semantic search and never calls GPU control.

The browser renders the required profile and invokes the existing fixed-profile
confirmation/RBAC flow only after an operator presses the action.

There is no generic proxy endpoint and no request field selects an upstream
host, port or arbitrary path. The adapter:

- disables environment proxies and upstream redirects;
- restricts camera, stream, alert, job, report and media identifiers;
- verifies `store_id`, schema version and stable `camera_id` on relevant
  responses;
- caps JSON at 2 MiB, thumbnails at 5 MiB and binary media/report responses at
  64 MiB;
- normalizes upstream rejection, standby, timeout, invalid JSON and oversized
  responses;
- emits structured operation/status/latency/byte logs without secrets,
  authorization headers, cookies, camera URIs or sensitive filenames;
- serves exact allowlisted selected/report/upload media IDs and supports one
  HTTP byte range;
- exposes only exact JSON/Markdown report IDs;
- forwards bounded binary uploads only to the fixed media-intake service; it
  does not mount or persist uploaded raw data itself.

OpenAPI 3.1 contract version `1.5.0` documents the workspace, session and
existing system/GPU routes at `/openapi.json`.

## Architecture and data policy

The media path remains:

```text
camera/raw recording
  -> existing VIOS or media selection/preparation
  -> selected-media reference
  -> search/verification/summary/report workflow
```

There is no raw-storage-to-event, embedding, summary or report path.

The Phase 15 container:

- is CPU-only;
- mounts no `runtime/raw-video`;
- mounts no selected-media directory;
- mounts no camera credentials;
- mounts no Docker socket;
- mounts no GPU device;
- mounts no model cache;
- reads only the credential-free camera registry, which contains stable IDs
  and secret references rather than plaintext credentials.

The selected-media BFF reads only exact assets returned by the existing
incident/media-preparation path. It never scans a raw archive.

Host networking is used because every existing upstream is intentionally
published on host loopback. The Python process refuses any bind other than
`127.0.0.1`, and requests must use the exact `127.0.0.1:39510` or
`localhost:39510` Host header. Mutations require JSON and same-origin Fetch
Metadata/Origin. CSP includes `media-src 'self'`, `object-src 'none'`,
`frame-ancestors 'none'` and same-origin connect policy. No permissive CORS was
added.

## Identity and mutation policy

The RBAC implementation and digest-only bearer store remain available, but
the current local PoC deployment deliberately sets
`PHASE15_TRUSTED_LOOPBACK_FULL_ACCESS=true`. Requests that reach the
loopback-only process therefore receive the trusted local admin identity.

This is not production authentication. Port 39510 must remain loopback-only.
Before any LAN, shared-host or production use, disable trusted-loopback access
and add approved identity/TLS controls.

Mutations remain narrow and audited:

- search and evidence Q&A use the existing tool-execution permission;
- feedback, summary job/action, report creation and analytics config changes
  require the operator-level GPU-control permission in the current API;
- analytics editing can only increment the current config version and change
  existing queue length/wait thresholds;
- GPU transition requires an online worker, a fixed catalog profile, explicit
  confirmation and no active transition;
- an unknown lease prevents transition rather than guessing a stop action.

No GPU-heavy model was admitted or started solely to produce UI evidence.

## Managed GPU lifecycle refinement

Phase 13 summary jobs can now carry an exact `managed_job_id` on an explicit,
operator-confirmed `summary_caption` or `summary_reasoning` GPU command. The
host-only worker stops RT-CV before the fixed provider profile starts, while
the CPU summarization service consumes queued jobs only when the matching
admission lease and provider are ready. Caption completion at
`queued_summary`, or final summary completion, triggers the allowlisted stop
script, lease revocation and RT-CV restore. Invalid IDs, profiles without a
managed summary job, unknown leases and missing confirmation fail closed.
The browser never silently switches a profile.

## Deployment change

`phase15-api` now uses `network_mode: host` and listens directly on
`127.0.0.1:39510`. There is no Compose `ports` publication. The health check
also uses `127.0.0.1:39510`.

This replaces the old bridge-network assumption. It enables the fixed BFF to
reach the real loopback services without exposing those ports to the browser.
It also creates one known observability limitation: the existing Prometheus
container still targets `phase15-api:8080`, which is no longer a valid
service-DNS target. Because Phase 15 binds only to host loopback, a container
scraper cannot reach it directly. The host-local `/metrics` endpoint remains
implemented, but the Prometheus target must be treated as pending until a safe
host-side scrape/relay design is approved. Do not bind Phase 15 to `0.0.0.0`
to make the scrape pass.

## Files in this refinement

Primary implementation:

- `apps/dashboard/index.html`
- `apps/dashboard/styles.css`
- `apps/dashboard/app.js`
- `tests/unit/test_phase15.py`
- `apps/dashboard/chat-routing.js`
- `services/api/service.py`
- `services/api/workspace.py`
- `services/api/README.md`
- `services/api/gpu_control.py`
- `services/gpu-control-worker/worker.py`
- `services/gpu-admission-controller/admission.py`
- `scripts/env.sh`
- `scripts/start-profile.sh`
- `scripts/start-phase13-vlm.sh`
- `scripts/phase13-lib.sh`
- `deploy/overlays/single-gpu-poc.compose.yml`
- `services/search/service.py`
- `services/summarization/service.py`
- `services/rt-cv/metadata_service.py`
- `deploy/compose/phase15.compose.yml`
- `schemas/openapi/phase15.openapi.json`

Validation/evidence:

- `tests/unit/test_phase15.py`
- `tests/unit/test_phase12.py`
- `tests/unit/test_phase13.py`
- `scripts/healthcheck-phase15.sh`
- `scripts/test-phase15.sh`
- `scripts/capture-phase15-evidence.sh`
- `artifacts/benchmarks/phase15-ui-refinement/before/`
- `artifacts/benchmarks/phase15-ui-refinement/after/`

Documentation:

- `docs/runbooks/phase15-app-recovery.md`
- `docs/handoffs/PHASE-15-HANDOFF.md`
- `PROJECT_STATE.md`

The pinned `third_party/video-search-and-summarization` tree was used as a
visual/interaction reference and was not edited for this refinement.

## Validation completed

- Full project unit regression: `161 passed`.
- `pytest -q tests/unit/test_phase15.py`: `56 passed`.
- `node --check apps/dashboard/app.js`: PASS.
- `node --check apps/dashboard/chat-routing.js`: PASS.
- Python HTML parser: PASS.
- `python -m json.tool schemas/openapi/phase15.openapi.json`: PASS.
- `docker compose -f deploy/compose/phase15.compose.yml config --quiet`: PASS.
- `scripts/healthcheck-phase15.sh`: PASS after restarting the stale RT-CV
  metadata consumer; the unified API, media intake, Search CPU API, Summary
  CPU API and GPU control worker are healthy.
- Post-alignment source validation: `56 passed` in the targeted Phase 15
  contract suite and `161 passed` in the full project regression. JavaScript
  syntax and Python HTML parsing pass; the running dashboard serves the new
  New chat/Search/Import/Export/Settings shell with HTTP 200.
- Backend repair validation: `57 passed` for Phase 15 and `164 passed` for the
  full project regression (`120 passed` across the Phase 10–15 targeted
  suites, Python/JavaScript syntax checks passed, the real API returned
  `202 waiting_for_provider` instead of failing a queued summary action during
  standby, Cosmos3 `/v1/health/ready` returned `200`, Summary state reported
  `caption_provider=available`/`caption_admission=true`, and the GPU reserve
  verification reported `13452 MiB` free against `10240 MiB` required. A real
  short selected/uploaded job action returned `queued_summary` with one
  completed caption through the live BFF/provider.
- A current runtime healthcheck rerun remains `PARTIAL`: the CPU control
  plane and UI are healthy, but `ready=false` because the approved physical
  `cam-01` keyring secret is unavailable. No credential or synthetic live
  source was introduced; this is the existing camera-runtime blocker, not a
  UI inference result.
- The follow-up sidebar fix uses a dedicated
  `phase15.upstreamSidebarCollapsed` preference and a fixed desktop rail,
  preventing the previous shell's collapsed state or sticky scroll container
  from hiding/offsetting the left navigation. Cache-busted assets are now
  `phase15-upstream-ui-3`; a visible `Thu gọn sidebar` control was added to
  the rail while the header hamburger remains the reopen control. Targeted
  and full regression remain green.
- Direct RT-VLM is explicitly `on_demand` in the service registry. When it is
  not admitted, the control plane reports `standby` rather than a false
  always-on outage. Dashboard cache-busted assets are at
  `phase15-upstream-ui-3`, with an HTML boot fallback and direct workflow
  links to prevent a silent blank workspace.
- The fixed sidebar/grid placement was corrected after browser review: the
  fixed rail no longer consumes the main grid item, so the main route is
  explicitly placed in column 2 and the chat drawer in column 3. The header
  hamburger is the only collapse/expand control; the duplicate large sidebar
  launcher is hidden. This keeps all route content visible in both expanded
  and icon-only rail states.
- On 2026-08-03, following an explicit user request, the dashboard shell was
  aligned to the cloned upstream VSS 3.2.1 UI source. The project kept its
  seven deep links and same-origin BFF; only the presentation shell and
  toolkit-style sidebar controls were adapted. The browser-facing HTML now
  contains New chat, folder, Search, Import data, Export data and Settings
  controls. Unsupported chat folders/import are surfaced as feature-gated
  instead of creating fake backend state; session export is local and
  data-preserving.
- Dashboard, CSS, JavaScript, OpenAPI and same-origin workspace routes return
  HTTP 200 on port 39510.
- Runtime was started with `make phase15-start` after a secret-safe Docker
  image/container/disk inventory. Camera registry returned ten sources,
  workspace returned `store-001`/schema `1.0.0`, OpenAPI returned version
  `1.4.0`, and the dashboard contained the new Video Input/Launch Agent shell.
- The media-intake upload list, Phase 12 Search API and Phase 13 Summary API
  were reachable and healthy after restarting only their CPU services. Their
  model providers remain unavailable/standby without admission leases; the UI
  keeps those actions fail-closed and does not claim inference.
- Real Evidence Assistant smoke resolved hybrid alert `8e3a91ce…` to its exact
  selected clip and digest, created one persisted Phase 13 job `0620d8fa…` in
  `queued_caption`, returned `required_profile=summary_caption` and no answer,
  and returned the same job with `created=false` on repeat. No GPU profile was
  activated and no VLM/LLM completion is claimed.
- Real upload smoke sent MP4 H.264 asset `8b7f84b0…` through port 39510,
  received an authoritative SHA-256/prepared manifest and a 206 byte Range,
  then created persisted Phase 13 job `4cbfb150…` in `queued_caption`.
  Quarantine/restore passed for separate uploaded asset `8d22eef6…`.
- Real alert governance smoke soft-deleted and restored Direct alert
  `bc252841…`; the audit path was used and no evidence file was removed.
- Real report evidence `a5fea5fc…` returned 206 through report `0469d0ef…`;
  an asset outside the same report returned 403
  `report_media_scope_denied`.
- Camera inventory returned ten registered sources: only `cam-01` is physical
  and browser-live; after metadata consumer recovery its AI state is connected
  with fresh UTC metadata, ~25 FPS and track IDs.
  `cam-02`–`cam-10` are replay sources without
  fabricated browser-live/AI state.
- The 2026-08-03 recovery smoke found RT-CV core decoding at ~25 FPS while the
  metadata consumer had failed with `NoBrokersAvailable`. Restarting only
  `rtcv-metadata` reconnected Kafka; `/health/ready` became 200, metadata
  frames/track IDs advanced and `scripts/healthcheck-rtcv.sh` plus
  `scripts/healthcheck-behavior-analytics.sh` passed. No GPU-heavy profile was
  started to hide a failure. The later Cosmos3 start was an explicit
  user-requested runtime repair, not a visual-evidence shortcut, and it
  passed the reserve gate.
- The `cam-01` same-origin MJPEG request transferred a multi-megabyte body
  during the bounded five-second capture. An allowlisted selected MP4 returned
  `206 Partial Content`, `Content-Range: bytes 0-1023/2195615` and
  `Content-Type: video/mp4`.
- Manual action search returned three real `cam-01` selected clips with
  `provider_sources.action=cache`; critic stayed unavailable and results
  stayed unverified. No unleased provider was called.
- An explicit ad-hoc Phase 10 smoke selected a real RT-CV candidate from the
  requested 03/08/2026 08:30–13:44 Asia/Ho_Chi_Minh window (`10:24:45.791`
  local), created incident
  `02b64ed28dd73dfc6e0637976f4ec80010e75f855725b5afc8a87e8e1f77a6a4` and
  prepared one selected clip. The candidate contract and VIOS/media
  preparation path passed. The serialized Cosmos3 local window did not pass:
  the pinned cache loaded, but the NIM exited `137` during full CUDA graph
  capture before stable readiness, so no VLM request or visual description was
  claimed. RT-CV and CPU Phase 10 services were restored healthy and the VLM
  lease was revoked. This remains `PARTIAL`; it does not change the last
  approved phase or open Phase 16. Detailed evidence is in
  `artifacts/evals/phase10/adhoc-20260803-vlm-smoke.md`.
- A follow-up smoke later on 2026-08-03 used a fresh real RT-CV
  `queue.threshold` event and VIOS-selected clip. Cosmos3 ran with bounded
  context and CUDA graph capture disabled, then returned actual HTTP
  inference: verification `rejected`, confidence `0.98`, plus a Vietnamese
  visible-activity description. This proves the selected-clip-to-VLM gate for
  the smoke. The production verifier consumer was intentionally stopped to
  avoid historical Kafka backlog, so no persisted `verified` alert or full
  consumer-group PASS is claimed. RT-CV was restored healthy and the VLM lease
  revoked; evidence is in the same ad-hoc smoke artifact.
- Phase 13 Q&A returned one grounded `evidence_extract_fallback` response with
  three cited evidence items and one exact refusal (`không đủ dữ liệu`) with
  an empty evidence list while Nemotron was not admitted.
- All 80 captured Phase 15 service-log lines parsed as standalone JSON.
- Backup/isolated restore now includes and compares `service.py` and
  `workspace.py`; `scripts/test-phase15-restore.sh` passed.
- Tests cover:
  - the seven-route shell, safe legacy Sources redirect and absence of
    external workflow tabs/iframes;
  - safe DOM sinks;
  - fixed-loopback upstream allowlist and SSRF rejection;
  - response-size limits and normalized provider errors;
  - truthful physical/replay camera capability states;
  - search identity, filters, post-filtering and result normalization;
  - grounded/refused Q&A and report path redaction;
  - selected-media allowlist and Range parsing;
  - alert tombstone/restore/idempotency/reference retention;
  - uploaded asset validation/path traversal/quarantine/restore;
  - report-scoped evidence access and cross-store denial;
  - CSP media/object restrictions;
  - host-network loopback configuration and forbidden-mount absence;
  - GPU confirmation, serialization and unknown-lease fail-close.

These tests use mocks only as unit/contract fixtures. They are not evidence
that an external service, camera, NIM, LLM, VLM or GPU ran.

## Remaining validation gates

The following gates remain deliberately open:

- [ ] verify live video continues when AI is already in a policy-compliant
  paused state, without starting a heavy model only for validation.
- [ ] run screenshots, console inspection, keyboard-only navigation and
  viewport checks at 1920×1080, 1440×900, 1024×768, 768×1024 and 390×844 in an
  approved existing browser environment.
- [ ] approve and implement a safe scrape/relay for the stale Prometheus
  `phase15-api:8080` target without broadening the loopback bind. The design
  is proposed in `docs/decisions/ADR-008-phase15-metrics-relay.md` and is not
  approved.
- [ ] run the Phase 15 unit suite, healthcheck and restore test against the
  2026-11-19 source-only Real-time Alerts wiring changes.

Do not fill these items from unit mocks or older launcher evidence.

## Browser evidence limitation

No installed Chromium, Chrome, Firefox, Playwright, Puppeteer,
`wkhtmltoimage`, or browser MCP was available before implementation. Per the
disk/dependency policy, no large browser package was downloaded solely for
screenshots.

The `before/` directory contains the previous deployed HTML/CSS/JS and an HTTP
status record, not a visual screenshot. At this checkpoint there is no
post-refinement browser screenshot, console log, keyboard-only run or verified
1920×1080, 1440×900, 1024×768, 768×1024 and 390×844 capture. Those visual
accessibility/responsive gates remain `PARTIAL` and require an existing
approved browser environment or manual operator validation.

Older files under `artifacts/benchmarks/phase15-unified-app/` describe the
pre-refinement launcher and must not be cited as evidence for this UI.

## Known limitations

1. Phase 15 remains `PARTIAL`; this UI refinement does not open Phase 16.
2. Phase 14 Retail AI remains `LOCKED_BY_USER`; no retail workflow or evidence
   was fabricated.
3. Phase 08 physical ten-camera scale remains deferred. The active runtime now
   contains only physical `cam-01`; replay sources are stopped and are not
   physical capacity evidence.
4. The RTX PRO 5000 Blackwell serialized topology is experimental and is not
   NVIDIA-validated for this VSS topology.
5. Visual browser, console, keyboard and viewport evidence is unavailable.
6. Prometheus cannot currently scrape the host-loopback-only Phase 15 process
   through the stale `phase15-api:8080` target.
7. The previous unleased Phase 11/12 GPU provider processes were stopped with
   their project stop scripts on 2026-08-03; images, model caches and data were
   preserved. Only the result collector remains running without a GPU device.
8. A prior 2026-08-03 evidence checkpoint confirmed RT-CV live for `cam-01`
   (`stream-count=1`, ~25 FPS, fresh metadata and track IDs). The latest
   recovery cannot re-register the physical stream because the approved
   runtime-only camera secret is missing; the UI correctly reports the
   always-on camera service as unavailable rather than substituting a fake
   stream. Re-materialize the keyring secret, then run `scripts/start-rtcv.sh`.
9. Trusted-loopback admin has no production identity/session boundary.
10. Browser camera onboarding is unavailable. Uploaded-video delete is
   quarantine/restore; physical purge is intentionally absent.
11. Browser search-by-image selection is gated despite the existing backend
    image route.
12. Summary accepts only selected media; general live and image summary do not
    exist.
13. Global chat is a context router to system status, search and grounded Q&A,
    not a free-form always-on model session.
14. The standard-library HTTP server remains a PoC control plane; production
    TLS/identity, distributed tracing and DCGM integration are absent.
15. The working tree has no established commit baseline. The Phase 15 archive
    now covers the complete project-owned API adapter source, but rollback
    still requires an exact verified archive rather than destructive Git.
16. The public NVIDIA Launchable prompt controls are presentation-only in this
    project because the current Phase 13 contract locks prompts/models on the
    server. A future prompt-override capability requires a versioned backend
    contract, admission policy and tests before the controls can be enabled.

## Rollback and recovery

Operational rollback is narrow and data-preserving:

```bash
make phase15-stop
```

This stops only the unified app and requests the Phase 15 worker to stop. It
does not change the active GPU workload or delete any backend, recording,
selected media, report, index, audit record, lease, image, volume, model or
cache.

Before source rollback:

```bash
make phase15-backup
make phase15-restore-test
```

The verified Phase 15 archive now includes the dashboard plus the complete
project-owned API adapter, the touched search/summarization services, tests,
Compose, registry/security helpers, OpenAPI, documentation, GPU worker/control
and audit state. It is a known-good recovery snapshot of this refinement, not
a fabricated pre-refinement Git baseline. An exact UI-only pre-refinement
snapshot is also available under
`artifacts/benchmarks/phase15-ui-refinement/before/`; the recovery runbook
documents the exact three-file restore and its consequence of returning to
multi-port launcher behavior. Never use a hard reset or destructive Docker
cleanup.

See `docs/runbooks/phase15-app-recovery.md` for recovery, media allowlist,
host-network, Prometheus and validation details.

## Evidence locations

Current NVIDIA VSS UI replacement capture:

- `artifacts/benchmarks/phase15-vss-ui/after/`
- `artifacts/benchmarks/phase15-vss-ui/after/vss-ui.html`
- `artifacts/benchmarks/phase15-vss-ui/after/vss-ui-env.js`
- `artifacts/benchmarks/phase15-vss-ui/after/ui-container-isolation.json`
- `artifacts/benchmarks/phase15-vss-ui/after/gpu-state.csv`
- `artifacts/benchmarks/phase15-vss-ui/after/unit-tests.txt`

Existing pre-refinement capture:

- `artifacts/benchmarks/phase15-ui-refinement/before/dashboard.html`
- `artifacts/benchmarks/phase15-ui-refinement/before/styles.css`
- `artifacts/benchmarks/phase15-ui-refinement/before/app.js`
- `artifacts/benchmarks/phase15-ui-refinement/before/http-status.txt`
- `artifacts/benchmarks/phase15-ui-refinement/before/sha256.txt`
- `artifacts/benchmarks/phase15-ui-refinement/before/browser-tooling.txt`

Historical custom-shell refinement capture:

- `artifacts/benchmarks/phase15-ui-refinement/after/`
- `artifacts/benchmarks/phase15-ui-refinement/after/evidence-assistant-routing-smoke.md`
- `artifacts/benchmarks/phase15-ui-refinement/after/launchable-ui-contract.md`
- `artifacts/benchmarks/phase15-ui-refinement/after/gpu-lifecycle-smoke-20260803.md`

## Exact next permitted action

Complete only the remaining approved-browser and Prometheus integration gates,
preserve Phase 15 as `PARTIAL`, and ask the user to review this Phase 15
refinement. Do not begin Phase 16 without a new explicit user instruction. Do
not unlock Phase 14. Do not mark Phase 08 complete.

## Approval required

YES.
