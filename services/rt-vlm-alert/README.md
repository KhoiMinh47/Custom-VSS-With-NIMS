# Phase 11 direct RT-VLM alert

The pinned NVIDIA VSS RT-VLM 3.2.1 service reads only the internal,
credential-free `cam-01` H.264 relay fed by the physical 1280x720 channel-102
AI substream. It evaluates one eight-second chunk at a time using five fixed
frames and calls the admitted Cosmos3 NIM.

Vendor `VisionLLM` protobuf results are published to
`vss.rt-vlm.captions`. The CPU collector converts them into the project JSON
contract, persists them in `mdx-rt-vlm-alerts`, and exposes:

- `http://127.0.0.1:39210/dashboard`
- `http://127.0.0.1:39210/api/v1/alerts`
- `http://127.0.0.1:39210/api/v1/evaluation`
- `http://127.0.0.1:39210/api/v1/comparison`
- `http://127.0.0.1:39210/metrics`
- `http://127.0.0.1:39210/api/v1/resources` for the secret-free, read-only
  host CPU/RAM, GPU/VRAM and Phase 11 container snapshot shown in the dashboard.

Direct mode is limited to `cam-01` and is serialized with RT-CV. It never
mounts raw video storage and does not read Phase 07 metadata or Phase 09
candidates. Phase 10 remains the independent hybrid comparison path.
