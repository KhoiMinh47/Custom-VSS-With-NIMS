# Phase 15 unified workspace recovery

## Scope and safety

This runbook covers the Phase 15 NVIDIA VSS UI served at
`http://127.0.0.1:39510/`. It is the pinned upstream UI behind a CPU-only,
same-origin gateway and bounded BFF. It is not Phase 16.

The Phase 15 process uses host networking so its fixed adapters can reach the
existing loopback-only services. The process is required to bind to
`127.0.0.1:39510`; do not change it to `0.0.0.0` to work around a connectivity
problem. The current deployment grants trusted-loopback admin access and must
never be exposed to a LAN or the Internet.

Recovery must preserve the independent video/raw-storage plane and all model
state. Never use Docker/image/builder/volume prune, `docker compose down -v`,
`docker rmi`, `docker volume rm`, or delete model caches, raw recordings,
selected media, indices, reports, audit records or admission leases.

Stopping Phase 15 does not stop the active backend or GPU workload. It only
stops the unified API container and asks the project-local GPU control worker
to stop. If the worker is completing a transition, its stop script leaves it
running rather than interrupting the transition.

## Expected topology

- Browser origin: `http://127.0.0.1:39510`.
- Gateway bind: `127.0.0.1:39510` inside a host-network container.
- NVIDIA Next.js UI bind: `127.0.0.1:39511`, reached through the gateway for
  normal browser use.
- Browser API prefix: `/api/v1/workspace`.
- Fixed internal upstreams: ports 8090, 30888, 39110, 39120, 39121, 39210,
  39310, 39410 and CPU-only media intake 39420 on loopback.
- Live browser preview: `cam-01` only.
- Active registry and VIOS inventory: `cam-01` only.
- `cam-02` through `cam-10` remain historical replay fixtures only. The
  `simulated-cameras` service requires the explicit `simulated` Compose profile
  and must not be started by the default physical-camera recovery path.
- NVIDIA UI mounts: none. Phase 15 gateway mounts: project API/config,
  credential-free camera registry, admission state, Phase 15 runtime state and
  digest-only secret directory.
- Forbidden mounts: raw video, selected-media storage, camera credentials,
  Docker socket, GPU devices and model caches.

The BFF is not a generic proxy. Upstream service IDs and paths are fixed in
source; redirects and proxy environment variables are disabled. Do not add a
user-supplied URL as a recovery shortcut.

## Read-only triage

From the project root:

```bash
source scripts/env.sh
make phase15-config
docker compose -f deploy/compose/phase15.compose.yml ps
curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:39510/health/live
curl --fail --silent --show-error --max-time 8 \
  http://127.0.0.1:39510/health/ready
curl --fail --silent --show-error --max-time 20 \
  http://127.0.0.1:39510/api/v1/workspace
```

If port 39510 is unavailable, identify its owner without killing anything:

```bash
ss -ltnp 'sport = :39510'
docker logs --since 15m ntc-vss-phase15-api
```

If another process owns the port, do not terminate it automatically. Record
the exact process/container and resolve ownership with the operator.

Check the local worker without changing the GPU profile:

```bash
sed -n '1,200p' runtime/phase15/gpu-control/worker.json
sed -n '1,200p' runtime/phase15/gpu-control/state.json
tail -100 runtime/phase15/gpu-control/worker.log
find runtime/gpu-admission -maxdepth 1 -type f -name '*.lease' -print
```

Do not print the digest store, authorization headers, cookies, camera URIs or
environment secrets while collecting diagnostics.

## Recovery: stopped or unhealthy Phase 15 container

First validate source/config without changing backend workloads:

```bash
source scripts/env.sh
make phase15-config
python -m json.tool schemas/openapi/phase15.openapi.json >/dev/null
python -m py_compile services/api/service.py services/api/vss_ui.py
python -m pytest -q tests/unit/test_phase15.py
```

Then perform the narrow restart:

```bash
make phase15-stop
make phase15-start
make phase15-health
```

`make phase15-start` checks base infrastructure, starts the allowlisted host
worker, resolves the Compose configuration, starts the pinned `vss-ui`,
`phase15-api` and the CPU-only `media-intake` companion, and waits for both
`127.0.0.1:39511/` and `127.0.0.1:39510/health/ready`. It does not admit or start a heavy
LLM/VLM profile.

If startup still fails, inspect the service log and the exact read-only
mounts. Do not replace missing mounts with broad project-root or raw-storage
mounts:

