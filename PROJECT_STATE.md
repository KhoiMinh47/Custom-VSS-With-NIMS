# PROJECT STATE

Nguồn trạng thái hiện hành của project. Handoff cũ là evidence lịch sử và có
thể mô tả runtime tại thời điểm khác.

## Current checkpoint

- Timestamp: `2026-08-04T09:26:55Z` (`2026-08-04 16:26:55`, Asia/Ho_Chi_Minh)
- Current phase: `PHASE-15`
- Overall status: `PARTIAL`
- Last approved phase: `PHASE-13`
- Phase 08: `DEFERRED_BY_USER`
- Phase 14: `LOCKED_BY_USER`
- Phase 16: `NOT_STARTED`

## Executive status

Project đã có các đường chạy thật cho một physical `cam-01`: VIOS video
management, RT-DETR/NvDCF, behavior analytics, hybrid Cosmos3 verification,
direct RT-VLM, Cosmos-Embed1/SigLIP2 search, Cosmos3 caption, Nemotron summary,
grounded Q&A/report và Phase 15 NVIDIA VSS UI.

Phase 15 hiện bổ sung:

- NVIDIA upstream VSS UI tại `127.0.0.1:39510`;
- Video Management có Streaming và VLM Processed Videos;
- user-managed RTSP add/delete với credential-free inventory;
- low-latency `cam-01` MJPEG presentation;
- VLM Test Upload/Realtime/Store;
- automatic upload → RT-CV file batch → candidate → VLM;
- LLM/VLM web ON/OFF qua host worker/admission;
- explicit post-VLM Save to Store.
- Real-time Alerts tab now has a same-origin gateway URL and a working rule-list
  control plane; rule start remains `PARTIAL` until an admitted real-time VLM
  provider is available.

Không được gọi project production-ready: runtime đang có một camera vật lý,
accuracy set còn nhỏ, RT-CV realtime unavailable tại checkpoint, Retail AI
chưa triển khai và topology GPU chưa được NVIDIA validate.

## Runtime health

`GET /api/v1/overview?refresh=true` tại checkpoint:

| Service group | Status |
| --- | --- |
| NVIDIA VSS UI + unified gateway | Healthy |
| Camera live presentation | Healthy |
| RT-CV realtime core | Unavailable |
| Behavior Analytics | Healthy |
| Incident Queue + Alert Review | Healthy |
| Real-time Alerts control plane | Healthy for list/read; VLM start blocked |
| Direct RT-VLM result collector | Healthy |
| Search CPU service | Healthy |
| Summary/Q&A CPU service | Healthy |
| Media Intake | Healthy |
| VLM Test control plane | Healthy |
| Elasticsearch/MinIO/Prometheus/Grafana | Healthy |
| Cosmos3 provider | Standby/offline |
| Nemotron provider | Standby/offline |
| RT-Embedding provider | Standby |
| SigLIP2 provider | Standby |
| Retail AI | Locked |

Aggregate: `14 healthy`, `1 unavailable`, `4 standby`, `1 locked`.
Global `ready=false` vì RT-CV realtime đang unavailable.

## Camera and stream state

Registry mode: `physical_camera_only`.

| Field | Current value |
| --- | --- |
| Stable camera | `cam-01` |
| Store | `store-001` |
| Main stream contract | H.265, 2560×1440, 25 FPS |
| AI substream contract | H.264, 1280×720, 25 FPS |
| Browser live capability | Available through same-origin MJPEG |
| VIOS source status | Offline at checkpoint |
| RT-CV/AI status | Unavailable at checkpoint |
| User-added streams | None at checkpoint |

`cam-01` is protected from Video Management delete. Historical replay assets
and simulated-camera image remain recoverable, but replay sources are not
physical-camera capacity evidence.

## GPU state and policy

| Item | Current value |
| --- | --- |
| GPU | NVIDIA RTX PRO 5000 Blackwell |
| VRAM total | 48935 MiB |
| VRAM used at checkpoint | 19238 MiB |
| VRAM free at checkpoint | 29166 MiB |
| Project active leases | 0 |
| LLM state | Offline |
| VLM state | Offline |
| Shared reserve | 5120 MiB |
| Worker | Online |
| RT-CV UI policy | `upload_only` |

