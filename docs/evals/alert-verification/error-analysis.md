# Phase 10 error-analysis protocol

Review `uncertain` alerts first, followed by prediction/feedback
disagreements. For every reviewed clip record one of `confirmed`, `rejected`,
or `uncertain` and note whether the error came from provisional ROI geometry,
clip timing, occlusion, insufficient visual context, rule semantics, or VLM
reasoning.

Do not relabel an ambiguous clip as a confident positive or negative. Adjust
prompt versions separately from behavior-rule config versions so changes stay
auditable. Real-camera precision/recall remains `PARTIAL` until enough
operator-approved labels exist.
