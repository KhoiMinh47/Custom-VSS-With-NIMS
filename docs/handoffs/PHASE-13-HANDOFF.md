# PHASE-13 HANDOFF

## Result

PARTIAL

Phase 13 is technically complete on one physical source, `cam-01`. Actual
cached Cosmos3 and Nemotron inference produced checkpointed selected-clip
captions, hierarchical summaries, evidence-grounded Q&A and incident,
shift and daily reports. Queue recovery, Elasticsearch persistence,
API/dashboard/metrics, GPU admission and raw-plane isolation passed.

The result remains `PARTIAL` because the evaluation covers only three selected
clips and has zero independent human ratings. It proves the workflow and
grounding structure, not production summary accuracy, completeness or
hallucination rate. Phase 08 remains deferred by explicit user direction.
Phase 14 has not started.

## Scope completed

- Versioned selected-video and time-window request contracts with
  `store_id`, stable `camera_id`, UTC timestamps, schema/model/prompt versions
  and selected-asset hashes.
- Strict acceptance of `selected-clip://<sha256>.mp4` assets from the Phase 10
  prepared-clip directory mounted read-only.
- Five uniformly sampled frames per clip for Cosmos3 captioning.
- One selected clip per durable caption checkpoint, deterministic IDs,
  bounded retry and a local dead-letter queue.
- Atomic job persistence and restart recovery for caption and summary stages.
- Hierarchical Nemotron synthesis with bounded leaf batches and a compact
  final pass over partial summaries plus allowlisted event IDs.
- Evidence-preserving post-processing that rejects unknown model-produced
  event IDs.
- Evidence Q&A with lexical preselection, cited camera/time/asset evidence and
  the exact `không đủ dữ liệu` response when no matching evidence exists.
- Deterministic incident, shift and daily JSON/Markdown reports.
- Explicit `unobserved` coverage gaps; missing selected media is never treated
  as evidence that no event occurred.
- Strict Elasticsearch mappings/templates for caption and summary documents.
- CPU API, dashboard, structured logs, health and Prometheus metrics.
- Separate admitted Cosmos3 and Nemotron GPU windows that stop RT-CV/metadata
  only, preserve the video/relay plane, revoke leases on stop and restore
  healthy RT-CV.
- Unit, integration, restart, isolation, credential and evaluation gates.

The summarization and reporting services neither mount nor scan
`runtime/raw-video`. Raw storage has no direct path to captions, summaries,
Q&A or reports.

## Actual inference and recovery evidence

- Cosmos3 performed four successful HTTP 200 caption requests: one short
  selected-video job and a three-clip time-window job.
- The jobs produced seven timestamped caption events. The shared first clip is
  deterministically upserted, leaving three unique caption documents in
  Elasticsearch.
- Nemotron completed one short summary and one hierarchical time-window
  summary.
- The time-window job used four partial summaries. Its final summary cited
  five of seven caption events, for structural event coverage `0.7142857143`.
  This is not a human correctness score.
- The summarization orchestrator was restarted twice while the long job was in
  `summarizing`. Both restarts recovered it to `queued_summary`; existing
  caption checkpoints were reused and the job completed without re-captioning.
- A supported Q&A request returned seven cited evidence records with
  `camera_id`, UTC bounds and selected-clip URI.
- The unsupported delivery-truck question returned exactly
  `không đủ dữ liệu` with an empty evidence list.
- Incident, shift and daily reports were generated in both JSON and Markdown.
- One 743.760-second gap between selected clips is recorded as `unobserved`.

## Evaluation

- Evaluation run: `phase13-20260730T032701Z`.
- Result: `PARTIAL`.
- Completed jobs: 2.
- Selected clips: 3.
- Caption events: 7.
- Hierarchical partial summaries: 4.
- Final-summary cited events: 5.
- Structural event coverage: `0.7142857143`.
- Coverage gaps: 1, explicitly `unobserved`.
- Unsupported-question refusal gate: PASS.
- Human ratings: 0.

All technical checks passed: timestamp bounds, cited summary claims,
evidence-bearing supported Q&A, unsupported-query refusal, evidence-bearing
reports and the missing-media policy. The small one-camera sample cannot
support production accuracy, completeness or hallucination-rate claims.

## Images, models and admission

- Cosmos3 image:
  `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` at digest
  `sha256:19add3edaaa77c4030c75eb27d30939c29ca93807bb7af10a1876f05d520026c`.
