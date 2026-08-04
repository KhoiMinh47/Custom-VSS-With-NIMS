from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any


SCHEMA_VERSION = "1.0.0"
INCIDENT_MODEL_ID = "ntc-phase10-candidate-selector"
INCIDENT_MODEL_VERSION = "1.0.0"


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must include UTC timezone")
    return parsed.astimezone(UTC)


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def is_candidate(event: dict[str, Any]) -> bool:
    return bool(event.get("candidate")) and not bool(event.get("evaluation"))


def validate_behavior_event(event: dict[str, Any]) -> None:
    required = (
        "schema_version",
        "store_id",
        "camera_id",
        "event_id",
        "event_type",
        "model_id",
        "model_version",
        "start_time",
        "end_time",
        "evidence",
    )
    missing = [name for name in required if name not in event]
    if missing:
        raise ValueError(f"behavior event missing fields: {','.join(missing)}")
    if event["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported behavior schema_version")
    if not str(event["store_id"]).strip() or not str(event["camera_id"]).strip():
        raise ValueError("store_id and camera_id are required")
    parse_utc(str(event["start_time"]))
    parse_utc(str(event["end_time"]))


def build_incident(
    event: dict[str, Any],
    *,
    pre_roll_seconds: float,
    post_roll_seconds: float,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    validate_behavior_event(event)
    if not is_candidate(event):
        raise ValueError("event is not an eligible Phase 10 candidate")
    start = parse_utc(str(event["start_time"])) - timedelta(seconds=pre_roll_seconds)
    end = parse_utc(str(event["end_time"])) + timedelta(seconds=post_roll_seconds)
    if end <= start:
        raise ValueError("clip window must have positive duration")
    incident_id = hashlib.sha256(
        f'{event["store_id"]}|{event["camera_id"]}|{event["event_id"]}|phase10'.encode()
    ).hexdigest()
    now = created_at or datetime.now(UTC)
    return {
        "@timestamp": utc_text(now),
        "schema_version": SCHEMA_VERSION,
        "store_id": event["store_id"],
        "camera_id": event["camera_id"],
        "correlation_id": event.get("correlation_id", event["event_id"]),
        "event_id": event["event_id"],
        "incident_id": incident_id,
        "event_type": event["event_type"],
        "model_id": INCIDENT_MODEL_ID,
        "model_version": INCIDENT_MODEL_VERSION,
        "source_model_id": event["model_id"],
        "source_model_version": event["model_version"],
        "status": "preparing_clip",
        "verdict": "pending",
        "confidence": float(event.get("confidence", 0.0)),
        "candidate": True,
        "evaluation": False,
        "start_time": event["start_time"],
        "end_time": event["end_time"],
        "clip_start_time": utc_text(start),
        "clip_end_time": utc_text(end),
        "retry_count": 0,
        "created_at": utc_text(now),
        "updated_at": utc_text(now),
        "evidence": {
            "kind": "selected_clip_pending",
            "source_event_id": event["event_id"],
            "source_evidence": event["evidence"],
        },
        "payload": event.get("payload", {}),
    }


def mark_clip_ready(
    incident: dict[str, Any],
    *,
    asset_uri: str,
    clip_sha256: str,
    clip_bytes: int,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    result = json.loads(json.dumps(incident))
    result["status"] = "queued_for_verification"
    result["asset_uri"] = asset_uri
    result["clip_sha256"] = clip_sha256
    result["clip_bytes"] = int(clip_bytes)
    result["updated_at"] = utc_text(updated_at or datetime.now(UTC))
    result["evidence"]["kind"] = "vios_selected_clip"
    result["evidence"]["reference"] = asset_uri
    return result

