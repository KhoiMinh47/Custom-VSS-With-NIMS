# Phase 12 bounded-search error analysis

## Interpretation

The run proves that the evaluation path and all search routes execute. It does
not estimate production accuracy. There are only four queries, three selected
clips, three object crops and one physical camera.

## Observed ranking behavior

- Both restricted-entry clips ranked first and second for the restricted-area
  action query.
- The queue clip was retrieved for the queue query but ranked second, which
  reduced Precision@K even though nDCG remained high.
- The manually bounded white-shirt crop ranked first for the corresponding
  attribute query.
- Fusion and search-by-image returned evidence-bearing results with camera,
  UTC timestamp and selected asset URI.
- Cosmos3 marked the first restricted-entry candidate `relevant` with
  confidence `0.95`. This is one critic response, not an accuracy sample.

## Main sources of error and uncertainty

- Phase 09 event types are provisional labels, not independently reviewed
  search relevance judgments.
- The three object crops come from one manually reviewed snapshot and do not
  cover lighting, pose, occlusion or camera variation.
- Text-query caches cover only the bounded evaluation set. A new query needs
  an admitted embedding window before GPU-offline retrieval can use it.
- Reciprocal-rank fusion is configured but cannot be statistically tuned with
  this dataset.
- Phase 08 physical multi-camera capacity evidence remains deferred.

## Required follow-up before an accuracy claim

Build an operator-reviewed query/relevance set across physical cameras,
events, negative clips, time ranges and appearance variations; then rerun
Precision@K, Recall@K and nDCG with confidence intervals. That follow-up is
not part of Phase 12 completion and does not start Phase 13.
