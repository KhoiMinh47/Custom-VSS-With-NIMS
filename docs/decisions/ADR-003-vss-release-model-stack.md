# ADR-003: VSS release and model stack

- Status: Accepted
- Date: 2026-07-23

## Decision

- NVIDIA VSS release baseline: 3.2.1.
- LLM: NVIDIA Nemotron Nano 9B v2 via NIM-compatible API.
- VLM: NVIDIA Cosmos3 Nano Reasoner via NIM or VSS RT-VLM.
- Detection: RT-DETR Warehouse 2D v1.0.2 FP16.
- Tracking: NvDCF.
- Video embedding: Cosmos-Embed1 448p anomaly-detection FP16 TensorRT.
- Object embedding: SigLIP2 SO400M patch16 256 FP16.

Deployment assets, not guessed version symmetry, determine image tags. Digests
must be recorded after pull.

## Consequences

Changing an embedding model or vector semantics requires re-indexing. Retail
accuracy claims require real data and evaluation; the warehouse detector is
not treated as an SKU model.

## Rollback

Restore the previous reviewed model manifest, image digests and compatible
indices/engines. Do not delete cached artifacts automatically.
