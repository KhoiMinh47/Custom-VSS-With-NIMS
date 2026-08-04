# VLM Test service

CPU control service for the Phase 15 Upload, Realtime and Store test workflow.
It owns job metadata and project-local test media under
`runtime/phase15/vlm-test/`; it does not mount VIOS raw recording storage and
does not run a GPU model itself.

## Pipelines

```text
Upload -> staging -> RT-CV file batch -> real candidate -> Cosmos3 -> result
                                                              -> explicit Save
                                                              -> post-VLM Store

Persisted realtime candidate -> exact selected clip -> staging -> Cosmos3

Post-VLM Store asset -> Launch -> staging retest -> new Cosmos3 result
```

Uploading is automatic after file selection. Store remains empty until VLM has
completed and the user explicitly saves. A file with no RT-CV detections ends
as `no_rtcv_candidate`; no synthetic candidate is generated.

Realtime means a bounded clip selected from an already persisted RT-CV/
behavior incident. It does not feed an unbounded RTSP stream directly into
Cosmos3. If realtime RT-CV is unavailable, no new candidate is available to
launch.

The service preserves `store_id`, stable `camera_id`, UTC bounds,
`schema_version`, model/prompt versions and content SHA-256. GPU work is
requested through the host queue and admission controller. See
[`docs/runbooks/phase15-vlm-test.md`](../../docs/runbooks/phase15-vlm-test.md)
for routes and operational states.
