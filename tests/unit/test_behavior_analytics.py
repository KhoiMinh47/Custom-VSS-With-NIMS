from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/heatmap"))
sys.path.insert(0, str(ROOT / "services/behavior-analytics"))

from contracts import validate_config  # noqa: E402
from engine import BehaviorEngine  # noqa: E402
from heatmap import HeatmapGrid  # noqa: E402


def config() -> dict:
    return yaml.safe_load(
        (ROOT / "config/analytics/cam-01.behavior.yaml").read_text(encoding="utf-8")
    )


def frame(frame_id: str, timestamp: datetime, x: float, track_id: str = "track-1") -> dict:
    return {
        "@timestamp": timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "correlation_id": f"source-{frame_id}",
        "model_id": "rtdetr-warehouse-2d",
        "model_version": "1.0.2",
        "payload": {
            "frame_id": frame_id,
            "evaluation": True,
            "objects": [{
                "track_id": track_id,
                "type": "Person",
                "confidence": 0.9,
                "bbox": {
                    "left": x - 0.03, "right": x + 0.03,
                    "top": 0.4, "bottom": 0.8
                },
            }],
        },
    }


def test_config_uses_normalized_versioned_camera_mapping() -> None:
    value = config()
    validate_config(value)
    assert value["store_id"] == "store-001"
    assert value["camera_id"] == "cam-01"
    assert value["coordinate_space"] == "normalized"
    assert value["calibration_status"] == "provisional"
    assert value["config_version"] == 1


def test_trajectory_emits_all_phase09_use_case_events_with_evidence() -> None:
    engine = BehaviorEngine(config())
    start = datetime(2026, 7, 29, 5, 0, tzinfo=UTC)
    events = []
    for index, x in enumerate((0.2, 0.4, 0.4, 0.4, 0.75, 0.4)):
        events.extend(
            engine.process_frame(frame(f"eval-{index}", start + timedelta(seconds=index), x))
        )
    types = {event["event_type"] for event in events}
    assert {
        "roi.entry", "roi.exit", "restricted_zone.entry", "dwell.threshold",
        "line_crossing", "people_count.entry", "people_count.exit",
        "queue.threshold", "queue.cleared", "heatmap.snapshot",
    } <= types
    assert all(event["schema_version"] == "1.0.0" for event in events)
    assert all(event["store_id"] == "store-001" for event in events)
    assert all(event["camera_id"] == "cam-01" for event in events)
    assert all(event["@timestamp"].endswith("Z") for event in events)
    assert all(event["evidence"]["reference"].startswith("rtcv://") for event in events)
    assert all(event["evaluation"] is True for event in events)
    json.dumps(events)


def test_duplicate_frame_is_idempotent() -> None:
    engine = BehaviorEngine(config())
    value = frame("same-frame", datetime(2026, 7, 29, 5, 0, tzinfo=UTC), 0.4)
    assert engine.process_frame(value)
    assert engine.process_frame(value) == []
    assert engine.snapshot()["frames_processed"] == 1


def test_non_person_and_wrong_camera_are_rejected() -> None:
    engine = BehaviorEngine(config())
    value = frame("wrong-camera", datetime(2026, 7, 29, 5, 0, tzinfo=UTC), 0.4)
    value["camera_id"] = "cam-02"
    assert engine.process_frame(value) == []
    value["camera_id"] = "cam-01"
    value["payload"]["objects"][0]["type"] = "Forklift"
    assert engine.process_frame(value) == []
    assert engine.snapshot()["active_tracks"] == 0


def test_heatmap_maps_normalized_edges_and_returns_normalized_grid() -> None:
    heatmap = HeatmapGrid(2, 2)
    heatmap.add(0, 0)
    heatmap.add(1, 1)
    heatmap.add(1, 1)
    snapshot = heatmap.snapshot()
    assert snapshot["samples"] == 3
    assert snapshot["counts"] == [[1, 0], [0, 2]]
    assert snapshot["normalized"] == [[0.5, 0.0], [0.0, 1.0]]


def test_phase09_files_do_not_reference_raw_video_or_credentials() -> None:
    paths = [
        ROOT / "services/behavior-analytics",
        ROOT / "services/heatmap",
        ROOT / "config/analytics/cam-01.behavior.yaml",
        ROOT / "deploy/compose/behavior-analytics.compose.yml",
    ]
    content = ""
    for path in paths:
        files = path.rglob("*") if path.is_dir() else [path]
        for file in files:
            if file.is_file() and file.suffix in {".py", ".yaml", ".yml", ".json"}:
                content += file.read_text(encoding="utf-8")
    assert "runtime/raw-video" not in content
    assert "rtsp://" not in content
    assert "NGC_API_KEY" not in content
