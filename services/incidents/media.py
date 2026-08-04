from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from contracts import parse_utc


class MediaSelectionError(RuntimeError):
    pass


class MediaPreparationError(RuntimeError):
    pass


class MediaPreparer:
    def __init__(self, base_url: str, timeout_seconds: float = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def prepare(self, clip: Path) -> tuple[str, int]:
        request = Request(
            f"{self.base_url}/api/v1/prepare",
            data=json.dumps({"filename": clip.name}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                value = json.load(response)
            if value.get("status") != "prepared":
                raise MediaPreparationError("media preparation did not complete")
            return str(value["clip_sha256"]), int(value["clip_bytes"])
        except Exception as error:
            raise MediaPreparationError(
                f"selected-clip preparation failed: {type(error).__name__}"
            ) from error


class ViosClipSelector:
    def __init__(
        self,
        base_url: str,
        destination: Path,
        *,
        timeout_seconds: float = 60,
        attempts: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.destination = destination
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts

    def _json(self, path: str) -> Any:
        with urlopen(f"{self.base_url}{path}", timeout=self.timeout_seconds) as response:
            return json.load(response)

    @staticmethod
    def _flatten_streams(value: Any) -> list[dict[str, Any]]:
        wrappers = value if isinstance(value, list) else value.get("streams", [])
        result: list[dict[str, Any]] = []
        for wrapper in wrappers:
            if not isinstance(wrapper, dict):
                continue
            if any(key in wrapper for key in ("streamId", "id", "uuid")):
                result.append(wrapper)
            else:
                for nested in wrapper.values():
                    if isinstance(nested, list):
                        result.extend(item for item in nested if isinstance(item, dict))
        return result

    def stream_id(self, camera_id: str) -> str:
        streams = self._flatten_streams(self._json("/api/v1/sensor/streams"))
        matching = [item for item in streams if str(item.get("name")) == camera_id]
        if len(matching) != 1:
            raise MediaSelectionError(
                f"expected one VIOS stream for camera_id={camera_id}, got {len(matching)}"
            )
        value = matching[0].get("streamId") or matching[0].get("id") or matching[0].get("uuid")
        if not value:
            raise MediaSelectionError("VIOS stream is missing a stable stream ID")
        return str(value)

    def _timeline_covers(self, stream_id: str, start: str, end: str) -> bool:
        target_start, target_end = parse_utc(start), parse_utc(end)
        timelines = self._json(f"/api/v1/storage/{stream_id}/timelines")
        return any(
            parse_utc(item["startTime"]) <= target_start
            and parse_utc(item["endTime"]) >= target_end
            for item in timelines
            if isinstance(item, dict) and "startTime" in item and "endTime" in item
        )

    def select(self, incident: dict[str, Any]) -> tuple[Path, str, int]:
        stream_id = self.stream_id(str(incident["camera_id"]))
        start, end = str(incident["clip_start_time"]), str(incident["clip_end_time"])
        self.destination.mkdir(parents=True, exist_ok=True)
        target = self.destination / f'{incident["incident_id"]}.mp4'
        if target.exists() and target.stat().st_size > 32 and b"ftyp" in target.read_bytes()[:32]:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            return target, digest, target.stat().st_size

        query = urlencode(
            {
                "startTime": start,
                "endTime": end,
                "container": "mp4",
                "transcode": "none",
            }
        )
        error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                if not self._timeline_covers(stream_id, start, end):
                    raise MediaSelectionError("VIOS recording has not reached the post-roll boundary")
                with urlopen(
                    f"{self.base_url}/api/v1/storage/file/{stream_id}?{query}",
                    timeout=self.timeout_seconds,
                ) as response:
                    payload = response.read()
                if len(payload) <= 32 or b"ftyp" not in payload[:32]:
                    raise MediaSelectionError("VIOS clip response is not MP4")
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(payload)
                temporary.replace(target)
                return target, hashlib.sha256(payload).hexdigest(), len(payload)
            except Exception as caught:
                error = caught
                if attempt + 1 < self.attempts:
                    time.sleep(min(2**attempt, 8))
        raise MediaSelectionError(
            f"VIOS selected-clip request failed after {self.attempts} attempts: "
            f"{type(error).__name__}"
        )
