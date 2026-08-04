from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    pass


def parse_json_object(content: Any) -> dict[str, Any]:
    if not isinstance(content, str):
        raise ProviderError("provider response content is not text")
    text = content.strip()
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1].strip()
    decoder = json.JSONDecoder()
    for offset, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ProviderError("provider response does not contain a JSON object")


def json_request(
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 30,
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


class SigLIPClient:
    def __init__(self, base_url: str, timeout: float = 120) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def text(self, text: str) -> list[float]:
        value = json_request(
            self.base_url,
            "/api/v1/generate_text_embeddings",
            {"text_input": text, "model": ""},
            timeout=self.timeout,
        )
        item = value["data"][0]
        if isinstance(item, list):
            return list(item)
        return list(item.get("embedding", item.get("embeddings")))

    def image(self, image_path: str, bbox_pixels: dict[str, int] | None = None) -> list[float]:
        payload: dict[str, Any] = {"image_path": image_path, "model": ""}
        if bbox_pixels is not None:
            payload["bbox"] = bbox_pixels
        value = json_request(
            self.base_url,
            "/api/v1/generate_image_embeddings",
            payload,
            timeout=self.timeout,
        )
        item = value["data"][0]
        if isinstance(item, list):
            return list(item)
        return list(item.get("embedding", item.get("embeddings")))


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout: float = 90) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def decompose(self, query: str) -> dict[str, Any]:
        value = json_request(
            self.base_url,
            "/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Return JSON only. Keys: route (action|attribute|fusion), "
                            "action_query, attribute_query, camera_ids. Use fusion when "
                            "both motion/action and visual object attributes matter."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "temperature": 0,
                "max_tokens": 256,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        content = value["choices"][0]["message"]["content"]
        parsed = parse_json_object(content)
        if parsed.get("route") not in {"action", "attribute", "fusion"}:
            raise ProviderError("LLM returned an invalid search route")
        parsed["source"] = "nemotron"
        return parsed


class CriticClient:
    def __init__(self, base_url: str, model: str, timeout: float = 240) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def evaluate(self, query: str, clip: Path) -> dict[str, Any]:
        if not clip.is_file():
            raise ProviderError("selected critic clip is missing")
        mime = mimetypes.guess_type(str(clip))[0] or "video/mp4"
        encoded = base64.b64encode(clip.read_bytes()).decode()
        value = json_request(
            self.base_url,
            "/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Judge whether the video is relevant to the search query. "
                            "Return JSON only with verdict relevant|not_relevant|uncertain, "
                            "confidence from 0 to 1, and a short reason."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{encoded}"}},
                            {"type": "text", "text": query},
                        ],
                    },
                ],
                "temperature": 0,
                "max_tokens": 256,
                "media_io_kwargs": {"video": {"num_frames": 5}},
            },
            timeout=self.timeout,
        )
        return parse_json_object(value["choices"][0]["message"]["content"])
