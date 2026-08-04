#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/env.sh"

evidence="$PROJECT_ROOT/artifacts/preflight"
mkdir -p "$evidence"

run_capture() {
  output="$1"
  shift
  if "$@" > "$output" 2>&1; then
    return 0
  fi
  printf 'COMMAND_FAILED exit=%s\n' "$?" >> "$output"
  return 1
}

version_ge() {
  [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}

version_lt() {
  [[ "$1" != "$2" ]] && [[ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" == "$1" ]]
}

run_capture "$evidence/uname.txt" uname -a || true
if command -v lsb_release >/dev/null 2>&1; then
  run_capture "$evidence/os-release.txt" lsb_release -a || true
else
  run_capture "$evidence/os-release.txt" cat /etc/os-release || true
fi
run_capture "$evidence/lscpu.txt" lscpu || true
run_capture "$evidence/memory.txt" free -h || true
run_capture "$evidence/disk.txt" df -hT "$PROJECT_ROOT" || true
run_capture "$evidence/disk-bytes.txt" df -B1 --output=source,fstype,size,used,avail,pcent,target "$PROJECT_ROOT" || true
run_capture "$evidence/network-links.txt" ip -br link || true
run_capture "$evidence/network-addresses.txt" ip -br address || true
if command -v ethtool >/dev/null 2>&1; then
  run_capture "$evidence/network-eno1.txt" ethtool eno1 || true
fi

run_capture "$evidence/nvidia-smi.csv" \
  nvidia-smi \
    --query-gpu=index,name,uuid,driver_version,memory.total,memory.used,compute_cap,power.limit \
    --format=csv || true
run_capture "$evidence/nvidia-smi-q.txt" nvidia-smi -q || true
run_capture "$evidence/nvidia-ctk-cdi.txt" nvidia-ctk cdi list || true
run_capture "$evidence/nvidia-container-cli.txt" nvidia-container-cli info || true
run_capture "$evidence/nvidia-packages.txt" \
  rpm -q nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools || true

run_capture "$evidence/docker-version.txt" docker version || true
run_capture "$evidence/docker-compose-version.txt" docker compose version || true
run_capture "$evidence/docker-info.txt" docker info || true
run_capture "$evidence/docker-images.txt" docker images --digests || true
run_capture "$evidence/docker-containers.txt" \
  docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || true
run_capture "$evidence/docker-disk.txt" docker system df -v || true

if command -v ngc >/dev/null 2>&1; then
  run_capture "$evidence/ngc-version.txt" ngc --version || true
else
  printf 'NOT_FOUND\n' > "$evidence/ngc-version.txt"
fi

if [[ -n "${NGC_API_KEY:-}" ]]; then
  printf 'SET\n' > "$evidence/ngc-api-key-status.txt"
else
  printf 'NOT_SET\n' > "$evidence/ngc-api-key-status.txt"
fi

for port in 3000 5432 6379 7777 9000 9001 9090 9092 9200 30081 30082; do
  if ss -ltn "sport = :$port" 2>/dev/null | tail -n +2 | grep -q .; then
    printf '%s\tIN_USE\n' "$port"
  else
    printf '%s\tFREE\n' "$port"
  fi
done > "$evidence/ports.tsv"

cuda_image="${CUDA_SMOKE_IMAGE:-nvcr.io/nvidia/cuda:12.8.1-base-ubuntu24.04}"
container_gpu_status=FAIL
if docker run --rm --gpus all "$cuda_image" nvidia-smi \
  > "$evidence/container-gpu.txt" 2>&1; then
  container_gpu_status=PASS
fi

os_id="$(. /etc/os-release && printf '%s' "$ID")"
os_version="$(. /etc/os-release && printf '%s' "$VERSION_ID")"
gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1)"
vram_mib="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n1 | tr -d ' ')"
driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1)"
cpu_count="$(getconf _NPROCESSORS_ONLN)"
memory_bytes="$(awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo | cut -d. -f1)"
filesystem_bytes="$(df -B1 --output=size "$PROJECT_ROOT" | tail -n1 | tr -d ' ')"
free_bytes="$(df -B1 --output=avail "$PROJECT_ROOT" | tail -n1 | tr -d ' ')"
docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
compose_version="$(docker compose version --short 2>/dev/null || true)"
toolkit_version="$(rpm -q --qf '%{VERSION}' nvidia-container-toolkit 2>/dev/null || true)"
ngc_version="$(ngc --version 2>/dev/null | sed -nE 's/.*[^0-9]([0-9]+\.[0-9]+\.[0-9]+).*/\1/p' | head -n1 || true)"

os_gate=FAIL
[[ "$os_id" == ubuntu && ( "$os_version" == 22.04 || "$os_version" == 24.04 ) ]] && os_gate=PASS
gpu_gate=FAIL
[[ "$gpu_name" == "NVIDIA RTX PRO 5000 Blackwell" ]] && gpu_gate=PASS
vram_gate=FAIL
[[ "${vram_mib:-0}" -ge 47000 ]] && vram_gate=PASS
cpu_gate=FAIL
[[ "$cpu_count" -ge 18 ]] && cpu_gate=PASS
memory_gate=FAIL
[[ "$memory_bytes" -ge 128000000000 ]] && memory_gate=PASS
filesystem_gate=FAIL
[[ "$filesystem_bytes" -ge 1000000000000 ]] && filesystem_gate=PASS
free_disk_gate=FAIL
[[ "$free_bytes" -ge 250000000000 ]] && free_disk_gate=PASS
docker_gate=FAIL
if [[ -n "$docker_version" ]] \
  && version_ge "$docker_version" 28.3.3 \
  && version_lt "$docker_version" 29.5.0; then
  docker_gate=PASS
fi
compose_gate=FAIL
[[ -n "$compose_version" ]] && version_ge "$compose_version" 2.39.1 && compose_gate=PASS
toolkit_gate=FAIL
[[ -n "$toolkit_version" ]] && version_ge "$toolkit_version" 1.17.8 && toolkit_gate=PASS
ngc_gate=FAIL
[[ -n "$ngc_version" ]] && version_ge "$ngc_version" 4.10.0 && ngc_gate=PASS
ngc_key_gate=FAIL
[[ -n "${NGC_API_KEY:-}" ]] && ngc_key_gate=PASS

driver_gate=FAIL
case "$driver_version" in
  580.65.06|580.105.08) driver_gate=PASS ;;
