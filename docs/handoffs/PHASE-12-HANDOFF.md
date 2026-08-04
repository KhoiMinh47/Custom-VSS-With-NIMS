# PHASE-12 HANDOFF

## Result

PARTIAL

All Phase 12 technical exit criteria passed on one physical source,
`cam-01`, using actual cached NVIDIA model runtimes. Cosmos-Embed1 video
search, SigLIP2 object/attribute search, reciprocal-rank fusion,
search-by-image, Nemotron query decomposition, Cosmos3 top-K criticism,
Elasticsearch persistence, API/UI/metrics, admission control and GPU-offline
fallback were exercised end to end.

The result remains `PARTIAL` because the evaluation has only four queries,
three selected clips, three manually bounded object crops and provisional
labels from one camera. It proves the workflow, not production search
accuracy. Phase 08 remains deferred by explicit user direction. Phase 13 has
not started.

## Scope completed

- Pinned VSS 3.2.1 RT-Embedding adapter for Cosmos-Embed1.
- Approximately ten-second selected-clip chunk contracts and deterministic
  embedding IDs.
- SigLIP2 object crop and text embeddings with normalized bounding boxes.
- Separate 768-dimensional video and 1152-dimensional object vector indices.
- Action, attribute, reciprocal-rank fusion and search-by-image APIs.
- Optional Nemotron decomposition with deterministic fallback.
- Optional Cosmos3 top-K critic with ranked-result preservation on outage.
- Cached query vectors for search while GPU providers are stopped.
- Model generation guard that requires re-indexing after ID/version/dimension
  changes when documents already exist.
- Non-blocking indexer lock that rejects duplicate indexers.
- Browser search UI, structured state, health and Prometheus metrics.
- Serialized admission/start/stop flows for all four GPU-heavy providers.
- Query set, Precision@K/nDCG evaluation and error analysis.
- Raw-plane isolation, credential scans, health checks and tests.

Only `selected-clip://` and `selected-snapshot://` media are accepted. The
search and embedding services neither mount nor scan `runtime/raw-video`.

## Actual indexing and search evidence

- Video model: `cosmos-embed1-448p-anomaly-detection`, version `1.0`.
- Video generation: `6b633ea73480435f`.
- Video documents: 3 selected clips, one approximately ten-second chunk each.
- Video vector dimension: 768.
- Object model: `siglip2-so400m-patch16-256`, version `v1.1`.
- Object generation: `b467f55de96f51ce`.
- Object documents: 3 manually bounded person crops from one selected
  snapshot.
- Object vector dimension: 1152.
- Action, attribute and fusion searches returned `camera_id`, UTC time,
  selected asset URI, score and evidence.
- Search-by-image returned three object matches.
- Actual Nemotron decomposition for “entering with a red backpack” returned
  `route=fusion`, `action_query=entering`,
  `attribute_query=red backpack`.
- Actual Cosmos3 critic marked the top restricted-entry result `relevant`
  with confidence `0.95`.
- After Cosmos3 stopped, the same action search preserved all three results
  and returned `critic_status=unavailable`.

## Evaluation

- Evaluation run: `phase12-20260729T100802Z`.
- Query count: 4.
- Routes: action, attribute and fusion.
- Mean Precision@K: `0.3833333333`.
- Mean nDCG@K: `0.9077324384`.
- The restricted-entry query ranked both relevant clips first and second.
- The queue clip was retrieved at rank two.
- The white-shirt crop ranked first for the corresponding attribute query.

Labels are provisional Phase 09 event types plus one manually reviewed
snapshot. These values cannot be cited as production precision, recall,
physical multi-camera capacity or generalization evidence.

## Images, models and admission

- RT-Embedding image:
  `nvcr.io/nvidia/vss-core/vss-rt-embed:3.2.1` at digest
  `sha256:978ef47aca4eca1e158b587a962b23a5bd9b7a3e717e61763b5c15e7228a1438`.
- SigLIP2 runtime image:
  `nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1` at digest
  `sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458`.
- Nemotron image:
  `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:1` at digest
  `sha256:a2f4a5aefe7dd0ff29bfd8d7081ce4977337d1b12081361af7b6283ff9a406b2`.
- Cosmos3 image:
  `nvcr.io/nim/nvidia/cosmos3-reasoner:1.7` at digest
  `sha256:19add3edaaa77c4030c75eb27d30939c29ca93807bb7af10a1876f05d520026c`.
- Nemotron cached profile:
  `5cf34bab34141258d0cc836c66684642d3e3f32b4daaa2008e48bd289d6bc84b`.
- Cosmos3 cached profile:
  `e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3`.

