from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


SCHEMA_VERSION = "1.0.0"
# The operator requested a 5 GiB headroom reserve for serialized GPU work.
DEFAULT_RESERVED_MEMORY_MIB = 5 * 1024
PROFILE_MEMORY_BUDGET_MIB = {
    # These are admission budgets, not claims about NVIDIA validation. They
    # describe this project's observed, serialized workload envelope.
    "local_vlm": 32_000,
    "summarization_vlm": 32_000,
    "direct_rt_vlm": 32_000,
    "search_critic": 32_000,
    "local_llm": 22_000,
    "summarization_llm": 22_000,
    "search_llm": 22_000,
    "rt_embedding": 8_000,
    "siglip_object": 8_000,
    # The file-batch RT-CV worker is serialized with every other GPU-heavy
    # workload and uses the pinned VSS RT-CV image.
    "rtcv_file_batch": 16_000,
}
FORBIDDEN_CONTAINERS = (
    "ntc-vss-phase07-rtcv",
    "ntc-vss-phase15-rtcv-file-batch",
    "ntc-vss-retail-poc-gpu-poc-nemotron-1",
    "ntc-vss-retail-poc-gpu-poc-cosmos3-1",
    "ntc-vss-phase11-rt-vlm",
    "ntc-vss-phase12-rt-embedding",
    "ntc-vss-phase12-siglip-object",
    "ntc-vss-rt-embed",
    "ntc-vss-retail-model",
)


def running_containers() -> set[str]:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def gpu_memory() -> tuple[int, int]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    first = result.stdout.splitlines()[0]
    total, free = (int(value.strip()) for value in first.split(","))
    return total, free


def reserved_memory_mib() -> int:
    try:
        value = int(os.environ.get("VSS_GPU_RESERVED_MEMORY_MIB", str(DEFAULT_RESERVED_MEMORY_MIB)))
    except ValueError:
        value = DEFAULT_RESERVED_MEMORY_MIB
    return max(DEFAULT_RESERVED_MEMORY_MIB, value)


def profile_memory_budget_mib(profile: str, total_mib: int) -> int | None:
    """Return the reviewed fixed admission budget for a GPU profile."""
    del total_mib
    return PROFILE_MEMORY_BUDGET_MIB.get(profile)


def decision(
    containers: set[str],
    total_mib: int,
    free_mib: int,
    profile: str | None = None,
) -> tuple[bool, str]:
    conflicts = sorted(containers.intersection(FORBIDDEN_CONTAINERS))
    if conflicts:
        return False, f"conflicting GPU workload is running: {','.join(conflicts)}"
    reserved = reserved_memory_mib()
    if total_mib <= 0:
        return False, "GPU memory telemetry is invalid"
    if free_mib / total_mib < 0.15:
        return False, (
            f"GPU free-memory headroom is below 15 percent and the required "
            f"reserve ({reserved} MiB)"
        )
    if free_mib < reserved:
        return False, f"GPU free-memory headroom is below required reserve ({reserved} MiB)"
    if profile is not None:
        budget = profile_memory_budget_mib(profile, total_mib)
        if budget is None:
            return False, f"GPU profile has no approved memory budget: {profile}"
        if free_mib - budget < reserved:
            return False, (
                f"GPU profile {profile} would breach the {reserved} MiB reserve "
                f"(free={free_mib} MiB, budget={budget} MiB)"
            )
    return True, "single-GPU serialized workload lease granted"


def grant(path: Path, profile: str = "local_vlm") -> int:
    containers = running_containers()
    total, free = gpu_memory()
    allowed, reason = decision(containers, total, free, profile=profile)
    result = {
        "schema_version": SCHEMA_VERSION,
        "profile": profile,
        "status": "granted" if allowed else "denied",
        "issued_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "gpu_free_mib": free,
        "gpu_total_mib": total,
        "reason": reason,
    }
    if allowed:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    print(json.dumps(result, separators=(",", ":")))
    return 0 if allowed else 2


def check(profile: str) -> int:
    containers = running_containers()
    total, free = gpu_memory()
    allowed, reason = decision(containers, total, free, profile=profile)
    result = {
        "schema_version": SCHEMA_VERSION,
        "profile": profile,
        "status": "admissible" if allowed else "blocked",
        "gpu_free_mib": free,
        "gpu_total_mib": total,
        "reserved_memory_mib": reserved_memory_mib(),
        "profile_memory_budget_mib": profile_memory_budget_mib(profile, total),
        "reason": reason,
    }
    print(json.dumps(result, separators=(",", ":")))
    return 0 if allowed else 2


def verify_reserve() -> int:
    total, free = gpu_memory()
    reserved = reserved_memory_mib()
    allowed = total > 0 and free >= reserved
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "admissible" if allowed else "blocked",
        "gpu_free_mib": free,
        "gpu_total_mib": total,
        "reserved_memory_mib": reserved,
        "reason": (
            "GPU reserve is satisfied"
            if allowed
            else f"GPU free-memory headroom is below required reserve ({reserved} MiB)"
        ),
    }
    print(json.dumps(result, separators=(",", ":")))
    return 0 if allowed else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("grant", "check", "verify-reserve", "status", "revoke"))
    parser.add_argument("--lease", type=Path)
    parser.add_argument(
        "--profile",
        choices=(
            "local_vlm",
            "local_llm",
            "direct_rt_vlm",
            "rt_embedding",
            "siglip_object",
            "search_llm",
            "search_critic",
            "summarization_vlm",
            "summarization_llm",
            "rtcv_file_batch",
        ),
        default="local_vlm",
    )
    args = parser.parse_args()
    if args.action in {"grant", "status", "revoke"} and args.lease is None:
        parser.error(f"--lease is required for {args.action}")
    if args.action == "grant":
        return grant(args.lease, args.profile)
    if args.action == "check":
        return check(args.profile)
    if args.action == "verify-reserve":
        return verify_reserve()
    if args.action == "revoke":
        args.lease.unlink(missing_ok=True)
        print('{"schema_version":"1.0.0","status":"revoked"}')
        return 0
    if not args.lease.exists():
        print('{"schema_version":"1.0.0","status":"absent"}')
        return 1
    print(args.lease.read_text(encoding="utf-8").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
