from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

CHUNK_SECONDS = 10
VIDEO_MODEL_ID = "cosmos-embed1-448p-anomaly-detection"


class RTEmbeddingError(RuntimeError):
    pass


class RTEmbeddingClient:
    def __init__(self, base_url: str, timeout_seconds: float = 240) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        request = Request(
            f"{self.base_url}{path}",
            data=None if payload is None else json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.load(response)
        except Exception as error:
            raise RTEmbeddingError(
                f"RT-Embedding request failed: {type(error).__name__}"
            ) from error

    def ready(self) -> bool:
        try:
            return bool(self._request("/v1/ready"))
        except RTEmbeddingError:
            return False

    def text(self, text: str) -> list[float]:
        value = self._request(
            "/v1/generate_text_embeddings",
            {"text_input": [text], "model": VIDEO_MODEL_ID},
        )
        return list(value["data"][0]["embeddings"])

    def video(self, path: Path, creation_time: str) -> list[dict[str, Any]]:
        value = self._request(
            "/v1/generate_video_embeddings",
            {
                "id": str(uuid.uuid4()),
                "url": f"file:///selected-clips/{path.name}",
                "media_type": "video",
                "creation_time": creation_time,
                "model": VIDEO_MODEL_ID,
                "stream": False,
                "chunk_duration": CHUNK_SECONDS,
                "chunk_overlap_duration": 0,
            },
        )
        chunks = value.get("chunk_responses", value.get("data", []))
        if not isinstance(chunks, list) or not chunks:
            raise RTEmbeddingError("RT-Embedding returned no video chunks")
        return chunks
