# Documentation index

Tài liệu được chia theo mục đích để tránh trộn kiến trúc mục tiêu, trạng thái
runtime và evidence lịch sử.

## Bắt đầu đọc

1. [README tổng quan](../README.md)
2. [Trạng thái hiện tại](../PROJECT_STATE.md)
3. [Toàn bộ pipeline](architecture/PIPELINES.md)
4. [Services, model và data stores](architecture/SERVICES-AND-MODELS.md)
5. [Phase guide](../phase.md)

## Kiến trúc hiện hành

- [Pipeline catalog](architecture/PIPELINES.md)
- [Service/model catalog](architecture/SERVICES-AND-MODELS.md)
- [Feature matrix](architecture/feature-matrix.md)
- [Phase capability guide](PHASE-CAPABILITY-GUIDE.md)

## Architecture Decision Records

- [ADR-001 — PoC scope](decisions/ADR-001-poc-scope.md)
- [ADR-002 — Video/AI plane boundary](decisions/ADR-002-video-ai-plane.md)
- [ADR-003 — VSS release and model stack](decisions/ADR-003-vss-release-model-stack.md)
- [ADR-004 — Project-local cache](decisions/ADR-004-project-local-cache.md)
- [ADR-005 — Single-GPU admission](decisions/ADR-005-single-gpu-admission-control.md)
- [ADR-006 — Infrastructure data plane](decisions/ADR-006-infrastructure-data-plane.md)
- [ADR-007 — Phase ordering exception](decisions/ADR-007-phase14-lock-phase15-ordering.md)

ADR là quyết định kiến trúc, không phải runtime status.

## Reports và evaluation

- Reports: [host compatibility](reports/host-compatibility-report.md),
  [VSS release resolution](reports/vss-release-resolution.md),
  [model compatibility](reports/model-compatibility-report.md),
  [camera onboarding](reports/camera-onboarding-report.md) và
  [hybrid vs direct VLM](reports/hybrid-vs-direct-vlm.md).
- Behavior evaluation: [summary](evals/behavior-analytics/README.md) và
  [error analysis](evals/behavior-analytics/error-analysis.md).
- Hybrid alert evaluation: [summary](evals/alert-verification/README.md) và
  [error analysis](evals/alert-verification/error-analysis.md).
- Direct RT-VLM evaluation: [summary](evals/rt-vlm-alert/README.md) và
  [error analysis](evals/rt-vlm-alert/error-analysis.md).
- Search evaluation: [summary](evals/search-results/README.md) và
  [error analysis](evals/search-results/error-analysis.md).
- Summarization evaluation: [summary](evals/summarization/README.md) và
  [error analysis](evals/summarization/error-analysis.md).

Các con số trong evaluation chỉ có giá trị trong dataset và checkpoint ghi ở
chính tài liệu đó; không tự suy rộng thành production accuracy.

## Runbooks

- [GPU Control Center](runbooks/gpu-control-center.md)
- [VLM Test](runbooks/phase15-vlm-test.md)
- [Phase 15 recovery](runbooks/phase15-app-recovery.md)
- [RTSP down](runbooks/rtsp-down.md)
- [GPU OOM](runbooks/gpu-oom.md)
- [NIM down](runbooks/nim-down.md)
- [Kafka lag](runbooks/broker-lag.md)
- [Elasticsearch red](runbooks/elasticsearch-red.md)

## Handoffs

`handoffs/` là nhật ký kỹ thuật bất biến theo phase. Handoff cũ có thể mô tả
runtime tại một thời điểm đã qua. Trạng thái hiện hành luôn lấy từ
[PROJECT_STATE.md](../PROJECT_STATE.md), sau đó mới dùng handoff để truy lịch
sử/evidence.

- Foundation: [Phase 00](handoffs/PHASE-00-HANDOFF.md),
  [01](handoffs/PHASE-01-HANDOFF.md),
  [02](handoffs/PHASE-02-HANDOFF.md),
  [03](handoffs/PHASE-03-HANDOFF.md),
  [04](handoffs/PHASE-04-HANDOFF.md),
  [05](handoffs/PHASE-05-HANDOFF.md).
- Video/realtime: [Phase 06](handoffs/PHASE-06-HANDOFF.md),
  [07](handoffs/PHASE-07-HANDOFF.md),
  [09](handoffs/PHASE-09-HANDOFF.md).
- Semantic AI: [Phase 10](handoffs/PHASE-10-HANDOFF.md),
  [11](handoffs/PHASE-11-HANDOFF.md),
  [12](handoffs/PHASE-12-HANDOFF.md),
  [13](handoffs/PHASE-13-HANDOFF.md).
- Product surface: [Phase 15](handoffs/PHASE-15-HANDOFF.md).

Không có Phase 08 handoff vì phase bị deferred; Phase 14 bị locked và Phase 16
chưa bắt đầu.

## Service-level documentation

Mỗi service có README cạnh source. Các README giải thích contract và giới hạn
của riêng service; pipeline xuyên service được chuẩn hóa ở
[PIPELINES.md](architecture/PIPELINES.md).

- UI/control: [NVIDIA VSS UI](../apps/vss-ui/README.md),
  [Unified API](../services/api/README.md),
  [control plane](../services/control-plane/README.md),
  [agent router](../services/agent/README.md) và
  [MCP catalog](../services/mcp/README.md).
- Video/realtime: [Video Management](../services/video-management/README.md),
  [RT-CV](../services/rt-cv/README.md),
  [RT-CV file batch](../services/rtcv-file-batch/README.md),
  [Behavior Analytics](../services/behavior-analytics/README.md),
  [heatmap](../services/heatmap/README.md) và
  [incidents](../services/incidents/README.md).
- VLM/alert: [alert verification](../services/alert-verification/README.md),
  [direct RT-VLM](../services/rt-vlm-alert/README.md) và
  [VLM Test](../services/vlm-test/README.md).
- Search/understanding: [RT-Embedding](../services/rt-embedding/README.md),
  [search](../services/search/README.md),
  [summarization](../services/summarization/README.md),
  [reporting](../services/reporting/README.md) và
  [media intake](../services/media-intake/README.md).
- GPU lifecycle: [admission controller](../services/gpu-admission-controller/README.md)
  và [host worker](../services/gpu-control-worker/README.md).

Deployment overlays are documented in
[deploy/overlays/README.md](../deploy/overlays/README.md).

## Security

- [Phase 15 threat model](security/phase15-threat-model.md)

## Tài liệu kế hoạch

[Full phased plan](../PLAN_NVIDIA_VSS_RETAIL_POC_1_STORE_10_CAMERAS_v2.2_PHASED.md)
là target architecture và execution contract. Một capability xuất hiện trong
plan không đồng nghĩa capability đó đã chạy; đối chiếu `PROJECT_STATE.md` và
feature matrix trước khi công bố.