```bash
docker logs --since 15m ntc-vss-phase15-api
docker logs --since 15m ntc-vss-phase15-ui
docker inspect ntc-vss-phase15-api --format '{{json .Mounts}}'
docker inspect ntc-vss-phase15-ui --format '{{json .Mounts}}'
docker inspect ntc-vss-phase15-api --format '{{.HostConfig.NetworkMode}}'
```

The expected network mode is `host`. The expected HTTP environment is
`HTTP_HOST=127.0.0.1` and `HTTP_PORT=39510`.

## Recovery: shell loads but a workspace component is unavailable

`GET /api/v1/workspace` is intentionally partial-failure tolerant. A failed
camera, analytics, incident, search or summary adapter is returned as an
unavailable component with a normalized `code`, `service_id` and `retryable`
flag. The UI must not replace it with mock data.

Use the component state endpoints to isolate the failure:

```text
GET /api/v1/workspace/cameras
GET /api/v1/workspace/analytics/state
GET /api/v1/workspace/incidents/state
GET /api/v1/workspace/search/state
GET /api/v1/workspace/summaries/state
GET /api/v1/workspace/uploads?deleted=exclude
```

Then use the owning phase's health/runbook. Do not restart unrelated services
and do not switch a GPU profile simply because a page was opened.

- A search or summary provider in standby is not proof of failure. CPU state,
  persisted jobs and cached results can remain available while the admitted
  LLM/VLM is stopped.
- `paused_for_gpu` on RT-CV can be policy-compliant during an admitted model
  window. Live video must remain independent.
- If an unknown lease exists, leave GPU control fail-closed and follow
  `docs/runbooks/gpu-control-center.md`.
- To deliberately restore the accepted realtime profile, obtain operator
  confirmation and use the existing GPU control workflow or
  `make alerts-default-start`; do not run it as an automatic UI recovery step.

## Recovery: camera or evidence playback

For `cam-01`, check camera state before opening the MJPEG stream:

```text
GET /api/v1/workspace/cameras/cam-01/state
GET /api/v1/workspace/cameras/cam-01/live.mjpeg
```

An offline RT-CV state must not stop or hide an otherwise available live
video. `cam-02` through `cam-10` are expected to report the real replay/no
browser-preview capability instead of reusing `cam-01`.

Selected-media playback accepts only an exact 64-character lowercase SHA-256
ID previously discovered from an allowlisted incident, alert, search or
summary response. After a BFF restart its in-memory allowlist is rebuilt from
trusted workflow responses. Reload the owning alert/job or rerun the exact
search before retrying playback. Never point the BFF at raw storage.

The media route supports one HTTP byte range. A multi-range or out-of-bounds
request correctly returns 416. Do not disable the range/size checks to make a
malformed clip play.

Uploaded video recovery is independent of alert evidence:

- active/prepared/quarantine files are under
  `runtime/media-intake-data/`, mounted only by media-intake;
- Phase 13 sees only `runtime/media-intake-data/prepared` read-only;
- Phase 15 API forwards bounded bytes but has no raw-upload mount;
- delete moves the exact uploaded asset to quarantine and restore moves it
  back; neither operation targets `runtime/incidents/clips`;
- a summary reference returns 409 and must be resolved by policy rather than
  by deleting the job or evidence automatically.

Do not remove `runtime/media-intake-data`, its registry, or quarantine during
rollback. A source rollback must first restore a Phase 13 configuration that
does not reference `uploaded-media://`; existing uploaded jobs remain
historical records and must not be rewritten.

## Recovery: mutation rejected

Workspace mutations require `application/json`, a same-origin request,
matching `store_id=store-001`, schema version, stable IDs and any contract
specific idempotency key. Errors are intentionally normalized.

- Analytics rule editing can only increment `config_version` and update the
  existing queue length/wait thresholds. Connection fields and rule
  create/delete/reshape operations are rejected.
- Alert feedback requires the exact alert ID. The UI exposes feedback only
  where the upstream contract is proven.
- Summary creation accepts only selected-media assets and bounded UTC windows.
- Summary actions use fixed `caption`, `summarize` or `retry` IDs.
- Report creation accepts only incident, shift or daily JSON/Markdown
  contracts.
- GPU switching requires a fixed profile ID, explicit confirmation, one
  transition at a time and a healthy host worker.

Do not relax validation, add plaintext RTSP fields, or synthesize success
responses during recovery.

## Prometheus limitation after host-network migration

Direct host metrics remain available at
`http://127.0.0.1:39510/metrics` whenever Phase 15 is running. However, the
existing Prometheus job still targets `phase15-api:8080`, which belonged to the
old bridge-network deployment. The refined service now uses host networking
and binds only to host loopback, so the Prometheus container cannot resolve or
reach that old target.

