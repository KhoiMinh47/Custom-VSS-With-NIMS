# Services, models and data stores

## Runtime topology

Project dùng một browser origin `127.0.0.1:39510`. NVIDIA VSS UI chạy private
ở `39511`; same-origin gateway/BFF định tuyến tới các fixed loopback service.
Browser không được chọn arbitrary upstream URL.

## NVIDIA model stack

| Component | Artifact | Runtime | Output | Current policy |
| --- | --- | --- | --- | --- |
| RT-DETR | Warehouse 2D v1.0.2, ResNet-50, 640×640 FP16 | VSS RT-CV 3.2.1 + TensorRT | person box/confidence | realtime/file batch, serialized with large NIMs |
| NvDCF | DeepStream tracker | VSS RT-CV | track ID/trajectory | runs with detector |
| Cosmos3 | `nvidia/cosmos3-nano-reasoner`, NIM image 1.7 | OpenAI-compatible VLM / VSS RT-VLM | verdict, caption, critic, visual answer | on-demand; standard profile; 5 GiB reserve gate |
| Nemotron | `nvidia/nvidia-nemotron-nano-9b-v2`, NIM image 1 | OpenAI-compatible LLM | decomposition, chat, summary, Q&A | on-demand; mutually exclusive with VLM |
| Cosmos-Embed1 | 448p anomaly-detection model, FP16 TRT | VSS RT-Embedding 3.2.1 | 768-d video vector | indexing window only |
| SigLIP2 | SO400M patch16 256, FP16 TRT | RT-CV image adapter | 1152-d object/image vector | indexing window only |

Pinned source, image digests, profile IDs, hashes and engine build metadata are
in `config/models/model-manifest.yaml`.

### Cosmos3 responsibilities

- Phase 10 hybrid alert verification;
- Phase 11 direct semantic alert;
- Phase 12 top-K search critic;
- Phase 13 selected-clip caption and visual evidence extraction;
- Phase 15 VLM Test upload/realtime/store retest;
- future Phase 14 uncertain retail verification.

Cosmos3 không detect/tracking liên tục trên toàn bộ camera và không thay
RT-DETR.

### Nemotron responsibilities

- complex search query decomposition;
- NVIDIA UI chat when an LLM lease is active;
- hierarchical summary synthesis;
- grounded Q&A/report reasoning.

Nemotron không đọc pixel/video, không tạo video embedding và không thay VLM.

## Application and workflow services

| Service | Port | Plane | Vai trò |
| --- | ---: | --- | --- |
| NVIDIA VSS UI | 39511 private | UI | Upstream Search, Alerts, Video Management, Chat |
| Unified API/BFF | 39510 public loopback | Control | Same-origin adapters, RBAC, audit, GPU queue, overlays |
| Camera live | 8090 | Presentation | Low-latency MJPEG và best-effort AI overlay |
| VIOS | 30888 and internal | Video | RTSP sensor/proxy, recording, timeline, picture, selected clip |
| RT-CV core | 39000/39080 | GPU/realtime | RT-DETR/NvDCF, protobuf normalization, health/metrics |
| Behavior Analytics | 39110 | CPU analytics | count, ROI, dwell, zone, queue, heatmap, candidates |
| Incident Queue | 39121 | CPU workflow | selected clip, hashing, candidate persistence |
| Alert Review/Verification | 39120 | CPU + VLM client | verdict persistence, retry/DLQ, feedback/evaluation |
| Direct RT-VLM collector | 39210 | CPU result | direct semantic alert persistence/comparison |
| Search | 39310 | CPU search | vector retrieval, fusion, fallback routing, API/UI |
| RT-Embedding | 39320 | GPU on-demand | Cosmos-Embed1 indexing |
| SigLIP2 adapter | 39321 | GPU on-demand | object/image embeddings |
| Summarization | 39410 | CPU orchestrator | caption/summary checkpoints, Q&A, report source |
| Media Intake | 39420 | CPU media | validated Summary uploads and quarantine/restore |
| VLM Test | 39520 | CPU workflow | staging, jobs, realtime candidate, explicit Store |
| GPU host worker | host process | Control | executes allowlisted start/stop commands |
| Admission controller | host/project runtime | Control | lease, priority, VRAM reserve, mutual exclusion |

## Data infrastructure

### Kafka

Kafka là event bus, không phải database kết quả cuối. Nó tách producer và
consumer, cho phép consumer group, retry, replay và đo lag.

| Topic | Producer | Consumer / purpose |
| --- | --- | --- |
| `mdx-raw` | VSS RT-CV | metadata normalizer/file-batch candidate |
| `vss.rt-cv.frames` | metadata normalizer | behavior analytics |
| `vss.behavior.events` | behavior analytics | incident service, Elasticsearch |
| `vss.incidents.candidate` | incident queue | alert verifier |
| `vss.incidents.verified` | alert verifier | review/search/report consumers |
| `vss.rt-vlm.captions` | VSS RT-VLM | direct result collector |
| `vss.embeddings.video` | RT-Embedding adapter | vector persistence/indexing |
| `vss.embeddings.object` | SigLIP2 adapter | object vector persistence/indexing |
| `mdx-vlm-captions` | caption workflow | summary/event indexing |
| `mdx-structured-events-summary` | summary workflow | downstream report/search |
| `vss.jobs.status` | workflow services | job status consumers |
| `vss.dlq` | failed consumers | controlled inspection/replay |

