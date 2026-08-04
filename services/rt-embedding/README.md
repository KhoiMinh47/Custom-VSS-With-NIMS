# Phase 12 RT-Embedding adapter

This adapter calls the pinned VSS 3.2.1 RT-Embedding service with cached
Cosmos-Embed1 artifacts. Historical ingestion accepts only Phase 10
`selected-clip://` prepared media and emits deterministic 10-second,
768-dimensional documents. It never mounts or scans raw video storage.

Changing the model ID, version, or vector dimension changes the embedding
generation and requires a new index generation before writes continue.
