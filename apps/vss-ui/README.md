# NVIDIA VSS UI integration

The browser application starts from NVIDIA's pinned
`nv-metropolis-bp-vss-ui`. Its source is kept once, under:

- `third_party/video-search-and-summarization/services/ui/apps/nv-metropolis-bp-vss-ui`
- `third_party/video-search-and-summarization/services/ui/packages/nv-metropolis-bp-vss-ui`

Phase 15 runs the release UI image declared in
`deploy/compose/phase15.compose.yml`; it does not maintain a second copy of
the TypeScript application. The upstream bundle is unchanged on disk, while
the same-origin gateway applies project-owned HTML/API compatibility overlays
at response time. Project-specific integration is deliberately separated into:

- `config/ui/vss-ui.env`: non-secret runtime feature flags and same-origin URLs.
- `services/api/vss_ui.py`: bounded UI reverse proxy and contract adapters.
- `services/api/service.py`: authorization, auditing, and route ownership.
- `services/api/stream_sources_overlay.js`: Streaming/VLM single-pane Video
  Management, user-managed RTSP sources and post-VLM Store cards.
- `services/api/vlm_test_overlay.js`: Upload/Realtime/Store VLM Test drawer.
- `services/api/gpu_control_overlay.js`: LLM/VLM on/off controls and status.

The public entry point is `http://127.0.0.1:39510/`. The Next.js process is
loopback-only on port 39511, behind the Phase 15 gateway. Neither UI service
mounts raw storage, the Docker socket, GPU devices, camera secrets, or model
caches.

The header places GPU and VLM Test controls beside the light/dark icon. Video
Management shows exactly one selected view: `Streaming` or
`VLM Processed Videos`. Selecting an upload begins the VLM Test upload flow
automatically; Store is updated only after a completed result and explicit
`Save to Store`.

See `SOURCE-MANIFEST.json` for the exact source and image provenance.
