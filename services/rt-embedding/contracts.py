from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
VIDEO_MODEL_ID = "cosmos-embed1-448p-anomaly-detection"
VIDEO_MODEL_VERSION = "1.0"
VIDEO_DIMENSION = 768
CHUNK_SECONDS = 10


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def validate_vector(vector: Any, dimension: int = VIDEO_DIMENSION) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimension:
        raise ValueError(f"embedding must contain exactly {dimension} values")
    values = [float(value) for value in vector]
    if not all(value == value and abs(value) != float("inf") for value in values):
        raise ValueError("embedding contains a non-finite value")
    return values


def selected_clip_path(root: Path, asset_uri: str) -> Path:
    prefix = "selected-clip://"
    if not asset_uri.startswith(prefix):
        raise ValueError("only selected-clip:// media is accepted")
    name = asset_uri.removeprefix(prefix)
    if not name or name != Path(name).name or not name.endswith(".mp4"):
        raise ValueError("invalid selected clip URI")
    candidate = (root / name).resolve()
    if candidate.parent != root.resolve():
        raise ValueError("selected clip escaped its allowed directory")
    if not candidate.is_file():
        raise ValueError("selected clip is missing")
    return candidate


def file_uri(path: Path, container_root: Path = Path("/selected-clips")) -> str:
    return f"file://{container_root / path.name}"


def generation_id(model_id: str, model_version: str, dimension: int) -> str:
    value = f"{model_id}\n{model_version}\n{dimension}".encode()
    return hashlib.sha256(value).hexdigest()[:16]


def embedding_id(asset_id: str, chunk_index: int, generation: str) -> str:
    value = f"{asset_id}\n{chunk_index}\n{generation}".encode()
    return hashlib.sha256(value).hexdigest()


def chunk_timestamp(creation_time: str, offset_seconds: float) -> str:
    base = datetime.fromisoformat(creation_time.replace("Z", "+00:00"))
    if base.tzinfo is None:
        raise ValueError("creation_time must include a timezone")
    return (base.astimezone(UTC) + timedelta(seconds=offset_seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def build_video_document(
    *,
    asset_id: str,
    asset_uri: str,
    camera_id: str,
    creation_time: str,
    chunk_index: int,
    start_offset_seconds: float,
    end_offset_seconds: float,
    vector: list[float],
    frame_count: int,
    clip_sha256: str,
) -> dict[str, Any]:
    checked = validate_vector(vector)
    generation = generation_id(VIDEO_MODEL_ID, VIDEO_MODEL_VERSION, VIDEO_DIMENSION)
    start_time = chunk_timestamp(creation_time, start_offset_seconds)
    end_time = chunk_timestamp(creation_time, end_offset_seconds)
    return {
        "@timestamp": start_time,
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "model_id": VIDEO_MODEL_ID,
        "model_version": VIDEO_MODEL_VERSION,
        "embedding_generation": generation,
        "embedding_id": embedding_id(asset_id, chunk_index, generation),
        "asset_id": asset_id,
        "asset_uri": asset_uri,
        "source_type": "selected_clip",
        "chunk_index": chunk_index,
        "chunk_seconds": CHUNK_SECONDS,
        "start_time": start_time,
        "end_time": end_time,
        "frame_count": int(frame_count),
        "clip_sha256": clip_sha256,
        "model_dimension": VIDEO_DIMENSION,
        "embedding": checked,
        "evidence": {
            "media_plane": "selected_prepared_clip",
            "raw_storage_consumed": False,
        },
    }
