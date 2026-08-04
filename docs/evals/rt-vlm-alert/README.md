# Phase 11 direct RT-VLM evaluation

The controlled benchmark uses one physical source, `cam-01`, an eight-second
chunk, zero overlap and five fixed frames per chunk. Results are accepted as
successful inference evidence only when the vendor protobuf contains a
non-empty VLM response, positive VLM latency and no more than five frames.

Operator feedback uses `confirmed`, `rejected`, or `uncertain`. Unlabeled
results are excluded from accuracy and false-alert calculations. Transport,
latency, token and GPU measurements may pass while accuracy remains
`PARTIAL`.

Evidence is stored under `artifacts/benchmarks/rt-vlm-alert/`. The initial
eight-frame configuration generated HTTP 422 responses because Cosmos3 accepts
at most five images per prompt. Those records are retained as error-analysis
evidence and excluded from the clean benchmark.
