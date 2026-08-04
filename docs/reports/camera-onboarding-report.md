# Phase 06 camera onboarding report

## Result

PASS_WITH_RISK

One physical H.265 main stream and nine simulated sources were registered against
NVIDIA VIOS 3.2.1 and recorded concurrently. The risk suffix is inherited from the explicitly
accepted unsupported host/GPU environment; it is not a claim that NVIDIA
validates RTX PRO 5000 Blackwell for this topology.

The physical camera is stable `cam-01`; its credential-bearing URI is resolved
from an in-memory secret agent. The committed registry and control plane store
only `camera://` references.

## Registry

| Camera ID | Store | Main stream | AI substream | Recording |
| --- | --- | --- | --- | --- |
| cam-01 (physical) | store-001 | secret reference | secret reference | PASS |
| cam-02 | store-001 | secret reference | secret reference | PASS |
| cam-03 | store-001 | secret reference | secret reference | PASS |
| cam-04 | store-001 | secret reference | secret reference | PASS |
| cam-05 | store-001 | secret reference | secret reference | PASS |
| cam-06 | store-001 | secret reference | secret reference | PASS |
| cam-07 | store-001 | secret reference | secret reference | PASS |
| cam-08 | store-001 | secret reference | secret reference | PASS |
| cam-09 | store-001 | secret reference | secret reference | PASS |
| cam-10 | store-001 | secret reference | secret reference | PASS |

Physical `cam-01` uses channel 101 as H.265 2560x1440/25 FPS main stream.
Channel 102 remains its logical H.264 1280x720/25 FPS AI substream. The
remaining simulated profile maps each main and AI reference to the same replay source.
No resolved URI or camera password is committed or stored in the Phase 05
control-plane database.

## Runtime validation

- VIOS services healthy: 6/6.
- Active VIOS sources: 10/10 (one physical plus nine simulated).
- VIOS sensor status online: 10/10.
- VIOS live RTSP proxies: 10/10.
- UTC recording timelines and raw MKV segments: 10/10.
- Recorded picture API: JPEG, 640x360, PASS.
- Time-range clip API: MP4, PASS.
- Live RTSP path: sustained GStreamer receive probe, PASS.
- Physical RTSP camera: authenticated H.265 RTP receive and decode at 2560x1440,
  PASS.
- Source-loss/reconnect: recording quiesced while the source was stopped and
  resumed after restart, PASS.
- AI/model services started by the Phase 06 compose: 0.

The VIOS Sensor status endpoint remained `online` during the short simulated
source outage even though recording stopped. Functional loss and recovery
were therefore gated using recording byte quiescence/resumption. This
telemetry limitation is recorded for future health-adapter work.

## Timestamp validation

Backend timelines used ISO 8601 UTC values with a `Z` suffix. The validated
cam-01 timeline began at `2026-07-28T02:49:36.852Z`; picture and clip requests
used timestamps inside that interval. `Asia/Ho_Chi_Minh` remains display-only
metadata in the camera registry.

## Evidence

- `artifacts/logs/phase06-video-management-smoke.txt`
- `artifacts/logs/phase06-reconnect.txt`
- `artifacts/logs/phase06-physical-camera-probe.txt`
- `artifacts/logs/phase06-vios-streams.json`
- `artifacts/logs/phase06-vios-status.json`
- `artifacts/manifests/phase06-image-sources.tsv`
- `artifacts/manifests/inventory-20260728T022421Z/`
- `runtime/raw-video/`
- `runtime/snapshots/`
- `runtime/clips/`

Runtime media and evidence are intentionally ignored by Git.

The nine replay sources preserve the ten-source project workflow but are not
physical-camera performance evidence. Capacity and soak gates requiring ten
real cameras remain `PARTIAL` until the corresponding credentials are
available and those tests are rerun.
