# Phase 09 behavior analytics evaluation

The committed `cam-01` ROI and line configuration is provisional. The
automated evaluation uses a deterministic normalized synthetic trajectory to
exercise entry/exit, line crossing, ROI transitions, dwell, restricted-zone,
queue and heatmap behavior.

This proves rule logic and the Kafka-to-Elasticsearch event path. It does not
measure real-camera accuracy. Counting MAE/MAPE, queue error and event
precision/recall remain `PARTIAL` until a business owner approves the camera
mapping and supplies an annotated real-camera sample.

Run:

```bash
make behavior-test
```

Generated evidence is stored under `artifacts/evals/phase09/`.
