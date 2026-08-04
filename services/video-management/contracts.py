from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CAMERA_ID_RE = re.compile(r"^cam-\d{2}$")
SECRET_REF_RE = re.compile(r"^camera://[a-zA-Z0-9._/-]+$")


class ContractError(ValueError):
    pass


def load_registry(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        registry = json.load(handle)
    validate_registry(registry)
    return registry


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("schema_version") != "1.0.0":
        raise ContractError("schema_version must be 1.0.0")
    store = registry.get("store", {})
    if not store.get("store_id"):
        raise ContractError("store_id is required")
    if store.get("backend_timestamps") != "UTC":
        raise ContractError("backend timestamps must be UTC")
    cameras = registry.get("cameras")
    if not isinstance(cameras, list) or not 1 <= len(cameras) <= 10:
        raise ContractError("camera count must be between 1 and 10")
    ids: set[str] = set()
    refs: set[str] = set()
    for camera in cameras:
        camera_id = camera.get("camera_id", "")
        if not CAMERA_ID_RE.fullmatch(camera_id):
            raise ContractError(f"invalid stable camera_id: {camera_id!r}")
        if camera_id in ids:
            raise ContractError(f"duplicate camera_id: {camera_id}")
        ids.add(camera_id)
        for stream_name in ("main_stream", "ai_substream"):
            stream = camera.get(stream_name)
            if not isinstance(stream, dict):
                raise ContractError(f"{camera_id}.{stream_name} is required")
            ref = stream.get("uri_secret_ref", "")
            if not SECRET_REF_RE.fullmatch(ref):
                raise ContractError(f"{camera_id}.{stream_name} must use camera:// secret ref")
            if ref in refs:
                raise ContractError(f"duplicate secret ref: {ref}")
            refs.add(ref)
            if any(key in stream for key in ("uri", "url", "username", "password")):
                raise ContractError(f"{camera_id}.{stream_name} contains plaintext connection data")
    reconnect = registry.get("reconnect", {})
    if reconnect.get("initial_delay_seconds", 0) <= 0:
        raise ContractError("reconnect initial delay must be positive")
    if reconnect.get("max_delay_seconds", 0) < reconnect["initial_delay_seconds"]:
        raise ContractError("reconnect max delay must be >= initial delay")


def validate_resolved_uri(uri: str) -> None:
    parsed = urlsplit(uri)
    if parsed.scheme != "rtsp" or not parsed.hostname:
        raise ContractError("resolved camera URI must be RTSP")


def reconnect_delays(initial: float, maximum: float, multiplier: float, attempts: int) -> list[float]:
    if initial <= 0 or maximum < initial or multiplier < 1 or attempts < 0:
        raise ContractError("invalid reconnect policy")
    values: list[float] = []
    delay = initial
    for _ in range(attempts):
        values.append(min(delay, maximum))
        delay = min(delay * multiplier, maximum)
    return values
