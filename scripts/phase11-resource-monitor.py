#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CONTAINERS = (
    "ntc-vss-phase11-rt-vlm",
    "ntc-vss-retail-poc-gpu-poc-cosmos3-1",
    "ntc-vss-phase11-rt-vlm-results",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def command(args: list[str], timeout: float = 3) -> str:
    try:
        result = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def cpu_ticks() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
    values = [int(value) for value in fields]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_percent(previous: tuple[int, int], current: tuple[int, int]) -> float:
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100 * (total_delta - idle_delta) / total_delta)), 1)


def memory_stats() -> dict[str, float]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.strip().split()[0])
    total = values["MemTotal"] / 1024
    available = values["MemAvailable"] / 1024
    used = total - available
    return {
        "used_mib": round(used, 1),
        "total_mib": round(total, 1),
        "utilization_percent": round(100 * used / total, 1),
    }


def gpu_stats() -> dict[str, Any]:
    output = command(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return {"available": False}
    try:
        fields = [field.strip() for field in output.splitlines()[0].split(",")]
        return {
            "available": True,
            "utilization_percent": float(fields[0]),
            "memory_used_mib": float(fields[1]),
            "memory_total_mib": float(fields[2]),
            "memory_utilization_percent": round(100 * float(fields[1]) / float(fields[2]), 1),
            "power_watts": float(fields[3]),
            "temperature_celsius": float(fields[4]),
        }
    except (ValueError, IndexError, ZeroDivisionError):
        return {"available": False}


def size_mib(value: str) -> float:
    number_text = "".join(character for character in value if character.isdigit() or character == ".")
    unit = value[len(number_text) :].strip()
    number = float(number_text or 0)
    factors = {
        "B": 1 / (1024 * 1024),
        "kB": 1 / 1024,
        "KB": 1 / 1024,
        "KiB": 1 / 1024,
        "MB": 1,
        "MiB": 1,
        "GB": 1024,
        "GiB": 1024,
    }
    return round(number * factors.get(unit, 1), 1)


def container_stats() -> dict[str, dict[str, Any]]:
    running = set(
        command(["docker", "ps", "--format", "{{.Names}}"], timeout=5).splitlines()
    )
    result: dict[str, dict[str, Any]] = {
        name: {"running": name in running} for name in CONTAINERS
    }
    selected = [name for name in CONTAINERS if name in running]
    if not selected:
        return result
    output = command(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", *selected],
        timeout=8,
    )
    samples: dict[str, dict[str, Any]] = {}
    for line in output.splitlines():
        try:
            value = json.loads(line)
            samples[str(value.get("Name", ""))] = value
        except json.JSONDecodeError:
            continue
    for name in CONTAINERS:
        if name not in running:
            continue
        try:
            value = samples[name]
            memory_usage = str(value.get("MemUsage", "0 / 0")).split("/", 1)
            result[name] = {
                "running": True,
                "cpu_percent": float(str(value.get("CPUPerc", "0")).rstrip("%")),
                "memory_used_mib": size_mib(memory_usage[0].strip()),
                "memory_limit_mib": size_mib(memory_usage[1].strip()),
                "memory_percent": float(str(value.get("MemPerc", "0")).rstrip("%")),
            }
        except (KeyError, ValueError, IndexError):
            result[name] = {"running": True, "metrics_available": False}
    return result


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(value, handle, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.chmod(0o644)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pid-file", required=True, type=Path)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    args.pid_file.parent.mkdir(parents=True, exist_ok=True)
    args.pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
    args.pid_file.chmod(0o644)

    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    previous = cpu_ticks()
    try:
        while running:
            time.sleep(max(0.5, args.interval))
            current = cpu_ticks()
            containers = container_stats()
            direct = containers["ntc-vss-phase11-rt-vlm"]["running"]
            cosmos = containers["ntc-vss-retail-poc-gpu-poc-cosmos3-1"]["running"]
            write_atomic(
                args.output,
                {
                    "schema_version": "1.0.0",
                    "timestamp": utc_now(),
                    "mode": "direct_rt_vlm" if direct and cosmos else "collector_only",
                    "host": {
                        "cpu_utilization_percent": cpu_percent(previous, current),
                        "memory": memory_stats(),
                    },
                    "gpu": gpu_stats(),
                    "containers": containers,
                },
            )
            previous = current
    finally:
        try:
            if args.pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                args.pid_file.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
