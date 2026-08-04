# Phase 10 alert-verification evaluation

Evaluation records one structured Cosmos3 verdict per real Phase 09 candidate
clip, end-to-end latency, retries, and an optional human feedback label.
`GET /api/v1/evaluation` reports the labeled confusion matrix and latency
summary. Unlabeled alerts are excluded from the matrix.

The automated gate proves the transport, selected-media, persistence,
retry/DLQ, admission and UI contracts. It does not claim production accuracy:
the Phase 09 ROI is provisional and the project does not yet have an
operator-approved real-camera ground-truth set.

Evidence is written under `artifacts/evals/phase10/` and
`artifacts/logs/phase10-*`. Synthetic or mocked VLM output must not be cited as
evidence that Cosmos3 ran.
