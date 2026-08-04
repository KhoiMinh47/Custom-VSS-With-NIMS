# Phase 15 unified API

CPU-only control plane for the project dashboard. It reads an allowlisted
service/port registry, probes loopback-only dashboards, exposes a stable
versioned API, reads GPU admission leases and queues explicitly confirmed GPU
profile switches for the separate host worker. It writes structured audit
records for tool calls, profile requests and denied actions.

The API container does not mount Docker's socket, camera credentials, selected
media or raw video. In bearer-RBAC mode anonymous sessions are limited to the
`viewer` role. The loopback-only PoC deployment deliberately enables its
existing trusted-local admin session; it is protected by an exact local Host
allowlist, same-origin mutation checks and a process bind to `127.0.0.1`.
Operator, model-engineer or admin access is required to switch a profile.
Bearer token SHA-256 digests are stored in the ignored operator file
`.secrets/phase15/token-hashes.json`.

MCP-style tools remain read-only. GPU mutation is a separate narrow control
surface: the API accepts only catalog profile IDs, requires a confirmation,
serializes requests and passes them through a project-local queue. The host
worker can call only fixed existing start/stop scripts and fails closed for an
unknown active lease. It never routes raw storage directly to an AI output.

For Phase 13, a confirmed GPU command may also carry one exact persisted
`managed_job_id` plus `auto_restore=true`. Only `summary_caption` and
`summary_reasoning` accept this lifecycle binding. The host worker waits for
the corresponding checkpoint, stops the provider, revokes its lease and
restores the realtime profile. Unbounded IDs, other profiles and unconfirmed
commands are rejected.

## Same-origin workspace adapters

The Phase 15 refinement serves the operator workspace and its browser-facing
API from `http://127.0.0.1:39510`. The container uses host networking and the
process itself is required to bind to `127.0.0.1`; this is necessary because
the existing services are intentionally published on host loopback only. The
compose service has no published port, Docker socket, GPU device, model/cache,
raw-video, selected-media or camera-secret mount. Its only camera input is the
credential-free registry containing stable IDs and secret references.

`/api/v1/workspace` is a bounded BFF, not a generic reverse proxy. Upstream
hosts and paths are fixed in source and requests cannot provide a URL, host or
port. JSON responses are limited to 2 MiB, selected media and report responses
to 64 MiB, and thumbnails to 5 MiB. Upstream failures are normalized to a
small response containing `code`, `service_id`, `retryable` and `request_id`.
Structured upstream logs contain operation names, status, byte count and
latency, but never authorization headers, cookies, tokens, camera URIs or
uploaded filenames.

Redirects and proxy environment variables are disabled for all upstream
requests, preventing a fixed service from redirecting the BFF outside the
loopback allowlist. Mutation bodies must be `application/json`; cross-origin
`Origin` and Fetch Metadata values are rejected for mutations and workspace
GET/media/live requests. Media responses carry same-origin resource policy
headers. Search and grounded Q&A use the existing analyst tool permission;
persisted feedback, job/action and report mutations require operator-or-higher
access. Successful, rejected and provider-failed mutation attempts are
audited.

The adapter surface is:

- `GET /api/v1/workspace` for capability/bootstrap state.
- `GET /api/v1/gpu-control/models` and
  `POST /api/v1/gpu-control/models/{llm|vlm}` for admission-controlled model
  power controls. These are host-worker commands; the browser never invokes
  Docker directly. RT-CV remains upload-workflow-only.
- `GET|POST /api/v1/workspace/stream-sources` and
  `DELETE /api/v1/workspace/stream-sources/{source_id}` for the Video
  Management `Upload Stream` control. The gateway returns only credential-free VIOS inventory;
  submitted RTSP URLs are forwarded to the fixed VIOS adapter and are never
  returned to the browser or written to the project camera registry. Stable
  `cam-01` cannot be deleted by this surface. The upstream VSS delete call
  `DELETE /compat/agent/api/v1/rtsp-streams/delete/{name}` is also adapted to
  this same guarded source-id path, so the native Video Management Confirm
  action deletes managed sources without requiring a request body.
- `GET /api/v1/workspace/cameras` and
  `/cameras/{camera_id}/state|live.mjpeg|thumbnail.jpg`. The `cam-01`
  presentation uses the local MJPEG path with a 100 ms RTSP jitter buffer and
  a leaky two-frame queue; it is separate from the delayed VST storage
  thumbnail/VOD path.
- `GET /api/v1/workspace/analytics/state|events|config` and operator-only
  `PUT /api/v1/workspace/analytics/config`. The current safe editor can only
  increment the config version and change the existing queue length/wait
  thresholds; rule creation, deletion, reshaping and connection fields are
  rejected.
- `GET /api/v1/workspace/incidents/state` and
  `GET /api/v1/workspace/alerts`; feedback is posted to
  `/alerts/{hybrid|direct}/{alert_id}/feedback`.
- `GET /api/v1/workspace/media/{selected_clip_sha256}.mp4`; only media IDs
  discovered from trusted incident, alert, search or summary responses are
  accepted. Single HTTP byte ranges are synthesized even when the fixed
  upstream returns a full response.
- `GET /api/v1/workspace/search/state` and
  `POST /api/v1/workspace/search`.
- `POST /api/v1/workspace/assistant/evidence` resolves one exact attached
  clip/alert/summary through selected-media provenance, reuses an exact
  single-asset completed summary or prepares a persisted Phase 13 job. It
  never calls search or switches GPU; queued work returns the fixed required
  profile for the existing confirmed operator action.
- Summary job state, creation, actions and grounded Q&A under
  `/api/v1/workspace/summaries`.
- Report list, creation and JSON/Markdown download under
  `/api/v1/workspace/reports`.

Camera inventory responses deliberately omit stream URIs and secret
references. `cam-01` is the only stable camera in the current
`physical_camera_only` registry and the only source with a previously proven
browser-live/RT-CV path. Historical replay profiles remain recoverable but are
not currently registered and are not physical-camera capacity evidence.

Summary creation additionally binds every selected clip to authoritative
camera, UTC bounds and content SHA-256 observed in a validated alert or
persisted job. Supplying a known media ID with relabeled camera/time provenance
is rejected before Phase 13 receives the request.

Video upload uses the project-owned CPU-only media-intake API and prepared
selected-media mount; it does not expose raw storage to this control plane.
Camera onboarding remains feature-gated because no browser-safe
secret-reference write contract is approved. Image summarization and general
live-stream summarization are also not exposed. These limits preserve the
raw/video plane boundary rather than simulating successful ingest or
inference.
