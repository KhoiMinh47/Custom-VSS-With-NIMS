from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


class VLMError(RuntimeError):
    pass


class CosmosClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def ready(self) -> bool:
        try:
            with urlopen(f"{self.base_url}/health/ready", timeout=5) as response:
                return response.status == 200
        except Exception:
            return False

    def verify(self, clip: Path, system_prompt: str, user_prompt: str) -> str:
        if not clip.is_file():
            raise VLMError("selected clip is missing")
        mime = mimetypes.guess_type(str(clip))[0] or "video/mp4"
        encoded = base64.b64encode(clip.read_bytes()).decode()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            "max_tokens": 1024,
            "temperature": 0.2,
            "media_io_kwargs": {"video": {"num_frames": 8}},
            "mm_processor_kwargs": {
                "size": {"shortest_edge": 1568, "longest_edge": 345600}
            },
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer not-used"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                value = json.load(response)
            return str(value["choices"][0]["message"]["content"])
        except Exception as error:
            raise VLMError(f"Cosmos3 request failed: {type(error).__name__}") from error
