# Phase capability guide

Guide nhanh để map capability về phase. Trạng thái runtime lấy từ
`PROJECT_STATE.md`; giải thích theo nhóm nằm trong `phase.md`.

| Phase | Capability owner | Primary output | Current status |
| ---: | --- | --- | --- |
| 00 | Scope and architecture | ADR, invariants, feature matrix | PASS |
| 01 | Project isolation | `.venv`, cache/runtime layout, safe scripts | PASS |
| 02 | Host/GPU preflight | compatibility report | PASS_WITH_RISK |
| 03 | NVIDIA VSS release | pinned source/images/digests | PASS_WITH_RISK |
| 04 | Model/NIM lifecycle | model manifest, cache, engines | PASS_WITH_RISK |
| 05 | Data infrastructure | Kafka, ES, PG, Redis, MinIO, metrics | PASS |
| 06 | Video plane | RTSP/record/live/timeline/selected media | PASS_WITH_RISK |
| 07 | Realtime vision | RT-DETR/NvDCF metadata for `cam-01` | PASS_WITH_RISK historically; runtime unavailable now |
| 08 | Physical scale | 1→10 camera capacity/soak | DEFERRED |
| 09 | Behavior | count/ROI/dwell/zone/queue/heatmap/candidate | PARTIAL |
| 10 | Hybrid VLM | selected-clip verification and review | PARTIAL |
| 11 | Direct RT-VLM | direct semantic alert | PARTIAL |
| 12 | Semantic search | vectors, retrieval, fusion, critic | PARTIAL |
| 13 | Video understanding | captions, summary, Q&A, reports | PARTIAL / approved |
| 14 | Retail AI | shelf/stock/planogram/SKU | LOCKED |
| 15 | Product surface | NVIDIA UI, BFF, controls, VLM Test | PARTIAL |
| 16 | Acceptance | full E2E/soak/security/final reports | NOT_STARTED |

## Capability dependency

```text
VIOS selected media
├── RT-CV realtime/file batch
│   └── Behavior candidate
│       └── Hybrid Cosmos3 verification
├── Cosmos-Embed1 / SigLIP2 indexing
│   └── Semantic search + optional critic
└── Cosmos3 caption
    └── Nemotron summary/Q&A/report

Phase 15 NVIDIA UI/BFF exposes these workflows through one loopback origin.
```

## Evidence interpretation

- `PASS_WITH_RISK`: technical gate passed under unsupported host/topology risk.
- `PARTIAL`: implementation exists, but scale, accuracy, browser or production
  integration evidence remains incomplete.
- `DEFERRED`: user chose not to run the phase; later phases do not implicitly
  complete it.
- `LOCKED`: missing approved business/data inputs; implementation must not be
  fabricated.
- Provider `standby` is normal for on-demand GPU services and is not equivalent
  to a failed CPU control plane.

## Read next

- [Project phases](../phase.md)
- [Pipeline catalog](architecture/PIPELINES.md)
- [Feature matrix](architecture/feature-matrix.md)
- [Current project state](../PROJECT_STATE.md)