Topic retention và partitions được pin trong `config/broker/topics.txt`.

### Elasticsearch

Elasticsearch là analytics/search plane:

- normalized RT-CV metadata;
- behavior events;
- candidate/verified/direct incidents;
- video and object vectors;
- timestamped captions and summaries.

Index template/mapping/ILM nằm trong `config/elasticsearch/`. Vector document
phải mang model version và dimension; đổi model bắt buộc re-index generation.

### PostgreSQL

Project PostgreSQL là control plane cho schema store/camera reference, config,
job, role, audit và retention. Camera credential chỉ là secret reference.

VIOS có PostgreSQL riêng để quản lý video-system state. Hai database không
được hiểu là một; raw video bytes không nằm trong project control-plane
PostgreSQL.

### Redis

Project Redis dùng cache/coordination. VIOS có Redis riêng cho video runtime.
Redis không phải source of truth cho incident, summary hay audit lâu dài.

### MinIO

MinIO cung cấp S3-compatible artifact/object storage cho PoC và future selected
assets. VIOS vẫn là chủ raw recording/timeline; MinIO không tạo direct path từ
raw recording sang AI output.

### Runtime filesystem

Một số PoC services persist atomic JSON/job/media state dưới `runtime/`:

- selected/prepared incident clips;
- VLM Test staging và post-VLM Store;
- media-intake active/quarantine/prepared files;
- summary checkpoints và reports;
- admission leases, command queue và audit;
- generated indices/cache evidence.

Các thư mục này ignored khỏi Git và phải được backup bằng script dự án.

### Prometheus và Grafana

Prometheus scrape health/metrics và Grafana hiển thị operational dashboard.
Known limitation: Phase 15 API bind host-loopback nên target bridge-network cũ
cần safe relay/scrape design; không được sửa bằng cách bind API ra `0.0.0.0`.

## Storage planes

| Plane | Chứa gì | Ai được đọc |
| --- | --- | --- |
| VIOS raw recording | camera recording/timeline | VIOS playback và media selection only |
| Selected incident media | exact bounded clip + provenance | verifier/search/summary allowlisted workflows |
| Media Intake prepared | validated upload for Summary | Phase 13 read-only |
| VLM Test staging | upload/realtime/store-retest work media | RT-CV batch + VLM Test verifier |
| Post-VLM Store | explicit user-saved media after completed VLM | Video Management VLM section/retest |
| Elasticsearch | metadata/event/vector/caption/summary | APIs/search/report services |

## GPU profiles

| Logical profile | Provider | Priority/behavior |
| --- | --- | --- |
| `realtime_core` | RT-CV | highest realtime priority |
| `rtcv_file_batch` | RT-CV file batch | bounded upload test window |
| `alert_verification` / `local_vlm` | Cosmos3 | event/test verification |
| `direct_rt_vlm` | Cosmos3 + RT-VLM | explicit one-camera mode |
| `rt_embedding` | Cosmos-Embed1 | selected clip indexing |
| `siglip_object` | SigLIP2 | crop/image indexing |
| `search_llm` | Nemotron | query decomposition |
| `search_critic` | Cosmos3 | top-K only |
| `summary_caption` | Cosmos3 | checkpointed caption window |
| `summary_reasoning` | Nemotron | summary/Q&A window |

Only one conflicting heavy profile may hold a lease. Current LLM/VLM reserve
is 5120 MiB. Runtime telemetry, not static estimates, decides admission.

The host may also run unrelated NIMs. At the latest checkpoint a separate
`nemo-retriever-service-dev` stack was serving VL embedding, OCR,
page-element detection and table-structure detection. Those containers are
not project services and are not listed as project model dependencies, but
their live VRAM consumption is included by admission telemetry.

## Security boundary

- all public project ports are loopback-only;
- browser uses 39510 only;
- gateway has fixed upstream allowlist and no generic proxy;
- UI/API containers mount no camera secrets, Docker socket or GPU device;
- mutations require same-origin checks and permissions;
- audit/log output omits secrets and raw credentials;
- trusted-loopback admin is PoC-only and must be replaced before LAN/production.

## Current known gaps

- RT-CV realtime was unavailable at the latest checkpoint;
- one physical camera is not 10-camera capacity evidence;
- Phase 08 is deferred and Phase 14 is locked;
- model/business accuracy datasets are too small for production claims;
- production TLS/IdP, distributed tracing and DCGM are incomplete;
- Phase 15 Prometheus scrape integration needs a loopback-safe design.
