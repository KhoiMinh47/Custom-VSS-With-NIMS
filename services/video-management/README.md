# Video management foundation

> Current runtime note (2026-08-04): the active registry profile is
> `physical_camera_only` with stable `cam-01`. The ten-file NVStreamer profile
> described below is a preserved validation/rollback profile, not the current
> physical-camera inventory and not ten-camera capacity evidence.

Phase 06 keeps the video/raw-storage plane independent from the AI plane.
NVIDIA VIOS owns RTSP ingest, health monitoring, recording, live playback,
snapshot and clip extraction. The registry adapter resolves `camera://` secret
references only at runtime; committed camera files never contain an RTSP
password or token.

The historical validation profile uses ten project-local H.264 replay files
served by NVIDIA NVStreamer. This proves the video-management contracts when
physical camera credentials are unavailable. Replace
`.secrets/camera-uris.json` with operator-managed RTSP URI resolution to
onboard physical cameras.

For this single-pod PoC, the registry adapter also performs the deterministic
Sensor-MS to StreamProcessing registration normally coordinated by NVIDIA's
SDR service. This avoids another control service while preserving the official
VIOS proxy, recording and storage APIs. Re-running onboarding is idempotent.

All backend timestamps are UTC. `Asia/Ho_Chi_Minh` is display metadata only.
No component in this phase produces metadata, events, embeddings, summaries
or reports, and no inference service is started.

Use the repository scripts:

```bash
make video-prepare-simulated
make video-start
make video-onboard
make video-probe-physical
make video-test
make video-reconnect-test
make video-stop
```

`video-stop` preserves images, raw recordings, clips, snapshots and VIOS
state. Migration rollback is operator-triggered with
`migrations/002_video_management.rollback.sql`; back up Phase 05 PostgreSQL
before applying it because the rollback drops Phase 06 reference tables.

`video-probe-physical` reads one credential-bearing RTSP URI with terminal
echo disabled. It does not write the URI to the registry, a secret file or an
artifact. A successful result proves authenticated RTP receive and decode
inside the VIOS StreamProcessing container; it does not replace the ten-source
registry automatically.

For repeated use, `make camera-save` stores the URI under a
`camera://keyring/...` reference. It first tries the host system keyring and
falls back to the volatile kernel keyring when no Secret Service daemon is
running. The URI is never written to the repository, `.secrets/`, logs or
artifacts; the kernel-keyring fallback is lost on reboot. Then use
`make camera-probe`; remove the entry with `make camera-clear`.

Use `make camera-activate` to replace simulated `cam-01` with the saved
physical camera while keeping `cam-02` through `cam-10` on replay sources.
The active committed registry remains credential-free in
`config/cameras/cameras.hybrid.json`. `make camera-restore` is the explicit
rollback to simulated `cam-01`.

For live preview in VS Code, run `make camera-live`, then open the Command
Palette → **Browser: Open Integrated Browser** and enter
`http://127.0.0.1:8090/mjpeg`.
With Remote SSH/Containers, forward port 8090 first. Stop it with
`make camera-live-stop`. The preview uses a 100 ms RTSP jitter buffer and a
two-frame leaky queue so it drops stale frames under load instead of building
minutes of backlog.

For the Phase 07 one-camera AI compositor, run:

```bash
make camera-ai-overlay
```

Then open `http://127.0.0.1:8090/ai-overlay`. The page reuses `/mjpeg` as an
ordinary browser image and polls the filtered `/api/ai-state` response about
2.5 times per second. Bounding boxes are normalized and drawn in a canvas,
so window resizing does not require video re-encoding. Current class,
confidence, track ID, UTC metadata timestamp, source FPS/frame counter,
line-crossing count and AI connection status are shown.

The UI process belongs to the live video presentation layer and does not mount
or read raw recording storage. `/api/ai-state` retries upstream reads up to
three times and treats metadata `/debug/state` as the primary health signal.
A temporary metrics failure reuses the last FPS/frame counter and marks only
`metrics_degraded`; it does not make healthy metadata unavailable. The first
two failed state polls show `AI reconnecting`, and only the third consecutive
failed poll shows `RT-CV unavailable`. `/mjpeg` continues independently in
every AI state.

The default metadata stale threshold is ten seconds. The last box and track
are retained for at most five seconds during a short delay. Because metadata
is object-driven, a live vendor FPS/frame counter keeps the UI in
`AI connected` even when an empty scene produces no new object message.
`waiting for AI metadata` is reserved for a source with neither metadata nor
live stream metrics.

The browser MJPEG presentation is a bounded low-latency view of `cam-01` with
a small jitter buffer and leaky queue. The AI branch uses the logical H.264
1280x720 substream contract while raw
recording remains H.265 2560x1440. Both use the same 16:9 normalized coordinate
space, but this PoC compositor is best-effort rather than frame-locked. The
presentation path must not be treated as a frame-accurate raw-recording reader.
The root page and `/mjpeg-main` expose a 2560x1440 browser preview of logical
mainstream 101; `/mjpeg` is the 1280x720 presentation paired with logical
AI substream 102 and `/ai-overlay`.

The physical camera OSD clock can be synchronized to the server with
`make camera-clock-sync`. This performs a one-time manual clock update through
the camera's authenticated ISAPI endpoint; configure camera NTP separately for
permanent automatic synchronization.
