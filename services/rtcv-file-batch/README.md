# RT-CV file-batch adapter

Bounded adapter that runs the pinned VSS RT-CV 3.2.1 detector/tracker against
one VLM Test staging file. It rewrites a runtime copy of the DeepStream config,
consumes the actual NVIDIA protobuf output from `mdx-raw`, filters detections
by the reviewed threshold and creates one deterministic candidate contract.

```text
staged MP4/MKV -> DeepStream decode -> RT-DETR -> NvDCF -> mdx-raw
               -> validated object detection -> candidate -> VLM Test
```

The adapter reads only VLM Test staging media. It neither reads VIOS raw
storage nor writes the post-VLM Store. It records `store-001`, `cam-01`, UTC
bounds, schema/model versions and evidence IDs. No detection means
`no_rtcv_candidate`; timeout or provider failure remains an explicit failed or
blocked state. The workflow stops this container and revokes its lease before
admitting Cosmos3.
