# GPU admission controller

Project-local guard for serialized GPU-heavy workloads. It reads live
`nvidia-smi` telemetry, rejects conflicting known containers, checks a reviewed
per-profile budget and writes an atomic lease only when admission succeeds.

The required shared reserve is `5120 MiB`. This is free-VRAM headroom, not a
request to shrink model weights or force Cosmos3 to memory utilization
0.3–0.4. Cosmos3 uses the reviewed standard profile documented in
[`PROJECT_STATE.md`](../../PROJECT_STATE.md).

Approved profiles include realtime/file RT-CV, local VLM/LLM, direct RT-VLM,
embedding, search critic/decomposition and summarization. The RTX PRO 5000
Blackwell topology is experimental for this project and is not claimed as
NVIDIA-validated. A lease proves only that the project gate admitted a
workload at that moment; provider health must be checked separately.
