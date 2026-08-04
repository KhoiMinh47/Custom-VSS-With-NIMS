from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
CAMERA_ID = "cam-01"
MODEL_ID = "rtdetr-warehouse-2d"
MODEL_VERSION = "1.0.2"
TRACKER_ID = "nvdcf"


class ContractError(ValueError):
    pass


def derive_ai_input_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme != "rtsp" or not parsed.hostname:
        raise ContractError("camera secret must be an RTSP URI")
    path = re.sub(
        r"/Streaming/Channels/101(?=/|$)",
        "/Streaming/Channels/102",
        parsed.path,
        flags=re.IGNORECASE,
    )
    if path == parsed.path and not re.search(
        r"/Streaming/Channels/102(?=/|$)", parsed.path, re.IGNORECASE
    ):
        raise ContractError("physical camera URI does not expose the approved 101/102 roles")
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def utc_iso(seconds: int, nanos: int = 0) -> str:
    moment = datetime.fromtimestamp(seconds + nanos / 1_000_000_000, tz=UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_bbox(bbox: dict[str, Any], width: int = 1280, height: int = 720) -> dict[str, float]:
    values = {
        "left": float(bbox.get("leftX", bbox.get("left", 0.0))),
        "top": float(bbox.get("topY", bbox.get("top", 0.0))),
        "right": float(bbox.get("rightX", bbox.get("right", 0.0))),
        "bottom": float(bbox.get("bottomY", bbox.get("bottom", 0.0))),
    }
    if max(abs(value) for value in values.values()) > 2:
        values["left"] /= width
        values["right"] /= width
        values["top"] /= height
        values["bottom"] /= height
    return {key: min(1.0, max(0.0, value)) for key, value in values.items()}


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


def correlation_id(frame_id: str, timestamp: str, event_type: str = "rt_cv.frame") -> str:
    value = f"{STORE_ID}|{CAMERA_ID}|{event_type}|{frame_id}|{timestamp}"
    return hashlib.sha256(value.encode()).hexdigest()


def frame_document(
    frame: dict[str, Any],
    timestamp: str,
    objects: list[dict[str, Any]],
) -> dict[str, Any]:
    frame_id = str(frame.get("id") or correlation_id("missing", timestamp))
    confidence = max((float(item["confidence"]) for item in objects), default=0.0)
    return {
        "@timestamp": timestamp,
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "camera_id": CAMERA_ID,
        "correlation_id": correlation_id(frame_id, timestamp),
        "event_type": "rt_cv.frame",
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "start_time": timestamp,
        "end_time": timestamp,
        "confidence": confidence,
        "payload": {
            "frame_id": frame_id,
            "source_schema_version": str(frame.get("version", "")),
            "sensor_id": str(frame.get("sensorId", "")),
            "tracker_id": TRACKER_ID,
            "objects": objects,
        },
    }


def line_crossing_document(
    frame_id: str,
    timestamp: str,
    track_id: str,
    line_id: str,
    direction: str,
    bbox: dict[str, float],
) -> dict[str, Any]:
    event_type = "line_crossing.smoke"
    return {
        "@timestamp": timestamp,
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "camera_id": CAMERA_ID,
        "correlation_id": correlation_id(
            f"{frame_id}:{track_id}:{line_id}:{direction}", timestamp, event_type
        ),
        "event_type": event_type,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "start_time": timestamp,
        "end_time": timestamp,
        "confidence": 1.0,
        "payload": {
            "frame_id": frame_id,
            "track_id": track_id,
            "line_id": line_id,
            "direction": direction,
            "bbox": bbox,
            "tracker_id": TRACKER_ID,
        },
    }
