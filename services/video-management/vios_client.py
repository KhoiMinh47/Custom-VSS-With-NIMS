from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ViosError(RuntimeError):
    pass


@dataclass(frozen=True)
class ViosClient:
    base_url: str
    timeout_seconds: float = 15
    attempts: int = 4

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> tuple[bytes, str]:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Accept": accept}
        if body is not None:
            headers["Content-Type"] = "application/json"
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            request = Request(f"{self.base_url.rstrip('/')}{path}", body, headers, method=method)
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return response.read(), response.headers.get("Content-Type", "")
            except (HTTPError, URLError, TimeoutError) as error:
                last_error = error
                if attempt + 1 < self.attempts:
                    time.sleep(min(2**attempt, 8))
        raise ViosError(f"{method} {path} failed after {self.attempts} attempts: {last_error}")

    def json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body, _ = self.request(method, path, payload)
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise ViosError(f"{method} {path} returned invalid JSON") from error

    def streams(self) -> list[dict[str, Any]]:
        result = self.json("GET", "/api/v1/sensor/streams")
        wrappers = result if isinstance(result, list) else result.get("streams", [])
        flattened: list[dict[str, Any]] = []
        for wrapper in wrappers:
            if not isinstance(wrapper, dict):
                continue
            if any(key in wrapper for key in ("streamId", "id", "uuid")):
                flattened.append(wrapper)
                continue
            for value in wrapper.values():
                if isinstance(value, list):
                    flattened.extend(item for item in value if isinstance(item, dict))
        return flattened

    def statuses(self) -> Any:
        return self.json("GET", "/api/v1/sensor/status")

    def proxy_streams(self) -> list[dict[str, Any]]:
        result = self.json("GET", "/api/v1/proxy/streams")
        return result if isinstance(result, list) else result.get("streams", [])

    def add_sensor(self, camera_id: str, name: str, uri: str) -> Any:
        return self.json(
            "POST",
            "/api/v1/sensor/add",
            {
                "name": camera_id,
                "location": name,
                "sensorUrl": uri,
                "username": "",
                "password": "",
                "verifyRtsp": True,
            },
        )

    def add_proxy(
        self,
        stream_id: str,
        name: str,
        uri: str,
        codec: str,
        resolution: str,
        framerate: str,
    ) -> Any:
        return self.json(
            "POST",
            "/api/v1/proxy/stream/add",
            {
                "id": stream_id,
                "name": name,
                "url": uri,
                "codec": codec,
                "resolution": resolution,
                "framerate": framerate,
            },
        )

    def delete_proxy(self, stream_id: str) -> None:
        self.request("DELETE", f"/api/v1/proxy/stream/{stream_id}")

    def delete_sensor(self, sensor_id: str) -> None:
        self.request("DELETE", f"/api/v1/sensor/{sensor_id}")