esac

result=PASS
for gate in \
  "$os_gate" "$gpu_gate" "$vram_gate" "$cpu_gate" "$memory_gate" \
  "$filesystem_gate" "$free_disk_gate" "$docker_gate" "$compose_gate" \
  "$toolkit_gate" "$ngc_gate" "$ngc_key_gate" "$driver_gate" \
  "$container_gpu_status"; do
  [[ "$gate" == PASS ]] || result=BLOCKED
done

{
  printf 'RESULT=%s\n' "$result"
  printf 'OS=%s-%s\n' "$os_id" "$os_version"
  printf 'OS_GATE=%s\n' "$os_gate"
  printf 'GPU_NAME=%s\n' "$gpu_name"
  printf 'GPU_GATE=%s\n' "$gpu_gate"
  printf 'VRAM_MIB=%s\n' "$vram_mib"
  printf 'VRAM_GATE=%s\n' "$vram_gate"
  printf 'DRIVER_VERSION=%s\n' "$driver_version"
  printf 'DRIVER_GATE=%s\n' "$driver_gate"
  printf 'CPU_COUNT=%s\n' "$cpu_count"
  printf 'CPU_GATE=%s\n' "$cpu_gate"
  printf 'MEMORY_BYTES=%s\n' "$memory_bytes"
  printf 'MEMORY_GATE=%s\n' "$memory_gate"
  printf 'FILESYSTEM_BYTES=%s\n' "$filesystem_bytes"
  printf 'FILESYSTEM_GATE=%s\n' "$filesystem_gate"
  printf 'FREE_BYTES=%s\n' "$free_bytes"
  printf 'FREE_DISK_GATE=%s\n' "$free_disk_gate"
  printf 'DOCKER_VERSION=%s\n' "$docker_version"
  printf 'DOCKER_GATE=%s\n' "$docker_gate"
  printf 'COMPOSE_VERSION=%s\n' "$compose_version"
  printf 'COMPOSE_GATE=%s\n' "$compose_gate"
  printf 'TOOLKIT_VERSION=%s\n' "$toolkit_version"
  printf 'TOOLKIT_GATE=%s\n' "$toolkit_gate"
  printf 'NGC_CLI_VERSION=%s\n' "${ngc_version:-NOT_FOUND}"
  printf 'NGC_CLI_GATE=%s\n' "$ngc_gate"
  printf 'NGC_API_KEY_GATE=%s\n' "$ngc_key_gate"
  printf 'CONTAINER_GPU_GATE=%s\n' "$container_gpu_status"
} > "$evidence/preflight-result.env"

cat "$evidence/preflight-result.env"
[[ "$result" == PASS ]]
