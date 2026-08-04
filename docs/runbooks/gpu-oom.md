# GPU OOM

## Symptom

GPU provider exits, health becomes unavailable, or CUDA reports out-of-memory.

## Detection

- Open the Phase 15 control room and inspect on-demand provider state.
- Check `nvidia-smi` and the active lease under `runtime/gpu-admission/`.
- Review only the affected provider log; never print its environment.

## Immediate mitigation

1. Stop the admitted provider with its phase-specific stop target.
2. Revoke only that provider's lease through the existing stop script.
3. Restore the approved RT-CV profile.
4. Do not delete model caches, TensorRT engines, images or volumes.

## Root-cause checklist

- Confirm no overlapping GPU-heavy profile bypassed admission.
- Compare requested context/batch/frame count with its approved profile.
- Confirm the image digest and model profile ID remain pinned.

## Recovery validation

Run the affected phase health check, `make rtcv-health`, and record GPU memory.

## Data-loss assessment

Check the phase queue, retry/DLQ and last checkpoint. Never treat a mock result
as evidence that the failed model request completed.
