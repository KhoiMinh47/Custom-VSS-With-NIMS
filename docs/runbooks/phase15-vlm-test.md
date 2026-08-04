# Phase 15 VLM Test workflow

This is a project-owned extension around the pinned NVIDIA VSS 3.2.1 UI. The
NVIDIA UI remains the upstream release; the gateway injects the same-origin
VLM Test control into the UI and exposes the versioned backend below. The
visual/upload baseline is the [NVIDIA VSS Reference User Interface](https://docs.nvidia.com/vss/latest/vss-ui.html).

## State machine

```text
VSS upload / selected realtime candidate
             |
             v
      vlm-test staging  -- no Store record exists here
             |
             v
      automatic RT-CV file batch -> real candidate
             |
      stop RT-CV -> admit Cosmos3 -> VLM test
             |
             +-- waiting_for_gpu / BLOCKED / failed
             |
             v
         completed result
             |
       explicit Save
             v
   vlm-test post-VLM Store
             |
        Launch VLM again
```

The raw video plane is not mounted by `vlm-test`. Realtime media is fetched
through the selected-media presentation endpoint after the incident queue has
prepared an allowlisted clip. Upload bytes are held only in the project-local
VLM-test staging directory until a completed VLM result and an explicit Save.

## UI

The regular VSS Video Management upload dialog retains NVIDIA's multi-file,
drag/drop, add-more and progress behavior. In this PoC its completed upload is
routed by the gateway to VLM-test staging. The VLM Test control is available as
a same-origin drawer with three views:

- Upload: stage files, show RT-CV → VLM status and Save after a completed test.
- Realtime: choose a real non-evaluation RT-CV candidate and launch its VLM test.
- Store: view only post-VLM assets and launch VLM again on an existing asset.

## API

The browser-facing routes are under `/api/v1/workspace/vlm-tests`; the fixed
control-plane service listens on `127.0.0.1:39520`.

- `POST /uploads` stages an MP4/MKV H.264 upload.
- `POST /jobs/{job_id}/candidate` attaches a real file RT-CV candidate.
- `POST /jobs/{job_id}/rtcv-start` retries the host upload → RT-CV → VLM workflow.
- `POST /jobs/{job_id}/launch` launches the admitted VLM test.
- `POST /jobs/{job_id}/save` copies media into Store only after completion.
- `GET /realtime/candidates` lists candidates from the Phase 10 incident queue.
- `POST /realtime/{incident_id}/launch` stages selected media and launches VLM.
- `GET /store` and `POST /store/{asset_id}/launch` list and retest stored media.

## Gates and truthful status

The project overlay contains a pinned VSS RT-CV file-batch runner. It reads
only VLM-test staging media, emits a candidate only from actual RT-CV Kafka
detections, and preserves the full store/camera/UTC/schema/model contract.
Videos with no detections are explicitly `no_rtcv_candidate`; no mock
candidate or VLM result is created.

Upload completion automatically queues the host `run_vlm_test` workflow. The
worker serializes RT-CV and VLM, stops the file-batch container before
starting Cosmos3, waits for the local VLM readiness endpoint, and cleans up
the VLM lease after the bounded job. The VLM verifier serializes explicit test
requests with production verification requests on the shared GPU. Store is
still changed only by explicit Save after a completed VLM result.
