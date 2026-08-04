# Phase 13 summarization service

The service accepts only explicit `selected-clip://` assets with stable
`store_id`, `camera_id`, UTC bounds, schema/model/prompt versions and content
hashes. One selected clip is one caption checkpoint; a time-window job is an
ordered sequence of selected clips. Intervals without selected evidence are
reported as `unobserved`, never as proof that no event occurred.

Captioning (Cosmos3) and hierarchical synthesis/Q&A (Nemotron) run in separate
GPU admission windows. Job state is atomically persisted after every chunk,
so an interrupted `captioning` or `summarizing` job returns to its last safe
queue state on restart. Exhausted caption retries are retained in the local
DLQ. Reports are rendered as JSON and Markdown from already grounded
summaries.

The CPU service has a persisted-job queue worker. It does not start models or
change GPU admission; it processes `queued_caption`/`queued_summary` only when
the matching fixed lease and provider are ready. A Phase 15 host-worker command
may bind one exact job to a confirmed `summary_caption` or `summary_reasoning`
window, then stop the provider and restore RT-CV at the checkpoint boundary.

The container mounts the selected-media directory read-only. It has no video
recording storage mount.
