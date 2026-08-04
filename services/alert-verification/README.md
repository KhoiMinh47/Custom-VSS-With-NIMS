# Phase 10 alert verification

The verifier consumes `vss.incidents.candidate` only when a local-VLM
admission lease exists and the pinned Cosmos3 NIM is ready. It sends the
selected MP4 clip to the OpenAI-compatible endpoint, requests a structured
`confirmed`, `rejected`, or `uncertain` verdict, retries transient failures
three times, persists the result, and publishes `vss.incidents.verified`.

An exhausted verification becomes `uncertain` and is also copied to
`vss.dlq`; the original incident and clip remain available for review. This is
event-driven clip verification, not continuous RT-VLM.

Review UI and API:

- `http://localhost:39120/dashboard`
- `http://localhost:39120/api/v1/alerts`
- `http://localhost:39120/api/v1/evaluation`
- `POST /api/v1/alerts/{incident_id}/feedback`
- `http://localhost:39120/metrics`

The UI serves only selected Phase 10 clips and supports human feedback labels
for the confusion matrix. It does not expose camera configuration or RTSP
credentials.