- Cosmos3 cached profile:
  `e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3`.
- Nemotron image:
  `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1` at digest
  `sha256:a2f4a5aefe7dd0ff29bfd8d7081ce4977337d1b12081361af7b6283ff9a406b2`.
- Nemotron cached profile:
  `5cf34bab34141258d0cc836c66684642d3e3f32b4daaa2008e48bd289d6bc84b`.

Both providers reused their approved Phase 04 caches. No model/profile
download occurred. Cosmos3 and Nemotron ran in separate admitted windows and
did not OOM. At handoff both providers are stopped, both Phase 13 leases are
revoked, GPU use is approximately 6.3 GiB, and RT-CV is restored and healthy.

This is an experimental serialized profile on RTX PRO 5000 Blackwell. NVIDIA
does not validate this GPU for the tested topology, and the result must not be
extrapolated to ten cameras.

## Files created

- `services/summarization/contracts.py`
- `services/summarization/providers.py`
- `services/summarization/service.py`
- `services/summarization/README.md`
- `services/reporting/reporting.py`
- `services/reporting/README.md`
- `config/prompts/summarization/caption.json`
- `config/prompts/summarization/summary.json`
- `config/prompts/summarization/qa.json`
- `config/prompts/reporting/report-policy.json`
- `config/elasticsearch/mapping-phase13-captions.json`
- `config/elasticsearch/mapping-phase13-summaries.json`
- `config/elasticsearch/template-phase13-captions.json`
- `config/elasticsearch/template-phase13-summaries.json`
- `deploy/compose/phase13.compose.yml`
- `scripts/phase13-lib.sh`
- `scripts/start-phase13.sh`
- `scripts/healthcheck-phase13.sh`
- `scripts/start-phase13-vlm.sh`
- `scripts/stop-phase13-vlm.sh`
- `scripts/start-phase13-llm.sh`
- `scripts/stop-phase13-llm.sh`
- `scripts/stop-phase13.sh`
- `scripts/run-phase13-workflow.py`
- `scripts/evaluate-phase13.sh`
- `scripts/test-phase13.sh`
- `scripts/capture-phase13-evidence.sh`
- `tests/unit/test_phase13.py`
- `docs/evals/summarization/README.md`
- `docs/evals/summarization/error-analysis.md`
- generated evaluation JSON under `docs/evals/summarization/`

## Files modified

- `Makefile`
- `README.md`
- `PROJECT_STATE.md`
- `phase.md`
- `scripts/bootstrap-project.sh`
- `services/gpu-admission-controller/admission.py`
- `config/elasticsearch/bootstrap.sh`
- `config/prometheus/prometheus.yml`
- `config/runtime/single-gpu-poc.yaml`

## Commands and validation

```text
non-destructive Docker/disk/GPU inventory
make phase13-config
make phase13-start
make phase13-health
make phase13-vlm-start/stop
make phase13-llm-start/stop
make phase13-evaluate
make phase13-test
make phase13-evidence
make phase12-start
make phase12-health
make rtcv-health
pytest -q
Elasticsearch, Prometheus, mount, lease, raw-plane and credential checks
```

## Validation result

- Full project test suite: 108 passed.
- Phase 13 unit tests: 16 passed.
- Phase 13 Compose/API/dashboard/queue/isolation gates: PASS.
- Actual Cosmos3 selected-clip captioning: PASS.
- Actual Nemotron short and hierarchical synthesis: PASS.
- Actual mid-summary restart/checkpoint recovery: PASS.
- Evidence-grounded Q&A and exact insufficient-evidence refusal: PASS.
- Incident/shift/daily JSON and Markdown reports: PASS.
- Repeatable additive Elasticsearch migration: PASS.
- Prometheus targets `phase12-search` and `phase13-summarization`: up.
- RT-CV restore and Phase 07 health: PASS.
- All inspected Prometheus targets: up.

No prune, image/model/cache deletion, volume deletion, global package
installation, raw-storage processing or credential persistence occurred.

## Evidence