VRAM includes VIOS and external host workloads; it is not all owned by this
project. Admission must use live telemetry. LLM and VLM remain mutually
exclusive. RT-CV, Cosmos3, Nemotron, Cosmos-Embed1 and SigLIP2 are serialized
until a measured overlap is explicitly approved.

External containers visible at this checkpoint include the separate
`nemo-retriever-service-dev` NIMs for VL embedding, OCR, page-element detection
and table-structure detection. They belong to another host/RAG workload, not
to this project's model stack, but their VRAM usage still affects admission.

Cosmos3 standard profile:

- `NIM_GPU_MEMORY_UTILIZATION=0.65`
- `NIM_MAX_MODEL_LEN=32768`
- `NIM_MAX_NUM_SEQS=1`
- `NIM_MAX_NUM_BATCHED_TOKENS=4096`

The earlier 0.3–0.4 memory experiment is historical failure evidence and is
not an active profile.

## Selected release and models

| Role | Selected artifact |
| --- | --- |
| VSS baseline | 3.2.1, tag `v3.2.1`, commit `7640d917047cf7b0fd3085eefb8282754b56bc94` |
| NVIDIA VSS UI image | intentional release tag `vss-agent-ui:3.2.0`, digest-pinned |
| LLM | `nvidia/nvidia-nemotron-nano-9b-v2` |
| VLM | `nvidia/cosmos3-nano-reasoner` |
| Detector | RT-DETR Warehouse 2D v1.0.2, ResNet-50, 640×640 FP16 |
| Tracker | NvDCF |
| Video embedding | Cosmos-Embed1-448p-anomaly-detection, 768 dimensions |
| Object embedding | SigLIP2 SO400M patch16 256, 1152 dimensions |

The RTX PRO 5000 Blackwell topology is experimental and not NVIDIA-validated
for this deployment.

## Pipeline status

| Pipeline | Status | Evidence boundary |
| --- | --- | --- |
| VIOS ingest/record/live/clip | PASS_WITH_RISK | One physical camera; replay history preserved |
| Low-latency MJPEG | PASS | HTTP 200 multipart response; best effort, not zero latency |
| Realtime RT-CV | PASS_WITH_RISK historically; unavailable now | One-camera detection/tracking/soak only |
| RT-CV file batch | PASS | Actual upload detections/candidate |
| Behavior analytics | PARTIAL | Technical events pass; ROI/accuracy provisional |
| Hybrid candidate → Cosmos3 | PARTIAL | Real inference pass; label set too small |
| Direct RT-VLM | PARTIAL | Real 8-second/5-frame runs; no accuracy labels |
| VLM Test Upload | PASS technical | Real RT-CV candidate and VLM result; Store explicit |
| VLM Test Realtime | Implemented/on-demand | Uses persisted real Phase 10 candidates |
| VLM Store retest | Implemented/on-demand | Exact Store asset; no duplicate Store copy |
| Video/action embedding | PARTIAL | Real 768-d vectors on small selected set |
| Object/image embedding | PARTIAL | Real 1152-d vectors on small crop set |
| Semantic search | PARTIAL | Action/attribute/fusion/image paths pass; small evaluation |
| Caption/summary/Q&A/report | PARTIAL | Real Cosmos3/Nemotron; small dataset/no human ratings |
| Retail AI | LOCKED | No approved ROI/product master/reference dataset |
| Unified UI/API/security | PARTIAL | Healthy loopback PoC; production IdP/TLS/tracing incomplete |

## Phase status

