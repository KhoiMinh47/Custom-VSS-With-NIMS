from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "1.0.0"
ANALYTICS_MODEL_ID = "ntc-retail-traffic-rules"
ANALYTICS_MODEL_VERSION = "1.0.0"


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include UTC timezone")
    return parsed.astimezone(UTC)


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            boundary = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < boundary:
                inside = not inside
        previous = current
    return inside


def line_side(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (
        end[1] - start[1]
    ) * (point[0] - start[0])


def validate_config(config: dict[str, Any]) -> None:
    required = ("schema_version", "store_id", "camera_id", "config_version")
    if any(not config.get(name) for name in required):
        raise ValueError("analytics config is missing stable identity fields")
    if config["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported analytics schema version")
    if config.get("coordinate_space") != "normalized":
        raise ValueError("Phase 09 requires normalized coordinates")
    if int(config["config_version"]) < 1:
        raise ValueError("config_version must be positive")
    for zone in config.get("zones", []):
        polygon = zone.get("polygon", [])
        if len(polygon) < 3:
            raise ValueError("each zone needs at least three points")
        for point in polygon:
            if len(point) != 2 or any(float(value) < 0 or float(value) > 1 for value in point):
                raise ValueError("zone coordinates must be normalized")
    line = config.get("people_counting", {}).get("line", {})
    for name in ("start", "end"):
        point = line.get(name, [])
        if len(point) != 2 or any(float(value) < 0 or float(value) > 1 for value in point):
            raise ValueError("counting line coordinates must be normalized")


def event_document(
    config: dict[str, Any],
    frame: dict[str, Any],
    event_type: str,
    timestamp: datetime,
    *,
    track_ids: list[str] | None = None,
    rule_id: str,
    payload: dict[str, Any] | None = None,
    candidate: bool = False,
) -> dict[str, Any]:
    frame_id = str(frame.get("payload", {}).get("frame_id", "unknown"))
    tracks = sorted(track_ids or [])
    identity = "|".join(
        (
            str(config["store_id"]),
            str(config["camera_id"]),
            event_type,
            rule_id,
            frame_id,
            ",".join(tracks),
            str(config["config_version"]),
        )
    )
    event_id = hashlib.sha256(identity.encode()).hexdigest()
    source_correlation = str(frame.get("correlation_id", ""))
    return {
        "@timestamp": utc_text(timestamp),
        "schema_version": SCHEMA_VERSION,
        "store_id": config["store_id"],
        "camera_id": config["camera_id"],
        "correlation_id": event_id,
        "event_id": event_id,
        "event_type": event_type,
        "model_id": ANALYTICS_MODEL_ID,
        "model_version": ANALYTICS_MODEL_VERSION,
        "source_model_id": frame.get("model_id"),
        "source_model_version": frame.get("model_version"),
        "config_version": int(config["config_version"]),
        "start_time": utc_text(timestamp),
        "end_time": utc_text(timestamp),
        "confidence": 1.0,
        "candidate": candidate,
        "evaluation": bool(frame.get("payload", {}).get("evaluation", False)),
        "evaluation_run_id": str(
            frame.get("payload", {}).get("evaluation_run_id", "")
        ),
        "evidence": {
            "kind": "rt_cv_metadata",
            "frame_id": frame_id,
            "source_correlation_id": source_correlation,
            "track_ids": tracks,
            "reference": (
                f'rtcv://{config["store_id"]}/{config["camera_id"]}/{frame_id}'
            ),
        },
        "payload": payload or {},
    }
