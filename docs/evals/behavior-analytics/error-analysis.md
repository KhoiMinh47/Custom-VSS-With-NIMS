# Phase 09 accuracy and error analysis

## Result

- Synthetic functional event coverage: 10/10 event types, 100%.
- Kafka → behavior analytics → Elasticsearch persistence: PASS.
- Live non-evaluation events observed after deployment: 9.
- Real-camera MAE/MAPE, queue-count error and event precision/recall: PARTIAL,
  not yet measurable.

## Known error sources

- `cam-01` ROI, queue area and restricted area are provisional normalized
  polygons, not business-approved calibration.
- RT-DETR is a warehouse person baseline and has not been accuracy-tuned for
  this retail view.
- Object-driven metadata can omit intervals without detections.
- Occlusion and NvDCF ID switches can over/under-count line crossings.
- Queue wait is a track-presence estimate, not POS transaction wait time.
- The Phase 08 multi-camera capacity ladder was explicitly deferred; no
  ten-camera throughput claim is made.

## Required closure data

Collect an operator-approved sample containing positive and negative
entry/exit, queue, dwell and restricted-zone trajectories. Annotate timestamp,
track, count and zone truth, then calculate counting MAE/MAPE and per-event
precision/recall before using these metrics operationally.