Cosmos-Embed1 reused its existing ONNX and TensorRT engines. SigLIP2 built one
FP16 batch-one engine and a restart then logged that the compatible engine was
reused. Nemotron and Cosmos3 used existing model caches. No all-profile
download or new model download occurred.

RT-Embedding, SigLIP2, Nemotron and Cosmos3 ran in separate admitted windows.
Each window paused RT-CV/metadata only, preserved the video/relay plane,
revoked its lease on stop and restored healthy RT-CV. Observed total GPU
memory was 15,793 MiB for RT-Embedding, 10,791 MiB for SigLIP2, 32,742 MiB
for the final Nemotron profile, and 44,333 MiB during Cosmos3 criticism.

This is an experimental serialized profile on RTX PRO 5000 Blackwell. It is
not an NVIDIA-validated topology and must not be extrapolated to ten cameras.

## Files created

- `services/rt-embedding/contracts.py`
- `services/rt-embedding/client.py`
- `services/rt-embedding/README.md`
- `services/search/contracts.py`
- `services/search/clients.py`
- `services/search/service.py`
- `services/search/start-siglip.sh`
- `services/search/README.md`
- `config/search/search-policy.json`
- `config/search/query-decomposition.json`
- `config/search/critic.json`
- `config/search/deepstream/ds-main-config.txt`
- `config/elasticsearch/mapping-phase12-video-embeddings.json`
- `config/elasticsearch/mapping-phase12-object-embeddings.json`
- `deploy/compose/phase12.compose.yml`
- `scripts/phase12-lib.sh`
- `scripts/start-phase12.sh`
- `scripts/healthcheck-phase12.sh`
- `scripts/start-phase12-rt-embedding.sh`
- `scripts/stop-phase12-rt-embedding.sh`
- `scripts/start-phase12-siglip.sh`
- `scripts/stop-phase12-siglip.sh`
- `scripts/start-phase12-llm.sh`
- `scripts/stop-phase12-llm.sh`
- `scripts/start-phase12-critic.sh`
- `scripts/stop-phase12-critic.sh`
- `scripts/index-phase12-assets.py`
- `scripts/evaluate-phase12-search.py`
- `scripts/test-phase12.sh`
- `scripts/capture-phase12-evidence.sh`
- `scripts/stop-phase12.sh`
- `tests/unit/test_phase12.py`
- `docs/evals/search-query-set.jsonl`
- `docs/evals/search-results/README.md`
- `docs/evals/search-results/error-analysis.md`
- generated evaluation JSON under `docs/evals/search-results/`

## Files modified

- `Makefile`
- `README.md`
- `PROJECT_STATE.md`
- `phase.md`
- `scripts/bootstrap-project.sh`
- `services/gpu-admission-controller/admission.py`
- `config/elasticsearch/bootstrap.sh`
- `config/elasticsearch/template-video-embeddings.json`
- `config/elasticsearch/template-object-embeddings.json`
- `config/prometheus/prometheus.yml`
- `config/runtime/single-gpu-poc.yaml`
- `deploy/overlays/single-gpu-poc.compose.yml`

## Commands and validation

```text
non-destructive Docker/disk/GPU inventory
make phase12-config
make phase12-start
make phase12-health
make phase12-rt-embedding-start/stop
make phase12-siglip-start/stop
make phase12-llm-start/stop
make phase12-critic-start/stop
make phase12-evaluate
make phase12-test
make phase12-evidence
make rtcv-health
make rtcv-test
make behavior-health
make phase10-health
make phase11-health
make video-health
make alerts-default-health
pytest -q
HTTP, Prometheus, Elasticsearch, mount and credential checks
```

## Validation result

- Full project test suite: 77 passed.
- Phase 12 unit tests: 16 passed.
- Phase 12 Compose/API/UI/vector/isolation/degradation gates: PASS.
- RT-Embedding actual inference and cache reuse: PASS.
- SigLIP2 text/image inference, image search and engine reuse: PASS.
- Nemotron actual decomposition: PASS.
- Cosmos3 actual top-K criticism: PASS.
- Critic-unavailable ranked-result preservation: PASS.
- Model generation/re-index guard: PASS.
- Duplicate indexer lock: PASS.
- Prometheus target `phase12-search`: up.
- RT-CV restore and Phase 07 full smoke test: PASS.
- Phase 09, Phase 10, Phase 11 collector and video plane: healthy.

No prune, image/model/cache deletion, volume deletion, global package
installation, raw-storage processing or credential persistence occurred.

## Evidence

