#!/usr/bin/env python3
"""Create the Phase 07 performance and frame-continuity evidence summary."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def stream_stat(record: dict[str, Any]) -> dict[str, Any]:
    for value in record.get("vendor_metrics", {}).get("stream-stats", []):
        if value.get("sensor_id") == "cam-01":
            return value
    raise ValueError("cam-01 is missing from a vendor metrics sample")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("samples", type=Path)
    parser.add_argument("basic_summary", type=Path)
    parser.add_argument("rtcv_log", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    records = [
        json.loads(line)
        for line in args.samples.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(records) < 2:
        raise SystemExit("ERROR: at least two successful soak samples are required")
    basic = json.loads(args.basic_summary.read_text(encoding="utf-8"))
    stats = [stream_stat(record) for record in records]
    fps = [float(item["fps"]) for item in stats]
    latency = [float(item["latency_ms"]) for item in stats]
    frame_numbers = [int(item["frame_number"]) for item in stats]
    frame_deltas = [
        current - previous
        for previous, current in zip(frame_numbers, frame_numbers[1:])
    ]
    elapsed = (
        parse_timestamp(records[-1]["timestamp"])
        - parse_timestamp(records[0]["timestamp"])
    ).total_seconds()
    log_text = args.rtcv_log.read_text(encoding="utf-8", errors="replace")
    drop_signals = re.findall(
        r"(?i)\b(?:dropped?\s+frames?|frames?\s+(?:were\s+)?dropped?)\b",
        log_text,
    )
    stream_errors = re.findall(
        r"(?i)(?:internal data stream error|streaming stopped, reason error)",
        log_text,
    )
    oom_signals = re.findall(
        r"(?i)(?:out of memory|oomkilled|cuda_error_out_of_memory)",
        log_text,
    )
    decode_signals = re.findall(
        r"(?i)(?:decode(?:r)? error|failed to decode)",
        log_text,
    )

    result = {
        **basic,
        "result": "PASS",
        "successful_samples": len(records),
        "vendor_reported_fps": {
            "minimum": round(min(fps), 3),
            "average": round(statistics.fmean(fps), 3),
            "p95": round(percentile(fps, 0.95), 3),
            "maximum": round(max(fps), 3),
        },
        "vendor_reported_latency_ms": {
            "minimum": round(min(latency), 3),
            "average": round(statistics.fmean(latency), 3),
            "p95": round(percentile(latency, 0.95), 3),
            "maximum": round(max(latency), 3),
        },
        "frame_continuity": {
            "first_frame_number": frame_numbers[0],
            "last_frame_number": frame_numbers[-1],
            "frame_number_delta": frame_numbers[-1] - frame_numbers[0],
            "observed_counter_rate_fps": round(
                (frame_numbers[-1] - frame_numbers[0]) / elapsed, 3
            ),
            "counter_resets": sum(delta < 0 for delta in frame_deltas),
            "non_advancing_samples": sum(delta == 0 for delta in frame_deltas),
            "runtime_drop_warning_count": len(drop_signals),
            "runtime_stream_error_count": len(stream_errors),
            "metadata_decode_error_delta": basic["decode_errors_delta"],
            "measurement_note": (
                "The VSS metrics API exposes frame_number, FPS, and latency but "
                "not an absolute input-drop counter. The gate therefore records "
                "counter continuity plus explicit runtime drop/decode signals. "
                "Metadata messages are object-driven with dummy-payload disabled, "
                "so detection-silent intervals are not classified as frame drops."
            ),
        },
        "runtime_oom_signal_count": len(oom_signals),
        "runtime_decode_signal_count": len(decode_signals),
    }
    failures = [
        basic.get("result") != "PASS",
        int(basic.get("duration_seconds", 0)) < 7200,
        result["frame_continuity"]["counter_resets"] != 0,
        result["frame_continuity"]["non_advancing_samples"] != 0,
        result["frame_continuity"]["runtime_drop_warning_count"] != 0,
        result["frame_continuity"]["runtime_stream_error_count"] != 0,
        int(basic.get("decode_errors_delta", 0)) != 0,
        int(basic.get("elasticsearch_errors_delta", 0)) != 0,
        int(basic.get("publish_errors_delta", 0)) != 0,
        len(oom_signals) != 0,
    ]
    if any(failures):
        result["result"] = "PARTIAL"
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["result"] != "PASS":
        raise SystemExit("ERROR: RT-CV soak performance analysis did not pass")


if __name__ == "__main__":
    main()
