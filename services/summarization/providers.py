from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from contracts import parse_json_object


class ProviderError(RuntimeError):
    pass


def request_json(
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 240,
) -> Any:
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=None if payload is None else json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer not-used"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
        return json.loads(body) if body else {}
    except Exception as error:
        raise ProviderError(f"provider request failed: {type(error).__name__}") from error


class CosmosCaptionClient:
    def __init__(self, base_url: str, model: str, timeout: float = 300) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def ready(self) -> bool:
        try:
            value = request_json(self.base_url, "/health/ready", timeout=5)
            return isinstance(value, dict)
        except ProviderError:
            return False

    def caption(
        self,
        clip: Path,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        if not clip.is_file():
            raise ProviderError("selected clip is missing")
        mime = mimetypes.guess_type(str(clip))[0] or "video/mp4"
        encoded = base64.b64encode(clip.read_bytes()).decode()
        value = request_json(
            self.base_url,
            "/chat/completions",
            {
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
                "temperature": 0,
                "max_tokens": 1024,
                "media_io_kwargs": {"video": {"num_frames": 5}},
            },
            timeout=self.timeout,
        )
        try:
            content = value["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("Cosmos3 response shape is invalid") from error
        try:
            return parse_json_object(content)
        except ValueError as error:
            raise ProviderError("Cosmos3 caption is not structured JSON") from error


class NemotronClient:
    def __init__(self, base_url: str, model: str, timeout: float = 180) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def ready(self) -> bool:
        try:
            value = request_json(self.base_url, "/health/ready", timeout=5)
            return isinstance(value, dict)
        except ProviderError:
            return False

    def generate_json(self, system_prompt: str, user_value: dict[str, Any]) -> dict[str, Any]:
        value = request_json(
            self.base_url,
            "/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_value, separators=(",", ":")),
                    },
                ],
                "temperature": 0,
                "max_tokens": 768,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        try:
            content = value["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("Nemotron response shape is invalid") from error
        try:
            return parse_json_object(content)
        except ValueError as error:
            raise ProviderError("Nemotron response is not structured JSON") from error