- `artifacts/manifests/inventory-20260729T093721Z/`
- `artifacts/benchmarks/phase12-search/video-indexing.json`
- `artifacts/benchmarks/phase12-search/object-indexing.json`
- `artifacts/benchmarks/phase12-search/llm-decomposition.json`
- `artifacts/benchmarks/phase12-search/critic-search.json`
- `artifacts/benchmarks/phase12-search/critic-unavailable-search.json`
- `artifacts/benchmarks/phase12-search/fusion-search.json`
- `artifacts/benchmarks/phase12-search/search-state.json`
- `artifacts/benchmarks/phase12-search/search-metrics.txt`
- `artifacts/benchmarks/phase12-search/search-mounts.json`
- `artifacts/benchmarks/phase12-search/*gpu*.csv`
- `artifacts/logs/phase12-rt-embedding-cache-and-inference.txt`
- `artifacts/logs/phase12-siglip-cache-reuse.txt`
- `artifacts/logs/phase12-nemotron-cache-and-inference.txt`
- `artifacts/logs/phase12-critic-cache-and-inference.txt`
- `artifacts/logs/phase12-smoke.txt`
- `docs/evals/search-results/latest.json`

## Issues found and resolved

1. RT-Embedding advertised the runtime model ID in lowercase while the cache
   source uses the display-name capitalization. The adapter now discovers and
   sends the actual runtime ID; the initial HTTP 400 occurred before any
   document was written.
2. Historical chunk responses returned absolute ISO start/end timestamps
   rather than numeric offsets. The adapter accepts the vendor response and
   preserves UTC contract fields.
3. Existing strict Elasticsearch mappings lacked new Phase 12 metadata
   fields. Repeatable mapping additions and templates were added before
   indexing.
4. SigLIP2 text responses have a direct vector at `data[0]`, unlike the
   wrapped form expected initially. The client accepts both documented shapes,
   and readiness now includes an actual text-embedding probe.
5. Nemotron's large default context/KV allocation exceeded the available GPU
   during configuration. The admitted Phase 12 window now uses a 4,096-token
   context, one sequence, 4,096 batched tokens and 50% KV-cache allocation.
   The final profile used 32,742 MiB and returned HTTP 200 without OOM.
6. The search container needed the external infrastructure network to reach
   the admitted Nemotron/Cosmos3 service aliases. The project overlay now
   attaches those services without exposing vendor APIs publicly.
7. Cosmos3 returned valid JSON inside a Markdown code fence. The shared
   provider parser now accepts JSON objects in plain, fenced and
   post-`</think>` responses while rejecting non-JSON content.
8. Host port 39300 was already occupied by an unrelated local process.
   RT-Embedding and SigLIP2 use project-local loopback ports 39320 and 39321;
   the Phase 12 search UI/API remains on 39310.

## Known limits

- Four provisional queries are insufficient for accuracy or recall claims.
- Only one physical camera and a very small selected-media set were tested.
- New uncached text/image queries require the corresponding admitted embedding
  provider window; the CPU search service cannot create novel vectors while
  providers are stopped.
- Query decomposition falls back to deterministic routing while Nemotron is
  stopped.
- Cosmos3 criticism is optional and absent between admitted windows.
- GPU provider startup is intentionally slower because model/engine readiness
  and admission are hard gates.
- Phase 08 physical ten-camera capacity evidence remains absent.

## Current runtime

- Phase 12 CPU search API/UI: healthy on
  `http://127.0.0.1:39310/dashboard`.
- Prometheus target `phase12-search`: up.
- RT-Embedding: stopped; lease revoked.
- SigLIP2 provider: stopped; lease revoked.
- Nemotron: stopped; lease revoked.
- Cosmos3 critic: stopped; lease revoked.
- Cached action/attribute/fusion retrieval: available.
- Deterministic query decomposition: active fallback.
- Critic outage behavior: ranked results preserved.
- RT-CV, metadata, relay, Phase 09, Phase 10 CPU services, Phase 11 collector
  and video plane: healthy.
- Elasticsearch documents, selected assets, images, model caches, TensorRT
  engines and evidence: preserved.

## Rollback

- `make phase12-stop` stops the Phase 12 CPU search service and all Phase 12
  GPU profiles, revokes Phase 12 leases and restores RT-CV.
- The command preserves Elasticsearch vectors, selected assets, images,
  model caches, TensorRT engines and evidence.
- No raw recording is modified or removed.

## Exact next phase

PHASE-13 only after the user reviews and explicitly instructs it. PHASE-08
remains deferred, incomplete and unapproved.

## Approval required

YES. The Phase 12 technical implementation is complete, but the documented
`PARTIAL` accuracy result has not yet been accepted by the user.
