from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/heatmap"))
sys.path.insert(0, str(ROOT / "services/behavior-analytics"))

from engine import BehaviorEngine  # noqa: E402

EXPECTED = {
    "roi.entry",
    "roi.exit",
    "restricted_zone.entry",
    "dwell.threshold",
    "line_crossing",
    "people_count.entry",
    "people_count.exit",
    "queue.threshold",
    "queue.cleared",
    "heatmap.snapshot",
}


def make_frame(run_id: str, index: int, timestamp: datetime, x: float) -> dict:
    frame_id = f"{run_id}-{index}"
    return {
        "@timestamp": timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "correlation_id": f"evaluation-source-{frame_id}",
        "model_id": "rtdetr-warehouse-2d",
        "model_version": "1.0.2",
        "payload": {
            "frame_id": frame_id,
            "evaluation": True,
            "evaluation_run_id": run_id,
            "objects": [{
                "track_id": f"{run_id}-track",
                "type": "Person",
                "confidence": 1.0,
                "bbox": {
                    "left": x - 0.03,
                    "right": x + 0.03,
                    "top": 0.4,
                    "bottom": 0.8,
                },
            }],
        },
    }


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts/evals/phase09"
    output.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load(
        (ROOT / "config/analytics/cam-01.behavior.yaml").read_text(encoding="utf-8")
    )
    engine = BehaviorEngine(config)
    start = datetime.now(UTC).replace(microsecond=0)
    run_id = f"phase09-eval-{int(start.timestamp())}"
    frames = [
        make_frame(run_id, index, start + timedelta(seconds=index), x)
        for index, x in enumerate((0.2, 0.4, 0.4, 0.4, 0.75, 0.4))
    ]
    events = [event for frame in frames for event in engine.process_frame(frame)]
    observed = {event["event_type"] for event in events}
    report = {
        "schema_version": "1.0.0",
        "evaluation_type": "synthetic_trajectory_ground_truth",
        "run_id": run_id,
        "camera_id": "cam-01",
        "config_version": config["config_version"],
        "calibration_status": config["calibration_status"],
        "expected_event_types": sorted(EXPECTED),
        "observed_event_types": sorted(observed),
        "missing_event_types": sorted(EXPECTED - observed),
        "functional_event_coverage": round(len(EXPECTED & observed) / len(EXPECTED), 4),
        "events_emitted": len(events),
        "limitations": [
            "Synthetic normalized trajectory validates rule logic, not real-camera accuracy.",
            "Provisional ROI/line mapping has not been business-annotated.",
            "Phase 08 scale/capacity evidence was explicitly deferred by the user.",
        ],
    }
    (output / "synthetic-frames.jsonl").write_text(
        "".join(json.dumps(frame, separators=(",", ":")) + "\n" for frame in frames),
        encoding="utf-8",
    )
    (output / "synthetic-events.jsonl").write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )
    (output / "evaluation-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f'evaluation_run={run_id} coverage={report["functional_event_coverage"]} '
        f'events={report["events_emitted"]}'
    )
    if report["missing_event_types"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