| Phase | Status | Summary |
| ---: | --- | --- |
| 00 | PASS | Scope/architecture contract |
| 01 | PASS | Project-local environment |
| 02 | PASS_WITH_RISK | Unsupported host baseline explicitly acknowledged |
| 03 | PASS_WITH_RISK | VSS 3.2.1 source/images pinned |
| 04 | PASS_WITH_RISK | Local serialized model stack and cache reuse |
| 05 | PASS | Infrastructure; executed first by user request |
| 06 | PASS_WITH_RISK | VIOS/video path and physical/replay validation |
| 07 | PASS_WITH_RISK | One-camera RT-CV vertical slice |
| 08 | DEFERRED_BY_USER | No ten-physical-camera capacity evidence |
| 09 | PARTIAL | Behavior rules work; accuracy open |
| 10 | PARTIAL | Hybrid VLM path works; evaluation small |
| 11 | PARTIAL | Direct RT-VLM works; evaluation small |
| 12 | PARTIAL | Search stack works; evaluation small |
| 13 | PARTIAL / approved | Summary/Q&A/report technical path works |
| 14 | LOCKED_BY_USER | Retail inputs not approved |
| 15 | PARTIAL | Current NVIDIA UI/control-plane work |
| 16 | NOT_STARTED | Full integration/soak/final handoff |

## Validation

Latest documentation/runtime repair validation:

- full unit/regression suite: `172 passed`;
- project-owned Markdown relative-link audit: `0` broken links;
- Python compilation: pass;
- JavaScript syntax: pass;
- Phase 15 healthcheck: pass for the control plane;
- NVIDIA UI injects stream overlay `v5`;
- RTSP compatibility delete route resolves and protects `cam-01`;
- live MJPEG route returned HTTP 200 and multipart bytes;
- no model/image/cache/data was deleted.

Unit mocks are contract evidence only, not proof of external model execution.
Runtime model evidence is documented in the phase handoffs/evaluation reports.

## Open blockers and risks

1. RT-CV realtime is unavailable at the current checkpoint; no new live
   candidate will be produced until the exact source/admission path is healthy.
2. One physical camera is not Phase 08 ten-camera capacity evidence.
3. Phase 09–13 accuracy claims remain partial due small/provisional datasets.
4. Phase 14 Retail AI is locked pending use case, shelf ROI, product master and
   approved reference data.
5. Phase 15 browser accessibility/multi-viewport evidence remains incomplete.
6. Prometheus still needs a safe scrape/relay for host-loopback Phase 15 API;
   do not bind the API to `0.0.0.0` as a shortcut.
7. The Real-time Alerts UI adapter is wired and its list endpoint is healthy,
   but creating a rule is blocked while the admitted Cosmos3/RTVI provider is
   unavailable; no successful live alert inference is claimed.
7. Current trusted-loopback admin mode is PoC-only and must not be exposed to
   LAN/Internet; production TLS/IdP remains incomplete.
8. Host differs from NVIDIA prerequisites: AlmaLinux 8.10, Docker 26.1.3,
   Compose 2.27.0, driver 590.48.01 and no NGC CLI 4.10+.
9. Docker/disk headroom and external GPU processes must be monitored.
10. No Phase 16 soak/final acceptance has been run.

## Active architecture rules

- raw/video storage plane remains independent from AI plane;
- selected media is required before historical AI work;
- stable identity and provenance fields are mandatory;
- GPU-heavy work uses admission and bounded windows;
- no arbitrary provider URL or Docker command from browser;
- no secret in Git/logs/audit/browser inventory;
- no prune, `down -v`, image removal, volume removal or automatic cache/model
  deletion;
- stop operations preserve data and are recoverable.

## Current documentation

- Overview: `README.md`
- Pipeline catalog: `docs/architecture/PIPELINES.md`
- Service/model catalog: `docs/architecture/SERVICES-AND-MODELS.md`
- Phase summary: `phase.md`
- Documentation index: `docs/README.md`
- Latest detailed handoff: `docs/handoffs/PHASE-15-HANDOFF.md`

## Next permitted action

Continue Phase 15 repair/validation only, unless the user explicitly changes
scope. Valid next work includes restoring realtime RT-CV safely, validating
browser UI/accessibility, and designing a loopback-safe Prometheus integration.

Do not mark Phase 08, 14, 15 or 16 complete without their missing evidence and
explicit approval.
