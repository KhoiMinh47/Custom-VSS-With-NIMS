# Phase 12 search evaluation

The bounded query set mixes provisional Phase 09 event labels with one
manually reviewed Phase 06 snapshot. It is sufficient to exercise
Precision@K/nDCG and compare action, attribute, and fusion routes, but it is
not a production accuracy dataset. Generated JSON results are written here.

The 2026-07-29 bounded run used four queries over three selected clips and
three manually bounded object crops:

- mean Precision@K: `0.3833333333`;
- mean nDCG@K: `0.9077324384`;
- routes exercised: action, attribute and fusion;
- search-by-image: three object matches returned;
- critic: one actual Cosmos3 top-result verdict, followed by a verified
  unavailable fallback that preserved all ranked results.

See `error-analysis.md` before interpreting these metrics.
