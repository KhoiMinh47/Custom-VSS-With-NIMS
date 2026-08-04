# PHASE-02 HANDOFF

## Result

PASS_WITH_RISK

## Scope completed

- Collected OS, kernel, CPU, RAM, disk, network, GPU, driver, Docker, Compose,
  NVIDIA Container Toolkit/CDI, NGC CLI, port and Docker inventory evidence.
- Ran a CUDA 12.8.1 container smoke test.
- Verified the NGC API key is loaded without printing or recording its value.
- Produced machine-readable gate output, detected hardware config and a
  compatibility report.

## Files created

- `config/preflight.yaml`
- `config/hardware.detected.yaml`
- `scripts/preflight.sh`
- `docs/reports/host-compatibility-report.md`
- `docs/handoffs/PHASE-02-HANDOFF.md`
- Generated evidence under `artifacts/preflight/`

## Files modified

- `PROJECT_STATE.md`

## Commands executed

```text
nvidia-smi ...
nvidia-smi -q
nvidia-ctk cdi list
nvidia-container-cli info
uname -a
lsb_release -a
lscpu
free -h
df -hT /home/ntcai/KM
docker version
docker compose version
docker images --digests
docker ps -a
docker system df -v
docker run --rm --gpus all nvcr.io/nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
bash scripts/preflight.sh
```

No driver, Docker, kernel or host setting was changed.

## Services/images/models affected

- Pulled/used only the allowed CUDA smoke-test image.
- No VSS, NIM or model image/cache was downloaded.
- No GPU service remains running.

## Validation evidence

See `artifacts/preflight/preflight-result.env` and
`docs/reports/host-compatibility-report.md`.

Passed gates: GPU, VRAM, CPU, RAM, Container Toolkit/CDI, CUDA container and
NGC key presence.

Failed baseline gates: OS, driver baseline, Docker, Compose, host NGC CLI and
Docker filesystem capacity. The user explicitly acknowledged these risks on
2026-07-23 and authorized continuing downloads. Model caches were placed on
`/mnt/storage1`, which had more than 850 GB free throughout the work.

## Metrics

- GPU: RTX PRO 5000 Blackwell, 48,935 MiB.
- CUDA container GPU visibility: PASS.
- Hard gates passed: 7.
- Hard gates failed: 7.

## Known issues

The local serialized model stack was verified, but the host remains outside
NVIDIA's documented support baseline. Full-stack deployment is not approved.

## Rollback

No host changes require rollback. Preserve the CUDA test image and evidence.

## Exact next phase

Review host remediation and expand/move Docker data storage before full-stack
deployment. Phase 03/04 proceeded only under the recorded user override.

## Approval required

YES before changing host software or starting the full VSS runtime.
