# Host compatibility report — VSS 3.2.1

- Assessment date: 2026-07-23
- Result: **PASS_WITH_RISK (explicit user override)**
- Host changes performed: none

NVIDIA's current VSS prerequisites list Ubuntu 22.04/24.04 for x86 hosts,
specific 580-series drivers, NVIDIA Container Toolkit 1.17.8+, Docker 28.3.3+
and earlier than 29.5.0, Compose 2.39.1+, NGC CLI 4.10.0+, and minimum system
capacity including an 18-core CPU, 128 GB RAM and 1 TB SSD:
https://docs.nvidia.com/vss/latest/prerequisites.html

## Gate results

| Gate | Required | Detected | Result |
|---|---|---|---|
| GPU | RTX PRO 5000 target | NVIDIA RTX PRO 5000 Blackwell | PASS |
| VSS GPU validation | Validated GPU or OTHER | Not validated; OTHER experimental | PASS_WITH_RISK |
| VRAM | At least 47,000 MiB for 48 GB target | 48,935 MiB | PASS |
| CUDA container visibility | `nvidia-smi` in container | Passed with CUDA 12.8.1 base image | PASS |
| NVIDIA CDI | GPU devices listed | GPU 0, UUID and `all` listed | PASS |
| CPU | At least 18 cores | 40 logical CPUs | PASS |
| RAM | At least 128 GB decimal | 134,272,749,568 bytes | PASS |
| OS | Ubuntu 22.04/24.04 | AlmaLinux 8.10 | FAIL |
| NVIDIA driver | Supported VSS x86 baseline | 590.48.01 | FAIL |
| Container Toolkit | 1.17.8+ | 1.19.0 | PASS |
| Docker Engine | >=28.3.3 and <29.5.0 | 26.1.3 | FAIL |
| Docker Compose | 2.39.1+ | 2.27.0 | FAIL |
| NGC CLI | 4.10.0+ | Not installed | FAIL |
| NGC API key | Loaded, never logged | Loaded; value not recorded | PASS |
| SSD capacity | At least 1 TB | ~399 GB filesystem | FAIL |
| Project free space | PoC gate >=250 GB | ~149 GB | FAIL |

## Evidence

All raw command output is under `artifacts/preflight/`, including:

- `nvidia-smi.csv` and `nvidia-smi-q.txt`
- `nvidia-ctk-cdi.txt` and `nvidia-container-cli.txt`
- `container-gpu.txt`
- `docker-version.txt`, `docker-compose-version.txt`, `docker-info.txt`
- `lscpu.txt`, `memory.txt`, `disk-bytes.txt`
- `ngc-version.txt`, `ngc-api-key-status.txt`
- `ports.tsv`
- `preflight-result.env`

The API key evidence records only `SET`, never the value.

## Decision

The user explicitly acknowledged the unsupported-host risks on 2026-07-23 and
authorized downloads. Under that override, compatible NIM profiles were
discovered and the local serialized model stack passed smoke tests. This does
not make the host NVIDIA-supported and does not approve a full 10-camera stack.

Model/cache storage was redirected to `/mnt/storage1`; Docker image storage
remains constrained under `/home/docker-data`, where a 55 GB safety guard
stopped the remaining VSS image pull without pruning data.

## Required remediation

1. Reprovision or use an x86 Ubuntu 22.04/24.04 host supported by VSS.
2. Install the VSS-documented driver baseline for the selected Ubuntu release;
   do not change the driver on this shared host without an approved maintenance
   window.
3. Upgrade Docker Engine and Compose to the documented supported range.
4. Install NGC CLI 4.10.0+.
5. Move/expand Docker data storage. Model artifacts already use the larger
   `/mnt/storage1` filesystem.
6. Re-run `scripts/preflight.sh` and remove the override only after all host
   gates pass.

## Risk notes

- RTX PRO 5000 Blackwell remains an experimental `OTHER` target even after host
  remediation.
- The 48 GB topology requires serialized GPU profiles unless benchmarks prove
  safe overlap.
- No H100/RTX PRO 6000 throughput claim applies to this machine.

## Rollback

Phase 02 made no host configuration changes. The CUDA smoke-test container used
`--rm`; its image is preserved according to the no-prune policy.
