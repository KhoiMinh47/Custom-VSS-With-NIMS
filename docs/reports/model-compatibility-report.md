# Model and NIM compatibility report

- Status: **PASS_WITH_RISK**
- VSS baseline: 3.2.1
- GPU: NVIDIA RTX PRO 5000 Blackwell 48 GB
- Topology: `LOCAL_SERIALIZED`
- Host policy: explicit unsupported-host acknowledgement dated 2026-07-23

## Verified stack

| Role | Artifact | Result |
|---|---|---|
| LLM | Nemotron Nano 9B v2, BF16 TP1 | Profile compatible; cache checksum and smoke PASS |
| VLM | Cosmos3 Nano Reasoner, BF16 TP1 | Profile compatible; 31/31 checksum and smoke PASS |
| RT-CV | RT-DETR Warehouse 2D v1.0.2 FP16 | Official NGC ONNX downloaded and SHA-256 pinned |
| Tracker | NvDCF | Selected in the VSS runtime manifest |
| Object embedding | SigLIP2 v1.1 | Official NGC ONNX, weights and tokenizer downloaded |
| RT-Embed | Cosmos-Embed1 448p anomaly detection | Download, ONNX export, TensorRT build, ready and restart reuse PASS |

## NIM runtime evidence

- Nemotron profile:
  `5cf34bab34141258d0cc836c66684642d3e3f32b4daaa2008e48bd289d6bc84b`
- Cosmos3 Nano profile:
  `e55fdb44f41441032f546360d0dcf61caa8b39fa2852d31124c03953d01e1cb3`
- Both NIMs advertise `max_model_len=32768`.
- Nemotron requires `NIM_MAX_NUM_SEQS=4` on this 48 GB GPU; the image default
  attempted a 33.75 GiB Mamba cache and OOMed.
- Cosmos3 has 22.96 GiB available KV cache and measured maximum concurrency
  5.10x at 32K context.
- NIMs were started one at a time and no smoke container remains running.

## Persistent storage

- Nemotron cache: 17 GB.
- Cosmos3 Nano cache: 17 GB.
- RT-DETR: 84 MB on disk.
- SigLIP2: 4.3 GB.
- Cosmos-Embed1 model cache: 4.5 GB.
- Cosmos-Embed1 ONNX/TensorRT repository: 6.8 GB.
- Model storage is under `/mnt/storage1/ntc-vss-retail-poc`, exposed through
  project-local symlinks.

Detailed file hashes are in `artifacts/manifests/*-digests.txt` and the pinned
summary is `artifacts/manifests/model-digests.json`.

## Cache-reuse proof

The Cosmos-Embed1 restart reached ready in about 60 seconds. Its restart log
reports:

- cached model selected;
- video/text ONNX export skipped because files exist;
- video/text TensorRT creation skipped because engines exist.

## Remaining risks

- AlmaLinux 8.10, Docker 26.1.3, Compose 2.27.0 and driver 590.48.01 differ
  from the documented VSS 3.2.1 host baseline.
- Docker data storage has only about 46 GB free. The image pull guard stopped
  before `vss-rt-vlm:3.2.1`; no prune or deletion was performed.
- Full 10-camera deployment and throughput benchmarking belong to later phases.

