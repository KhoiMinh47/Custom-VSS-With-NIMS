# Phase 07 RT-CV vertical slice

This service runs one physical source only: stable `camera_id=cam-01`,
`store_id=store-001`. A project-owned secure RTSP relay resolves the camera
secret at runtime and prefers the physical H.264 channel 102, 1280x720 AI
substream. It decodes and re-encodes that selected AI stream as clean H.264
with periodic keyframes through the credential-free internal channel-102 path,
so new browser/RT-CV clients do not begin on a broken mid-GOP frame. The VIOS
channel-101 H.265 main-stream proxy remains an explicit fallback only when the
physical secret lease is unavailable. No credential-bearing URI is stored in
Compose, config, logs or artifacts.

The pinned VSS 3.2.1 `vss-rt-cv` image runs RT-DETR Warehouse 2D v1.0.2 FP16
and NvDCF at a target inference rate of 5 FPS. DeepStream publishes NVIDIA
protobuf metadata to Kafka topic `mdx-raw`. The metadata service:

- rejects any sensor other than `cam-01`;
- enriches frames with schema/model/store/camera/UTC fields;
- publishes the stable JSON contract to `vss.rt-cv.frames`;
- indexes idempotently through the `mdx-raw` Elasticsearch write alias;
- evaluates the Phase 07 smoke ROI/line rule;
- exposes health, Prometheus metrics and `/debug/overlay`.

Raw video remains in the Phase 06 video plane. This service consumes only the
selected physical channel-102 AI substream through the secure internal relay
and creates metadata; it never reads raw recording storage.

Safe operations:

```text
make rtcv-start
make rtcv-health
make rtcv-test
make rtcv-reconnect-test
make rtcv-soak
make rtcv-stop
```

`rtcv-stop` stops containers only. It preserves the ONNX model, generated
TensorRT engine, Kafka data, Elasticsearch metadata and all Phase 06 video.

The approved Phase 07 browser compositor is served independently by the
camera-live service at `http://127.0.0.1:8090/ai-overlay`. It reads this
service's public `/debug/state` plus RT-CV vendor metrics through a filtered
same-origin UI proxy. It never receives an RTSP URI, never mounts raw storage
and does not alter the RT-DETR/NvDCF backend.