Treat the `phase15-unified-api` scrape as a known pending integration gate, not
as proof that the host-local UI is down. Do not solve it by binding Phase 15 to
`0.0.0.0`, weakening trusted-loopback access, or adding permissive CORS. A
future approved solution needs a safe host-side scrape/relay or an explicitly
designed metrics endpoint.

The proposed design is a Unix-socket metrics relay with no new host listener:
[ADR-008](../decisions/ADR-008-phase15-metrics-relay.md). It is not approved
or implemented yet; the target remains pending.

## Real-time alert rules control plane

`make phase15-start` now also starts `alert-realtime-redis`
(`127.0.0.1:6380`) and `alert-realtime` (host loopback `9080`, pinned VSS
Alert Verification 3.2.0 tag shipped with VSS 3.2.1). Both are CPU-only, and
starting them never admits a GPU model. `make phase15-stop` stops them with
`docker compose stop`, preserving images and volumes. Rule persistence is
disabled in this overlay, so rules do not survive a restart. Creating a rule
returns `realtime_provider_unavailable` while the admitted Cosmos3/RTVI
provider is not running.

## Validation after recovery

### GPU profile windows and control-plane recovery

The browser-facing CPU services are independent of model admission. If a
profile test has ended or a provider exits, reconcile them without starting a
model:

```bash
source scripts/env.sh
bash scripts/ensure-control-plane.sh
```

The default steady state is RT-CV/registered video plus CPU APIs. Cosmos3,
Nemotron, RT-Embedding, SigLIP and direct RT-VLM are on-demand. Start them
only through their project scripts and confirmed admission lease. Stop the
same profile with its matching project stop script; it revokes the lease and
restores RT-CV where that workflow owns the GPU window. Never stop the unified
API to free VRAM, and never bind a model or BFF port beyond `127.0.0.1`.

Run:

```bash
source scripts/env.sh
make phase15-health
make phase15-test
make phase15-backup
make phase15-restore-test
```

Also verify:

- `/`, `/__ENV.js`, a referenced `/_next/` asset and `/openapi.json` return
  200; `/dashboard` is only a compatibility redirect to `/`.
- The NVIDIA shell exposes the configured Search, Alerts and Video Management
  tabs plus global chat without opening business workflows on other ports.
- CSP contains the pinned NVIDIA foundations CSS origin,
  `media-src 'self' blob:` and `object-src 'none'`.
- `GET /api/v1/session` reports the expected trusted-loopback identity.
- Camera inventory identifies only stable `cam-01`; an unavailable physical
  source remains explicit and is never replaced by a simulated preview.
- Backend-down and provider-standby states remain explicit.
- An attached exact clip/alert calls
  `/api/v1/workspace/assistant/evidence`, never `/workspace/search`; queued
  work names `summary_caption` or `summary_reasoning` and requires the existing
  confirmed GPU action.
- No GPU-heavy profile was started merely for validation.

Browser screenshots, viewport checks, keyboard-only interaction and console
inspection remain pending when no browser/automation tooling is installed.
Do not download a large browser package solely to close that evidence gap
without first inventorying disk and dependencies.

## Backup, rollback and data-loss assessment

The refinement adds no database migration and does not change raw recording,
model or index formats. The safest operational rollback is to stop only Phase
15:

```bash
make phase15-stop
```

This preserves backend dashboards, raw recordings, selected media, indices,
reports, audit data, images, volumes, caches, leases and the currently active
GPU workload.

Before any source rollback, create and verify the existing control-plane
backup:

```bash
make phase15-backup
make phase15-restore-test
```

The current backup script covers UI provenance/runtime configuration, complete
project-owned Phase 15 API source (`service.py`, `vss_ui.py`, `workspace.py`,
registry/security helpers), the
touched search/summarization services and tests, Compose, OpenAPI,
security/observability config, handoff/runbook, GPU-control code/worker and
audit data. The isolated restore test extracts and compares the main adapter,
search, summarization and Compose files. Because this working tree has no
established commit baseline, this is a known-good recovery snapshot of the
refinement, not a pre-refinement Git baseline. Restore only an exact verified
archive; do not use `git reset --hard` or `git checkout --`.

Files under `artifacts/benchmarks/phase15-ui-refinement/before/` are historical
evidence for the removed custom shell, not a complete restore set for the
current Compose/gateway topology. Do not copy those files into the active tree.
A full Phase 15 code rollback uses an exact archive created by
`make phase15-backup`; inspect its checksum and contents before any
operator-approved restore. The pre-replacement archive recorded in the current
handoff is the recovery point if the NVIDIA UI integration must be reverted.
