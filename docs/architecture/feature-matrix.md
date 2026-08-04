# PoC feature matrix

Scope mục tiêu là một store và khoảng 10 camera. Current runtime có một
physical `cam-01`; feature completeness và physical scale evidence là hai gate
khác nhau.

| Capability | Required path | Current implementation/evidence | Status |
| --- | --- | --- | --- |
| Stable camera registry | `store_id` + stable `camera_id` + secret ref | Physical-only `cam-01`; replay history recoverable | PARTIAL scale |
| RTSP add/delete | Browser → fixed VIOS adapter | Add/inventory/delete; credentials scrubbed; `cam-01` protected | Implemented |
| Recording/timeline | VIOS video plane independent of AI | Recording/live/snapshot/clip/reconnect evidence | PASS_WITH_RISK |
| Low-latency live | RTSP → leaky MJPEG → same-origin UI | 100 ms jitter, two-frame queue, HTTP 200 multipart | PASS |
| RT-CV detection | RT-DETR on AI substream/file | One-camera and file-batch actual detections | PASS_WITH_RISK |
| Tracking | NvDCF track IDs | One-camera metadata/soak evidence | PASS_WITH_RISK |
| 10 physical cameras | 1/2/4/6/8/10 benchmark | Not run | DEFERRED |
| Line/ROI/count/dwell/queue | RT-CV JSON → Behavior Analytics | End-to-end events, provisional ROI | PARTIAL accuracy |
| Heatmap | Metadata aggregation only | 16×9 normalized grid | Implemented |
| Candidate incident | Behavior event → deterministic selected clip | Persistence, pre/post-roll, retry | Implemented |
| Hybrid VLM verification | Selected clip → Cosmos3 verdict | Real confirmed/rejected/uncertain path | PARTIAL accuracy |
| Direct RT-VLM | Bounded stream chunk → Cosmos3 | One-camera 8 s/5-frame actual runs | PARTIAL accuracy |
| VLM Test upload | Upload → RT-CV batch → VLM → explicit Store | Real candidate/VLM run; no mock | PASS technical |
| VLM Test realtime | Persisted candidate → staged clip → VLM | UI/API/worker path present | ON_DEMAND |
| VLM Store retest | Exact post-VLM Store asset → VLM | Launch path present; no duplicate Store copy | ON_DEMAND |
| Video embedding | Selected clip → Cosmos-Embed1 | 768-d vectors and cache reuse | PARTIAL dataset |
| Object embedding | Selected crop → SigLIP2 | 1152-d vectors and image route | PARTIAL dataset |
| Action search | Text/action vector retrieval | Top-K selected clips with camera/UTC | PARTIAL evaluation |
| Attribute search | Object vector retrieval | Implemented on bounded crops | PARTIAL evaluation |
| Fusion search | Reciprocal-rank multi-route fusion | Implemented | PARTIAL evaluation |
| Search by image | Exact image/crop query | Backend implemented; browser selection gated | PARTIAL UI |
| Search critic | Top-K → Cosmos3 | Actual critic and graceful unavailable state | PARTIAL evaluation |
| Caption | Selected clips → Cosmos3 | Real timestamped captions/checkpoints | PARTIAL quality |
| Hierarchical summary | Captions → Nemotron | Real partial/final summary and recovery | PARTIAL quality |
| Grounded Q&A | Exact summary/evidence scope | Grounded answer and exact refusal proven | PARTIAL quality |
| Reports | Summary → JSON/Markdown | Incident/shift/daily with evidence/gaps | Implemented |
| Media upload for Summary | CPU validation/preparation | MP4 ready; MKV catalog-only without remux | PARTIAL format |
| LLM chat | Lease-gated fixed Nemotron endpoint | Real answer proven; provider normally offline | ON_DEMAND |
| GPU ON/OFF | UI → API → queue → host worker → admission | LLM ON/OFF runtime proven; VLM same contract | Implemented |
| GPU admission | Lease, reserve, mutual exclusion | 5 GiB reserve; serialized profiles | PASS technical |
| Kafka/DLQ | Versioned event topics and replayable failures | Topics, consumer groups, retention, DLQ | Implemented |
| Elasticsearch | Metadata/vector/caption/summary indices | Real data and mappings | Implemented |
| PostgreSQL/Redis/MinIO | Control/cache/artifact data plane | Persistence and restore evidence | Implemented |
| NVIDIA VSS UI | Search/Alerts/Video Management/Chat | Pinned upstream UI plus project overlays | PARTIAL browser gates |
| Same-origin API/BFF | Fixed loopback adapters, no generic proxy | OpenAPI/contracts/audit/security tests | PARTIAL production |
| RBAC/audit | Permission checks and structured audit | Trusted-loopback PoC mode active | PARTIAL production |
| Prometheus/Grafana | Metrics and dashboard | Core healthy; Phase 15 scrape relay pending | PARTIAL |
| Retail shelf/stock | ROI → model/embedding/VLM | No approved data/use case | LOCKED |
| Final soak/acceptance | Full E2E + 72 h + resilience | Not started | NOT_STARTED |

## Mandatory architecture boundary

```text
Raw recording
  -> media selection/preparation
  -> exact selected clip/frame/ROI
  -> VSS/model service
  -> metadata/event/embedding/summary/report
```

There is no direct raw-storage-to-output path. Raw storage never directly
produces an AI output.
