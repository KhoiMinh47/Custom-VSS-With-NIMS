from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime
from typing import Any


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
OBJECT_MODEL_ID = "siglip2-so400m-patch16-256"
OBJECT_MODEL_VERSION = "v1.1"
OBJECT_DIMENSION = 1152


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def validate_vector(vector: Any, dimension: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimension:
        raise ValueError(f"embedding must contain exactly {dimension} values")
    values = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding contains a non-finite value")
    return values


def generation_id(model_id: str, model_version: str, dimension: int) -> str:
    raw = f"{model_id}\n{model_version}\n{dimension}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def object_embedding_id(
    asset_id: str, object_id: str, frame_time: str, generation: str
) -> str:
    raw = f"{asset_id}\n{object_id}\n{frame_time}\n{generation}".encode()
    return hashlib.sha256(raw).hexdigest()


def normalized_bbox(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("bbox must be [x,y,width,height]")
    result = [float(item) for item in value]
    x, y, width, height = result
    if any(not math.isfinite(item) for item in result):
        raise ValueError("bbox contains a non-finite value")
    if min(x, y, width, height) < 0 or x + width > 1 or y + height > 1:
        raise ValueError("bbox must use normalized coordinates")
    return result


def build_object_document(
    *,
    asset_id: str,
    asset_uri: str,
    camera_id: str,
    frame_time: str,
    object_id: str,
    track_id: str,
    object_class: str,
    bbox: list[float],
    vector: list[float],
) -> dict[str, Any]:
    generation = generation_id(OBJECT_MODEL_ID, OBJECT_MODEL_VERSION, OBJECT_DIMENSION)
    return {
        "@timestamp": frame_time,
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "model_id": OBJECT_MODEL_ID,
        "model_version": OBJECT_MODEL_VERSION,
        "embedding_generation": generation,
        "object_embedding_id": object_embedding_id(
            asset_id, object_id, frame_time, generation
        ),
        "asset_id": asset_id,
        "asset_uri": asset_uri,
        "source_type": "selected_snapshot",
        "frame_time": frame_time,
        "object_id": object_id,
        "track_id": str(track_id),
        "object_class": object_class,
        "bbox": normalized_bbox(bbox),
        "model_dimension": OBJECT_DIMENSION,
        "embedding": validate_vector(vector, OBJECT_DIMENSION),
        "evidence": {
            "media_plane": "selected_snapshot",
            "raw_storage_consumed": False,
        },
    }


ATTRIBUTE_WORDS = {
    "red",
    "blue",
    "green",
    "black",
    "white",
    "yellow",
    "shirt",
    "jacket",
    "backpack",
    "bag",
    "hat",
    "person",
    "forklift",
    "pallet",
}
ACTION_WORDS = {
    "entering",
    "leaving",
    "walking",
    "running",
    "waiting",
    "crossing",
    "carrying",
    "standing",
    "queueing",
}


def fallback_decomposition(query: str) -> dict[str, Any]:
    words = set(re.findall(r"[a-z0-9_-]+", query.lower()))
    has_attribute = bool(words.intersection(ATTRIBUTE_WORDS))
    has_action = bool(words.intersection(ACTION_WORDS))
    if has_attribute and has_action:
        route = "fusion"
    elif has_attribute:
        route = "attribute"
    else:
        route = "action"
    return {
        "route": route,
        "action_query": query if route in {"action", "fusion"} else "",
        "attribute_query": query if route in {"attribute", "fusion"} else "",
        "camera_ids": [],
        "source": "deterministic_fallback",
    }


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]], *, rank_constant: int = 60
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for items in ranked_lists:
        for rank, item in enumerate(items, start=1):
            key = str(item.get("asset_id") or item.get("id"))
            target = merged.setdefault(key, {**item, "fusion_score": 0.0, "channels": []})
            target["fusion_score"] += 1.0 / (rank_constant + rank)
            channel = str(item.get("search_channel", "unknown"))
            if channel not in target["channels"]:
                target["channels"].append(channel)
    return sorted(
        merged.values(),
        key=lambda value: (-float(value["fusion_score"]), str(value.get("asset_id", ""))),
    )


def precision_at_k(result_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    sample = result_ids[:k]
    return sum(item in relevant_ids for item in sample) / k


def ndcg_at_k(result_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    dcg = sum(
        (1.0 if item in relevant_ids else 0.0) / math.log2(rank + 1)
        for rank, item in enumerate(result_ids[:k], start=1)
    )
    ideal_count = min(len(relevant_ids), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return 0.0 if ideal == 0 else dcg / ideal
