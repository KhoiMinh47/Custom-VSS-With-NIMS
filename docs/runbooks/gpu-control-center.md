# GPU Control Center runbook

## Purpose

The Phase 15 UI can switch the single experimental RTX PRO 5000 Blackwell
between one realtime or on-demand GPU workload. This is project admission
control, not an NVIDIA-validated topology.

## Operator workflow

1. Open `http://127.0.0.1:39510/dashboard`.
2. Use `Operator access` and enter a configured operator token.
3. Open `Điều phối GPU`.
4. Review the current profile, VRAM, utilization and worker state.
5. Select a task-oriented profile and review its impact.
6. Confirm the transition and keep the page open until it completes.
7. Use `Khôi phục Camera realtime` when the on-demand window is finished.

Only one transition can be queued or running. The buttons are disabled while
the worker is busy. Every request and result is audited.

## Profiles

- `Camera realtime`: restores RT-CV, behavior analytics and default hybrid
  alerts; stops on-demand model profiles.
- `Xác minh cảnh báo đang chờ`: bounded Cosmos3 window for the durable Phase
  10 hybrid incident queue.
- `Cảnh báo ngữ nghĩa`: direct RT-VLM on the approved `cam-01` scope.
- `Lập chỉ mục video`: Cosmos-Embed1 selected-media indexing.
- `Lập chỉ mục đối tượng`: SigLIP2 selected object-crop indexing.
- `Hiểu câu truy vấn`: bounded Nemotron search decomposition.
- `Kiểm tra kết quả tìm kiếm`: Cosmos3 top-K critic.
- `Caption clip đã chọn`: Cosmos3 Phase 13 caption window.
- `Tạo tóm tắt & Q&A`: Nemotron Phase 13 synthesis window.

Every on-demand profile may pause RT-CV. Live video remains independent.
Model cache, checkpoints, indices, reports and raw recordings are preserved.

## Worker operations

```bash
make phase15-gpu-worker-start
make phase15-gpu-worker-stop
make phase15-health
```

Stopping the worker does not stop or change the active GPU workload. If a
transition is running, the stop script leaves the worker alive until the safe
transition finishes.

Inspect only project-local state:

```bash
sed -n '1,200p' runtime/phase15/gpu-control/worker.json
sed -n '1,200p' runtime/phase15/gpu-control/state.json
tail -100 runtime/phase15/gpu-control/worker.log
```

Do not edit request files while the worker is running. Never start a provider
manually alongside another active lease.

## Recovery

If the UI reports a failed transition, read the command message and worker
log. The worker attempts `Camera realtime` recovery automatically when a
target start script fails.

If the worker is offline:

```bash
make phase15-gpu-worker-start
make phase15-health
```

If the runtime remains ambiguous, use the existing safe default:

```bash
make alerts-default-start
make alerts-default-health
```

No recovery procedure may prune images, delete volumes, remove model caches or
delete raw video.