- `artifacts/manifests/inventory-20260730T030057Z/`
- `artifacts/benchmarks/phase13-summarization/service-state.json`
- `artifacts/benchmarks/phase13-summarization/jobs.json`
- `artifacts/benchmarks/phase13-summarization/caption-results.json`
- `artifacts/benchmarks/phase13-summarization/summary-results.json`
- `artifacts/benchmarks/phase13-summarization/qa-results.json`
- `artifacts/benchmarks/phase13-summarization/report-results.json`
- `artifacts/benchmarks/phase13-summarization/caption-index-count.json`
- `artifacts/benchmarks/phase13-summarization/summary-index-count.json`
- `artifacts/benchmarks/phase13-summarization/metrics.txt`
- `artifacts/benchmarks/phase13-summarization/prometheus-targets.json`
- `artifacts/benchmarks/phase13-summarization/mounts.json`
- `artifacts/benchmarks/phase13-summarization/gpu-final.csv`
- `artifacts/logs/phase13-cosmos-caption-cache-and-inference.txt`
- `artifacts/logs/phase13-nemotron-summary-cache-and-inference.txt`
- `artifacts/logs/phase13-smoke.txt`
- `artifacts/benchmarks/phase13-summarization/semantic-qa-regression.json`
- `docs/evals/summarization/latest.json`
- `docs/evals/summarization/error-analysis.md`

## Issues found and resolved

1. Existing Elasticsearch indices used strict mappings and rejected the first
   Phase 13 fields. Dedicated higher-priority templates and repeatable
   additive mapping updates were added without recreating indices or deleting
   data.
2. The first summary write exposed a missing `partial_summary_count` field.
   The field was added to both the mapping and template, and bootstrap now
   succeeds repeatedly.
3. The initial long final-summary request exceeded the 4,096-token Nemotron
   context (`3,160` prompt tokens plus `1,024` requested output tokens).
   Output was bounded to 768 tokens.
4. A subsequent long response was truncated/non-JSON and correctly failed
   closed. The final hierarchy input now contains only grounded partial
   summaries and allowlisted event IDs; the resumed job completed. Failed
   attempts remain in service/NIM logs.
5. The evaluation rerun originally treated a completed caption job as invalid.
   The workflow is now idempotent and accepts the already completed
   checkpoint before proceeding to summary/Q&A/report validation.
6. A post-handoff semantic Q&A regression showed that generic terms such as
   `event`/`sự kiện` could select evidence without respecting a camera/time
   scope expressed in the question. Q&A now hard-filters stable camera IDs and
   bounded UTC time ranges before lexical selection, refuses ambiguous scope,
   and emits explicit `grounded` and `refused` flags. The original
   `cam-01` 10:30–10:40 UTC query now fails closed with
   `không quan sát được` and no evidence.

## Known limits

- Only three selected clips from one physical camera were evaluated.
- There are no independent human ratings or annotated summary references.
- Structural event coverage is not semantic correctness, completeness or
  hallucination measurement.
- Q&A preselection is lexical and may refuse semantically related questions
  whose wording does not overlap available evidence.
- Novel captions and summaries require their respective admitted provider
  windows; the CPU service preserves and serves completed results while the
  providers are stopped.
- GPU provider startup remains intentionally serialized and slower because
  admission and readiness are hard gates.
- Phase 08 physical ten-camera capacity evidence remains absent.

## Current runtime

- Phase 13 CPU API/dashboard: healthy at
  `http://127.0.0.1:39410/dashboard`.
- Phase 12 CPU search API/dashboard: healthy.
- Prometheus target `phase13-summarization`: up.
- Cosmos3 caption provider: stopped; lease revoked.
- Nemotron summary provider: stopped; lease revoked.
- RT-CV, metadata, relay, Phase 09, Phase 10 CPU services, Phase 11 collector
  and video plane: healthy.
- Caption/summary Elasticsearch documents, selected assets, reports, model
  caches, images and evidence: preserved.

## Rollback

- `make phase13-stop` stops the Phase 13 CPU service and both Phase 13 GPU
  profiles, revokes Phase 13 leases and restores RT-CV.
- The command preserves durable jobs, Elasticsearch captions/summaries,
  selected assets, reports, images, model caches and evidence.
- Elasticsearch changes are additive; disabling Phase 13 requires no
  destructive downgrade.
- No raw recording is modified or removed.

## Exact next phase

PHASE-14 only after the user reviews this handoff and gives a new explicit
instruction. PHASE-08 remains deferred, incomplete and unapproved.

## Approval required

YES. The Phase 13 technical implementation is complete, but the documented
`PARTIAL` accuracy/completeness result has not yet been accepted by the user.
