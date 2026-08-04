from __future__ import annotations

import json
import math
import re
import socket
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
WORKSPACE_PREFIX = "/api/v1/workspace"
JSON_LIMIT = 2 * 1024 * 1024
BINARY_LIMIT = 64 * 1024 * 1024
THUMBNAIL_LIMIT = 5 * 1024 * 1024

# These are deployment-owned, fixed upstreams. No request field is ever used
# to select a host, port or arbitrary upstream path.
UPSTREAMS = {
    "camera-live": "http://127.0.0.1:8090",
    "vios": "http://127.0.0.1:30888/vst",
    "behavior-analytics": "http://127.0.0.1:39110",
    "alert-verification": "http://127.0.0.1:39120",
    "incidents": "http://127.0.0.1:39121",
    "direct-rt-vlm": "http://127.0.0.1:39210",
    "search": "http://127.0.0.1:39310",
    "summarization": "http://127.0.0.1:39410",
    "media-intake": "http://127.0.0.1:39420",
    "vlm-test": "http://127.0.0.1:39520",
    "nemotron": "http://127.0.0.1:30081",
}

CAMERA_ID_PATTERN = re.compile(r"cam-[0-9]{2}")
HEX_ID_PATTERN = re.compile(r"[0-9a-f]{64}")
REPORT_NAME_PATTERN = re.compile(r"([0-9a-f]{64})\.(json|md)")
SELECTED_CLIP_PATTERN = re.compile(r"selected-clip://([0-9a-f]{64})\.mp4")
UPLOADED_MEDIA_PATTERN = re.compile(r"uploaded-media://([0-9a-f]{64})\.mp4")
SELECTED_SNAPSHOT_PATTERN = re.compile(
    r"selected-snapshot://[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.(?:jpg|jpeg|png)",
    re.IGNORECASE,
)
STREAM_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,100}")
STREAM_SOURCE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}")


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _finite_json(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_json(nested) for nested in value.values())
    if isinstance(value, list):
        return all(_finite_json(nested) for nested in value)
    return True


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 64:
        raise WorkspaceError(400, "invalid_utc", "request", False, f"{field} must be UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise WorkspaceError(
            400, "invalid_utc", "request", False, f"{field} must be UTC"
        ) from error
    return parsed.astimezone(UTC)


def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise WorkspaceError(
            400, "invalid_parameter", "request", False, f"{field} is invalid"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise WorkspaceError(
            400, "invalid_parameter", "request", False, f"{field} is invalid"
        ) from error
    if parsed < minimum or parsed > maximum:
        raise WorkspaceError(
            400, "invalid_parameter", "request", False, f"{field} is out of range"
        )
    return parsed


def _bounded_float(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise WorkspaceError(
            400, "invalid_parameter", "request", False, f"{field} is invalid"
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise WorkspaceError(
            400, "invalid_parameter", "request", False, f"{field} is invalid"
        ) from error
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise WorkspaceError(
            400, "invalid_parameter", "request", False, f"{field} is out of range"
        )
    return parsed


def _one(query: dict[str, list[str]], name: str, default: str = "") -> str:
    values = query.get(name)
    if not values:
        return default
    if len(values) != 1:
        raise WorkspaceError(
            400, "invalid_parameter", "request", False, f"{name} must occur once"
        )
    return str(values[0])


def _selected_clip_id(value: Any) -> str | None:
    match = SELECTED_CLIP_PATTERN.fullmatch(str(value or ""))
    return match.group(1) if match else None


def _validate_identity(payload: dict[str, Any], operation: str) -> None:
    if (
        payload.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION
        or payload.get("store_id", STORE_ID) != STORE_ID
    ):
        raise WorkspaceError(
            400,
            "identity_mismatch",
            "request",
            False,
            f"{operation} identity fields must target store-001.",
        )


def _validate_idempotency_key(payload: dict[str, Any]) -> None:
    value = payload.get("idempotency_key")
    if value is None:
        return
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 160
        or any(
            not (character.isalnum() or character in "-_.:")
            for character in value
        )
    ):
        raise WorkspaceError(
            400,
            "invalid_idempotency_key",
            "request",
            False,
            "idempotency_key is invalid.",
        )


class WorkspaceError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        service_id: str,
        retryable: bool,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.service_id = service_id
        self.retryable = retryable
        self.message = message[:240]
        self.details = details or {}

    def public(self, request_id: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "code": self.code,
            "service_id": self.service_id,
            "retryable": self.retryable,
            "message": self.message,
            "request_id": request_id,
            **self.details,
        }


@dataclass
class BinaryResponse:
    response: Any
    content_type: str
    content_type_header: str
    content_length: int | None
    upstream_status: int
    service_id: str
    operation: str
    request_id: str
    started: float


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class FixedUpstreamClient:
    def __init__(self, logger: Callable[..., None] | None = None) -> None:
        self.logger = logger
        # Do not honor proxy environment variables and never follow an
        # upstream redirect. Both would weaken the fixed-loopback allowlist.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _log(self, event: str, **fields: Any) -> None:
        if self.logger is not None:
            self.logger(event, **fields)

    @staticmethod
    def _url(service_id: str, path: str) -> str:
        base = UPSTREAMS.get(service_id)
        if base is None:
            raise RuntimeError("unknown fixed upstream")
        if (
            not path.startswith("/")
            or "://" in path
            or "\r" in path
            or "\n" in path
            or len(path) > 2048
        ):
            raise RuntimeError("invalid fixed upstream path")
        return f"{base}{path}"

    @staticmethod
    def _mapped_http_error(service_id: str, status: int) -> WorkspaceError:
        if status == 400:
            return WorkspaceError(
                400,
                "upstream_rejected",
                service_id,
                False,
                "The upstream service rejected the validated request.",
            )
        if status == 404:
            return WorkspaceError(
                404, "not_found", service_id, False, "The requested resource was not found."
            )
        if status == 409:
            return WorkspaceError(
                409, "conflict", service_id, False, "The requested operation conflicts with current state."
            )
        if status == 503:
            if service_id not in {
                "alert-verification",
                "direct-rt-vlm",
                "search",
                "summarization",
                "vlm-test",
            }:
                return WorkspaceError(
                    503,
                    "upstream_unavailable",
                    service_id,
                    True,
                    "The fixed upstream service is unavailable.",
                )
            return WorkspaceError(
                503,
                "provider_standby",
                service_id,
                True,
                "The service or admitted provider is currently unavailable.",
            )
        return WorkspaceError(
            502,
            "upstream_error",
            service_id,
            True,
            "The fixed upstream service returned an invalid response.",
        )

    def json(
        self,
        service_id: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        request_id: str,
        operation: str,
        timeout: float = 8.0,
        max_bytes: int = JSON_LIMIT,
    ) -> tuple[int, Any]:
        started = time.monotonic()
        body = (
            None
            if payload is None
            else json.dumps(
                payload, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": "ntc-phase15-workspace/1.0",
            "X-Request-ID": request_id,
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self._url(service_id, path),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        declared_length = int(declared)
                    except ValueError as error:
                        raise WorkspaceError(
                            502,
                            "invalid_content_length",
                            service_id,
                            False,
                            "The fixed upstream returned an invalid length.",
                        ) from error
                    if declared_length < 0 or declared_length > max_bytes:
                        raise WorkspaceError(
                            502,
                            "response_too_large",
                            service_id,
                            False,
                            "The upstream JSON response exceeded the configured limit.",
                        )
                content = response.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise WorkspaceError(
                        502,
                        "response_too_large",
                        service_id,
                        False,
                        "The upstream JSON response exceeded the configured limit.",
                    )
                status = int(response.status)
        except WorkspaceError:
            raise
        except HTTPError as error:
            error.close()
            mapped = self._mapped_http_error(service_id, int(error.code))
            self._log(
                "workspace_upstream",
                request_id=request_id,
                operation=operation,
                service_id=service_id,
                outcome="http_error",
                http_status=int(error.code),
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
            raise mapped from error
        except (TimeoutError, socket.timeout) as error:
            self._log(
                "workspace_upstream",
                request_id=request_id,
                operation=operation,
                service_id=service_id,
                outcome="timeout",
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
            raise WorkspaceError(
                504,
                "upstream_timeout",
                service_id,
                True,
                "The fixed upstream service timed out.",
            ) from error
        except (URLError, OSError) as error:
            self._log(
                "workspace_upstream",
                request_id=request_id,
                operation=operation,
                service_id=service_id,
                outcome="unavailable",
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
            raise WorkspaceError(
                503,
                "upstream_unavailable",
                service_id,
                True,
                "The fixed upstream service is unavailable.",
            ) from error
        try:
            value = (
                json.loads(content, parse_constant=_reject_json_constant)
                if content
                else {}
            )
        except (ValueError, json.JSONDecodeError) as error:
            raise WorkspaceError(
                502,
                "invalid_upstream_json",
                service_id,
                True,
                "The fixed upstream returned invalid JSON.",
            ) from error
        if not _finite_json(value):
            raise WorkspaceError(
                502,
                "invalid_upstream_json",
                service_id,
                True,
                "The fixed upstream returned non-finite JSON.",
            )
        self._log(
            "workspace_upstream",
            request_id=request_id,
            operation=operation,
            service_id=service_id,
            outcome="success",
            http_status=status,
            response_bytes=len(content),
            latency_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return status, value

    def upload(
        self,
        body: bytes,
        *,
        filename: str,
        content_type: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[int, Any]:
        return self.upload_to(
            "media-intake",
            "/api/v1/assets",
            body,
            filename=filename,
            content_type=content_type,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )

    def upload_to(
        self,
        service_id: str,
        path: str,
        body: bytes,
        *,
        filename: str,
        content_type: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[int, Any]:
        started = time.monotonic()
        request = Request(
            self._url(service_id, path),
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": content_type,
                "X-File-Name": filename,
                "Idempotency-Key": idempotency_key,
                "X-Request-ID": request_id,
                "User-Agent": "ntc-phase15-workspace/1.0",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=60) as response:
                content = response.read(JSON_LIMIT + 1)
                status = int(response.status)
        except HTTPError as error:
            content = error.read(JSON_LIMIT + 1)
            status = int(error.code)
            error.close()
            try:
                value = json.loads(content, parse_constant=_reject_json_constant)
            except (ValueError, json.JSONDecodeError):
                raise self._mapped_http_error(service_id, status)
            raise WorkspaceError(
                status if status in {400, 404, 409} else 502,
                str(value.get("code") or "upload_rejected"),
                service_id,
                False,
                "The fixed upload service rejected the validated upload.",
            )
        except (TimeoutError, socket.timeout) as error:
            raise WorkspaceError(
                504, "upstream_timeout", service_id, True, "The fixed upload service timed out."
            ) from error
        except (URLError, OSError) as error:
            raise WorkspaceError(
                503, "upstream_unavailable", service_id, True, "The fixed upload service is unavailable."
            ) from error
        if len(content) > JSON_LIMIT:
            raise WorkspaceError(
                502, "response_too_large", service_id, False, "Upload service response was too large."
            )
        try:
            value = json.loads(content, parse_constant=_reject_json_constant)
        except (ValueError, json.JSONDecodeError) as error:
            raise WorkspaceError(
                502, "invalid_upstream_json", service_id, True, "Upload service returned invalid JSON."
            ) from error
        self._log(
            "workspace_upstream",
            request_id=request_id,
            operation=f"{service_id}_upload",
            service_id=service_id,
            outcome="success",
            http_status=status,
            response_bytes=len(content),
            latency_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return status, value

    def open_binary(
        self,
        service_id: str,
        path: str,
        *,
        request_id: str,
        operation: str,
        timeout: float,
        require_length: bool,
        max_bytes: int = BINARY_LIMIT,
        accept: str = "application/octet-stream",
    ) -> BinaryResponse:
        started = time.monotonic()
        request = Request(
            self._url(service_id, path),
            headers={
                "Accept": accept,
                "User-Agent": "ntc-phase15-workspace/1.0",
                "X-Request-ID": request_id,
            },
            method="GET",
        )
        try:
            response = self._opener.open(request, timeout=timeout)
        except HTTPError as error:
            error.close()
            self._log(
                "workspace_upstream",
                request_id=request_id,
                operation=operation,
                service_id=service_id,
                outcome="http_error",
                http_status=int(error.code),
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
            raise self._mapped_http_error(service_id, int(error.code)) from error
        except (TimeoutError, socket.timeout) as error:
            self._log(
                "workspace_upstream",
                request_id=request_id,
                operation=operation,
                service_id=service_id,
                outcome="timeout",
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
            raise WorkspaceError(
                504,
                "upstream_timeout",
                service_id,
                True,
                "The fixed media upstream timed out.",
            ) from error
        except (URLError, OSError) as error:
            self._log(
                "workspace_upstream",
                request_id=request_id,
                operation=operation,
                service_id=service_id,
                outcome="unavailable",
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
            raise WorkspaceError(
                503,
                "upstream_unavailable",
                service_id,
                True,
                "The fixed media upstream is unavailable.",
            ) from error
        declared = response.headers.get("Content-Length")
        try:
            content_length = int(declared) if declared is not None else None
        except ValueError:
            response.close()
            raise WorkspaceError(
                502,
                "invalid_content_length",
                service_id,
                False,
                "The fixed media upstream returned an invalid length.",
            )
        if require_length and content_length is None:
            response.close()
            raise WorkspaceError(
                502,
                "missing_content_length",
                service_id,
                False,
                "The fixed media upstream omitted its content length.",
            )
        if content_length is not None and (
            content_length <= 0 or content_length > max_bytes
        ):
            response.close()
            raise WorkspaceError(
                502,
                "media_size_rejected",
                service_id,
                False,
                "The media response exceeded the configured limit.",
            )
        content_type_header = str(response.headers.get("Content-Type", ""))
        return BinaryResponse(
            response=response,
            content_type=content_type_header.split(";", 1)[0].strip().lower(),
            content_type_header=content_type_header,
            content_length=content_length,
            upstream_status=int(response.status),
            service_id=service_id,
            operation=operation,
            request_id=request_id,
            started=started,
        )

    def binary_complete(self, opened: BinaryResponse, transferred: int, outcome: str) -> None:
        self._log(
            "workspace_upstream",
            request_id=opened.request_id,
            operation=opened.operation,
            service_id=opened.service_id,
            outcome=outcome,
            http_status=opened.upstream_status,
            response_bytes=transferred,
            latency_ms=round((time.monotonic() - opened.started) * 1000, 1),
        )


class WorkspaceAdapter:
    def __init__(
        self,
        camera_registry_path: Path,
        logger: Callable[..., None] | None = None,
        governance_root: Path | None = None,
    ) -> None:
        self.camera_registry_path = camera_registry_path
        self.client = FixedUpstreamClient(logger)
        self._media_lock = threading.Lock()
        self._media_records: dict[str, dict[str, Any]] = {}
        self._media_order: deque[str] = deque()
        self._governance_lock = threading.RLock()
        self._governance_root = governance_root
        self._alert_tombstones_path = (
            governance_root / "alert-tombstones.json"
            if governance_root is not None
            else None
        )

    def nemotron_chat(
        self,
        messages: list[dict[str, str]],
        request_id: str,
    ) -> str:
        """Call the fixed, operator-admitted Nemotron endpoint.

        The model is deliberately addressed through the deployment-owned
        upstream allowlist. The browser cannot provide a URL or model name.
        """
        status, value = self.client.json(
            "nemotron",
            "POST",
            "/v1/chat/completions",
            payload={
                "model": "nvidia/nvidia-nemotron-nano-9b-v2",
                "messages": messages,
                "max_tokens": 256,
                "temperature": 0.2,
                "stream": False,
            },
            request_id=request_id,
            operation="nemotron_chat",
            timeout=120.0,
            max_bytes=2 * 1024 * 1024,
        )
        if status < 200 or status >= 300 or not isinstance(value, dict):
            raise WorkspaceError(
                502,
                "invalid_llm_response",
                "nemotron",
                True,
                "Nemotron returned an invalid response.",
            )
        choices = value.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise WorkspaceError(
                502,
                "invalid_llm_response",
                "nemotron",
                True,
                "Nemotron returned no answer.",
            )
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip() or len(content) > 16 * 1024:
            raise WorkspaceError(
                502,
                "invalid_llm_response",
                "nemotron",
                True,
                "Nemotron returned an invalid answer.",
            )
        return content.strip()

    def _alert_tombstones(self) -> dict[str, dict[str, Any]]:
        path = self._alert_tombstones_path
        if path is None or not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise WorkspaceError(
                500,
                "governance_state_invalid",
                "phase15-governance",
                False,
                "Alert governance state could not be read safely.",
            ) from error
        records = value.get("records", {}) if isinstance(value, dict) else {}
        if not isinstance(records, dict):
            raise WorkspaceError(
                500,
                "governance_state_invalid",
                "phase15-governance",
                False,
                "Alert governance state is invalid.",
            )
        return {
            key: nested
            for key, nested in records.items()
            if isinstance(key, str) and isinstance(nested, dict)
        }

    def _write_alert_tombstones(
        self, records: dict[str, dict[str, Any]]
    ) -> None:
        path = self._alert_tombstones_path
        if path is None:
            raise WorkspaceError(
                503,
                "governance_unavailable",
                "phase15-governance",
                True,
                "Alert governance storage is unavailable.",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": STORE_ID,
                    "updated_at": utc_now(),
                    "records": records,
                },
                separators=(",", ":"),
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _tombstone_key(source: str, identifier: str) -> str:
        return f"{source}:{identifier}"

    @staticmethod
    def _require_identity(
        value: Any, service_id: str, camera_id: str | None = None
    ) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != SCHEMA_VERSION
            or value.get("store_id") != STORE_ID
            or (
                camera_id is not None
                and value.get("camera_id") != camera_id
            )
        ):
            raise WorkspaceError(
                502,
                "upstream_identity_mismatch",
                service_id,
                True,
                "The fixed upstream returned mismatched identity fields.",
            )
        return value

    def _remember_media(self, value: Any) -> None:
        discovered: list[tuple[str, dict[str, Any]]] = []

        def canonical_utc(raw: Any) -> str | None:
            try:
                return _utc(raw, "media.timestamp").isoformat()
            except WorkspaceError:
                return None

        def visit(item: Any, inherited_camera: str | None = None) -> None:
            if isinstance(item, dict):
                camera_id = str(item.get("camera_id") or inherited_camera or "")
                if CAMERA_ID_PATTERN.fullmatch(camera_id) is None:
                    camera_id = ""
                for key, nested in item.items():
                    if key in {"asset_uri", "reference"}:
                        identifier = _selected_clip_id(nested)
                        if identifier is not None:
                            digest = str(
                                item.get("clip_sha256")
                                or item.get("asset_sha256")
                                or item.get("content_sha256")
                                or ""
                            )
                            if HEX_ID_PATTERN.fullmatch(digest) is None:
                                digest = ""
                            discovered.append(
                                (
                                    identifier,
                                    {
                                        "camera_id": (
                                            camera_id or None
                                            if digest
                                            else None
                                        ),
                                        "start_time": (
                                            canonical_utc(
                                                item.get("clip_start_time")
                                                or item.get("start_time")
                                            )
                                            if digest
                                            else None
                                        ),
                                        "end_time": (
                                            canonical_utc(
                                                item.get("clip_end_time")
                                                or item.get("end_time")
                                            )
                                            if digest
                                            else None
                                        ),
                                        "content_sha256": digest or None,
                                    },
                                )
                            )
                    visit(nested, camera_id or inherited_camera)
            elif isinstance(item, list):
                for nested in item:
                    visit(nested, inherited_camera)

        visit(value)
        if not discovered:
            return
        with self._media_lock:
            for identifier, candidate in discovered:
                current = self._media_records.get(identifier)
                if current is None:
                    while len(self._media_order) >= 10_000:
                        expired = self._media_order.popleft()
                        self._media_records.pop(expired, None)
                    current = {
                        "camera_id": None,
                        "start_time": None,
                        "end_time": None,
                        "content_sha256": None,
                        "conflict": False,
                    }
                    self._media_records[identifier] = current
                    self._media_order.append(identifier)
                for field in (
                    "camera_id",
                    "start_time",
                    "end_time",
                    "content_sha256",
                ):
                    nested = candidate.get(field)
                    if nested is None:
                        continue
                    if current.get(field) is None:
                        current[field] = nested
                    elif current.get(field) != nested:
                        current["conflict"] = True

    def _media_known(self, identifier: str) -> bool:
        with self._media_lock:
            return identifier in self._media_records

    def _media_record(self, identifier: str) -> dict[str, Any] | None:
        with self._media_lock:
            value = self._media_records.get(identifier)
            return dict(value) if value is not None else None

    def _camera_registry(self) -> dict[str, Any]:
        try:
            value = json.loads(
                self.camera_registry_path.read_text(encoding="utf-8"),
                parse_constant=_reject_json_constant,
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise WorkspaceError(
                503,
                "camera_registry_unavailable",
                "camera-registry",
                True,
                "The credential-free camera registry is unavailable.",
            ) from error
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != SCHEMA_VERSION
            or value.get("store", {}).get("store_id") != STORE_ID
            or not isinstance(value.get("cameras"), list)
        ):
            raise WorkspaceError(
                503,
                "camera_registry_invalid",
                "camera-registry",
                False,
                "The credential-free camera registry is invalid.",
            )
        if not _finite_json(value):
            raise WorkspaceError(
                503,
                "camera_registry_invalid",
                "camera-registry",
                False,
                "The credential-free camera registry is invalid.",
            )
        return value

    def _camera(self, camera_id: str) -> dict[str, Any]:
        if CAMERA_ID_PATTERN.fullmatch(camera_id) is None:
            raise WorkspaceError(
                404, "camera_not_found", "camera-registry", False, "Camera was not found."
            )
        camera = next(
            (
                item
                for item in self._camera_registry()["cameras"]
                if isinstance(item, dict) and item.get("camera_id") == camera_id
            ),
            None,
        )
        if camera is None:
            raise WorkspaceError(
                404, "camera_not_found", "camera-registry", False, "Camera was not found."
            )
        return camera

    @staticmethod
    def _flatten_streams(value: Any) -> list[dict[str, Any]]:
        wrappers = value if isinstance(value, list) else value.get("streams", [])
        result: list[dict[str, Any]] = []
        if not isinstance(wrappers, list):
            return result
        for wrapper in wrappers:
            if not isinstance(wrapper, dict):
                continue
            if any(key in wrapper for key in ("streamId", "id", "uuid")):
                result.append(wrapper)
                continue
            for nested in wrapper.values():
                if isinstance(nested, list):
                    result.extend(item for item in nested if isinstance(item, dict))
        return result

    @staticmethod
    def _stream_identifier(stream: dict[str, Any]) -> str:
        identifier = str(
            stream.get("streamId") or stream.get("sensorId") or stream.get("id") or stream.get("uuid") or ""
        )
        return identifier if STREAM_ID_PATTERN.fullmatch(identifier) else ""

    @staticmethod
    def _stream_status_map(value: Any) -> tuple[dict[str, str], dict[str, str]]:
        """Return status keyed by safe stream id and display name.

        VIOS versions expose status either as a map or as a list. Keep this
        adapter tolerant of both shapes while never returning upstream URLs.
        """
        by_id: dict[str, str] = {}
        by_name: dict[str, str] = {}
        values: list[Any] = []
        if isinstance(value, list):
            values = value
        elif isinstance(value, dict):
            values = list(value.values())
        for item in values:
            if not isinstance(item, dict):
                continue
            state = str(item.get("state") or item.get("status") or "unknown").lower()[:32]
            identifier = str(item.get("streamId") or item.get("sensorId") or item.get("id") or item.get("uuid") or "")
            name = str(item.get("name") or item.get("sensorName") or "")
            if STREAM_ID_PATTERN.fullmatch(identifier):
                by_id[identifier] = state
            if name:
                by_name[name[:160]] = state
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, dict):
                    identifier = str(key)
                    state = str(item.get("state") or item.get("status") or "unknown").lower()[:32]
                    if STREAM_ID_PATTERN.fullmatch(identifier):
                        by_id.setdefault(identifier, state)
        return by_id, by_name

    def stream_sources(self, request_id: str) -> dict[str, Any]:
        """Expose a credential-free inventory of all VIOS stream sources."""
        _, raw_streams = self.client.json(
            "vios",
            "GET",
            "/api/v1/sensor/streams",
            request_id=request_id,
            operation="stream_sources_inventory",
            timeout=5,
        )
        _, raw_status = self.client.json(
            "vios",
            "GET",
            "/api/v1/sensor/status",
            request_id=request_id,
            operation="stream_sources_status",
            timeout=5,
        )
        status_by_id, status_by_name = self._stream_status_map(raw_status)
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for stream in self._flatten_streams(raw_streams):
            source_id = self._stream_identifier(stream)
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            name = str(stream.get("name") or stream.get("sensorName") or source_id)[:160]
            metadata = stream.get("metadata") if isinstance(stream.get("metadata"), dict) else stream
            codec = str(metadata.get("codec") or metadata.get("encoding") or "unknown")[:16]
            resolution = str(metadata.get("resolution") or "unknown")[:32]
            framerate = str(metadata.get("framerate") or metadata.get("fps") or "unknown")[:16]
            managed = CAMERA_ID_PATTERN.fullmatch(name) is None
            sources.append(
                {
                    "source_id": source_id,
                    "name": name,
                    "source_type": "rtsp",
                    "state": status_by_id.get(source_id, status_by_name.get(name, "unknown")),
                    "managed": managed,
                    "can_delete": managed,
                    "metadata": {
                        "codec": codec,
                        "resolution": resolution,
                        "framerate": framerate,
                    },
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "generated_at": utc_now(),
            "sources": sources,
        }

    def add_stream_source(self, payload: dict[str, Any], request_id: str) -> tuple[int, dict[str, Any]]:
        allowed = {"schema_version", "store_id", "name", "url", "idempotency_key"}
        if set(payload).difference(allowed):
            raise WorkspaceError(400, "unsupported_stream_source_fields", "request", False, "Stream source fields are invalid.")
        _validate_identity(payload, "Stream source")
        _validate_idempotency_key(payload)
        name = str(payload.get("name") or "").strip()
        if STREAM_SOURCE_NAME_PATTERN.fullmatch(name) is None:
            raise WorkspaceError(400, "invalid_stream_source_name", "request", False, "Stream source name is invalid.")
        raw_url = payload.get("url")
        if not isinstance(raw_url, str) or len(raw_url) > 2048 or "\r" in raw_url or "\n" in raw_url:
            raise WorkspaceError(400, "invalid_stream_source_url", "request", False, "RTSP URL is invalid.")
        parsed = urlsplit(raw_url.strip())
        if parsed.scheme.lower() != "rtsp" or not parsed.hostname or parsed.fragment:
            raise WorkspaceError(400, "invalid_stream_source_url", "request", False, "RTSP URL is invalid.")
        # Do not log or persist this payload in the project. VIOS receives it
        # only for the sensor onboarding operation and the response is scrubbed.
        status, result = self.client.json(
            "vios",
            "POST",
            "/api/v1/sensor/add",
            payload={
                "name": name,
                "location": name,
                "sensorUrl": parsed.geturl(),
                "username": "",
                "password": "",
                "verifyRtsp": True,
            },
            request_id=request_id,
            operation="stream_source_add",
            timeout=30,
        )
        result_dict = result if isinstance(result, dict) else {}
        source_id = str(
            result_dict.get("streamId") or result_dict.get("sensorId") or result_dict.get("id") or result_dict.get("uuid") or ""
        )
        if source_id and STREAM_ID_PATTERN.fullmatch(source_id) is None:
            source_id = ""
        return status, {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "status": "accepted",
            "source": {
                "source_id": source_id,
                "name": name,
                "source_type": "rtsp",
                "state": "starting",
                "managed": True,
                "can_delete": bool(source_id),
            },
        }

    def delete_stream_source(self, source_id: str, request_id: str) -> tuple[int, dict[str, Any]]:
        if STREAM_ID_PATTERN.fullmatch(source_id) is None:
            raise WorkspaceError(400, "invalid_stream_source_id", "request", False, "Stream source id is invalid.")
        inventory = self.stream_sources(request_id)
        source = next((item for item in inventory["sources"] if item["source_id"] == source_id), None)
        if source is None:
            raise WorkspaceError(404, "stream_source_not_found", "vios", False, "Stream source was not found.")
        if not source.get("can_delete"):
            raise WorkspaceError(409, "stable_camera_protected", "camera-registry", False, "Stable camera sources cannot be deleted here.")
        status, _ = self.client.json(
            "vios",
            "DELETE",
            f"/api/v1/sensor/{source_id}",
            payload={},
            request_id=request_id,
            operation="stream_source_delete",
            timeout=15,
        )
        return status, {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "status": "deleted",
            "source_id": source_id,
        }

    def delete_stream_source_by_name(self, name: str, request_id: str) -> tuple[int, dict[str, Any]]:
        """Delete a managed VIOS source for the legacy UI name-based route.

        The upstream VSS Video Management UI identifies RTSP sources by their
        display name. Resolve that name against the credential-free VIOS
        inventory first, then reuse the stable-id deletion guard above.
        """
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 160
            or any(ord(character) < 32 or ord(character) == 127 for character in name)
            or "/" in name
        ):
            raise WorkspaceError(
                400,
                "invalid_stream_source_name",
                "request",
                False,
                "Stream source name is invalid.",
            )
        inventory = self.stream_sources(request_id)
        source = next(
            (item for item in inventory["sources"] if item.get("name") == name),
            None,
        )
        if source is None:
            raise WorkspaceError(
                404,
                "stream_source_not_found",
                "vios",
                False,
                "Stream source was not found.",
            )
        return self.delete_stream_source(str(source["source_id"]), request_id)

    def _vios_inventory(
        self, request_id: str
    ) -> tuple[dict[str, str], dict[str, str], bool]:
        try:
            _, raw_streams = self.client.json(
                "vios",
                "GET",
                "/api/v1/sensor/streams",
                request_id=request_id,
                operation="camera_inventory",
                timeout=5,
            )
            _, raw_status = self.client.json(
                "vios",
                "GET",
                "/api/v1/sensor/status",
                request_id=request_id,
                operation="camera_status",
                timeout=5,
            )
        except WorkspaceError:
            return {}, {}, False
        stream_ids: dict[str, str] = {}
        for stream in self._flatten_streams(raw_streams):
            camera_id = str(stream.get("name", ""))
            identifier = str(
                stream.get("streamId") or stream.get("id") or stream.get("uuid") or ""
            )
            if (
                CAMERA_ID_PATTERN.fullmatch(camera_id)
                and STREAM_ID_PATTERN.fullmatch(identifier)
            ):
                stream_ids[camera_id] = identifier
        states: dict[str, str] = {}
        values = raw_status.values() if isinstance(raw_status, dict) else []
        for status in values:
            if not isinstance(status, dict):
                continue
            camera_id = str(status.get("name", ""))
            state = str(status.get("state", "unknown")).lower()[:32]
            if CAMERA_ID_PATTERN.fullmatch(camera_id):
                states[camera_id] = state
        return stream_ids, states, True

    def _ai_state(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "camera-live",
            "GET",
            "/api/ai-state",
            request_id=request_id,
            operation="camera_ai_state",
            timeout=4,
            max_bytes=256 * 1024,
        )
        return self._require_identity(value, "camera-live", "cam-01")

    @staticmethod
    def _safe_stream(stream: Any) -> dict[str, Any]:
        if not isinstance(stream, dict):
            return {}
        return {
            "codec": str(stream.get("codec", "unknown"))[:16],
            "width": int(stream.get("width", 0) or 0),
            "height": int(stream.get("height", 0) or 0),
            "fps": float(stream.get("fps", 0) or 0),
        }

    def cameras(self, request_id: str) -> dict[str, Any]:
        registry = self._camera_registry()
        stream_ids, states, inventory_available = self._vios_inventory(request_id)
        try:
            ai_state = self._ai_state(request_id)
            live_available = True
        except WorkspaceError:
            ai_state = {}
            live_available = False
        cameras: list[dict[str, Any]] = []
        for camera in registry["cameras"]:
            if not isinstance(camera, dict):
                continue
            camera_id = str(camera.get("camera_id", ""))
            source_type = "physical" if camera_id == "cam-01" else "replay"
            registered = camera_id in stream_ids
            vios_state = states.get(camera_id, "unknown")
            preview_available = camera_id == "cam-01" and live_available
            cameras.append(
                {
                    "camera_id": camera_id,
                    "name": str(camera.get("name", camera_id))[:160],
                    "enabled": bool(camera.get("enabled")),
                    "source_type": source_type,
                    "source_badge": "Physical" if source_type == "physical" else "Replay",
                    "registered": registered,
                    "video_status": (
                        "live"
                        if registered and vios_state == "online"
                        else "offline"
                        if inventory_available
                        else "unavailable"
                    ),
                    "vios_state": vios_state,
                    "browser_preview": preview_available,
                    "preview_reason": (
                        None
                        if preview_available
                        else "Live browser preview is only implemented for cam-01."
                    ),
                    "ai_enabled": camera_id == "cam-01",
                    "ai_status": (
                        str(ai_state.get("ai_status", "unavailable"))
                        if camera_id == "cam-01"
                        else "not_configured"
                    ),
                    "ai_connected": (
                        bool(ai_state.get("ai_connected"))
                        if camera_id == "cam-01"
                        else False
                    ),
                    "last_seen_utc": (
                        ai_state.get("metadata_timestamp_utc")
                        if camera_id == "cam-01"
                        else None
                    ),
                    "source_fps": (
                        ai_state.get("source_fps") if camera_id == "cam-01" else None
                    ),
                    "main_stream": self._safe_stream(camera.get("main_stream")),
                    "ai_substream": self._safe_stream(camera.get("ai_substream")),
                    "live_url": (
                        f"{WORKSPACE_PREFIX}/cameras/{camera_id}/live.mjpeg"
                        if preview_available
                        else None
                    ),
                    "thumbnail_url": (
                        f"{WORKSPACE_PREFIX}/cameras/{camera_id}/thumbnail.jpg"
                        if registered
                        else None
                    ),
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "generated_at": utc_now(),
            "source_mode": str(registry.get("source_mode", "")),
            "inventory_available": inventory_available,
            "count": len(cameras),
            "cameras": cameras,
        }

    def camera_state(self, camera_id: str, request_id: str) -> dict[str, Any]:
        self._camera(camera_id)
        if camera_id != "cam-01":
            return {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "camera_id": camera_id,
                "server_timestamp_utc": utc_now(),
                "preview_available": False,
                "ai_connected": False,
                "ai_status": "not_configured",
                "status_message": "AI and browser live preview are not configured for this replay source.",
                "objects": [],
            }
        value = dict(self._ai_state(request_id))
        value["preview_available"] = True
        value["live_url"] = f"{WORKSPACE_PREFIX}/cameras/cam-01/live.mjpeg"
        return value

    def open_live(self, camera_id: str, request_id: str) -> BinaryResponse:
        self._camera(camera_id)
        if camera_id != "cam-01":
            raise WorkspaceError(
                409,
                "capability_unavailable",
                "camera-live",
                False,
                "Live browser preview is only implemented for cam-01.",
            )
        opened = self.client.open_binary(
            "camera-live",
            "/mjpeg",
            request_id=request_id,
            operation="camera_live",
            timeout=12,
            require_length=False,
            accept="multipart/x-mixed-replace",
        )
        if opened.content_type != "multipart/x-mixed-replace":
            opened.response.close()
            raise WorkspaceError(
                502,
                "invalid_media_type",
                "camera-live",
                True,
                "The live presentation endpoint did not return MJPEG.",
            )
        return opened

    def thumbnail(self, camera_id: str, at_utc: str, request_id: str) -> bytes:
        self._camera(camera_id)
        stream_ids, _, available = self._vios_inventory(request_id)
        stream_id = stream_ids.get(camera_id)
        if not available or stream_id is None:
            raise WorkspaceError(
                503,
                "thumbnail_unavailable",
                "vios",
                True,
                "No registered VIOS stream is available for this camera.",
            )
        timestamp = at_utc
        if timestamp:
            _utc(timestamp, "at")
        else:
            _, timelines = self.client.json(
                "vios",
                "GET",
                f"/api/v1/storage/{stream_id}/timelines",
                request_id=request_id,
                operation="camera_timeline",
                timeout=6,
            )
            if not isinstance(timelines, list) or not timelines:
                raise WorkspaceError(
                    404,
                    "thumbnail_not_observed",
                    "vios",
                    False,
                    "No recorded interval is available for this camera.",
                )
            intervals: list[tuple[datetime, datetime]] = []
            for interval in timelines:
                if not isinstance(interval, dict):
                    continue
                try:
                    interval_start = _utc(
                        interval.get("startTime"), "timeline.startTime"
                    )
                    interval_end = _utc(
                        interval.get("endTime"), "timeline.endTime"
                    )
                except WorkspaceError:
                    continue
                if interval_end > interval_start:
                    intervals.append((interval_start, interval_end))
            if not intervals:
                raise WorkspaceError(
                    502,
                    "invalid_timeline",
                    "vios",
                    True,
                    "VIOS returned an invalid recording timeline.",
                )
            start_time, end_time = max(
                intervals, key=lambda interval: interval[1]
            )
            selected_time = max(start_time, end_time - timedelta(seconds=1))
            timestamp = selected_time.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            )
        query = urlencode({"startTime": timestamp, "width": "640", "height": "360"})
        opened = self.client.open_binary(
            "vios",
            f"/api/v1/storage/stream/{stream_id}/picture?{query}",
            request_id=request_id,
            operation="camera_thumbnail",
            timeout=12,
            require_length=True,
            max_bytes=THUMBNAIL_LIMIT,
            accept="image/jpeg",
        )
        try:
            content = opened.response.read(THUMBNAIL_LIMIT + 1)
        finally:
            opened.response.close()
        if (
            len(content) > THUMBNAIL_LIMIT
            or opened.content_type != "image/jpeg"
            or not content.startswith(b"\xff\xd8\xff")
        ):
            raise WorkspaceError(
                502,
                "invalid_thumbnail",
                "vios",
                True,
                "VIOS returned an invalid JPEG thumbnail.",
            )
        self.client.binary_complete(opened, len(content), "success")
        return content

    def analytics_state(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "behavior-analytics",
            "GET",
            "/api/v1/state",
            request_id=request_id,
            operation="analytics_state",
            timeout=8,
        )
        return self._require_identity(value, "behavior-analytics", "cam-01")

    def analytics_events(
        self, query: dict[str, list[str]], request_id: str
    ) -> dict[str, Any]:
        if set(query).difference({"include_evaluation", "limit"}):
            raise WorkspaceError(
                400,
                "unsupported_query_parameter",
                "request",
                False,
                "Analytics event query contains unsupported parameters.",
            )
        include = _one(query, "include_evaluation", "false").lower()
        if include not in {"true", "false"}:
            raise WorkspaceError(
                400,
                "invalid_parameter",
                "request",
                False,
                "include_evaluation must be true or false.",
            )
        _, value = self.client.json(
            "behavior-analytics",
            "GET",
            f"/api/v1/events?include_evaluation={include}",
            request_id=request_id,
            operation="analytics_events",
            timeout=8,
        )
        if not isinstance(value, dict) or not isinstance(value.get("events"), list):
            raise WorkspaceError(
                502,
                "invalid_analytics_events",
                "behavior-analytics",
                True,
                "Behavior analytics returned an invalid event list.",
            )
        limit = _bounded_int(_one(query, "limit", "100"), "limit", 1, 100)
        events = [
            event
            for event in value["events"]
            if isinstance(event, dict)
            and event.get("schema_version") == SCHEMA_VERSION
            and event.get("store_id") == STORE_ID
            and event.get("camera_id") == "cam-01"
        ][:limit]
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "camera_id": "cam-01",
            "count": len(events),
            "events": events,
        }

    def analytics_config(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "behavior-analytics",
            "GET",
            "/api/v1/config",
            request_id=request_id,
            operation="analytics_config",
            timeout=6,
        )
        checked = self._require_identity(
            value, "behavior-analytics", "cam-01"
        )
        try:
            self._reject_connection_fields(checked)
        except WorkspaceError as error:
            raise WorkspaceError(
                502,
                "invalid_analytics_config",
                "behavior-analytics",
                False,
                "Behavior analytics returned unsafe configuration fields.",
            ) from error
        self._validate_analytics_config_shape(checked)
        return checked

    @staticmethod
    def _reject_connection_fields(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if re.search(
                    r"(?:authorization|cookie|password|secret|token|username|rtsp|uri|url)",
                    str(key),
                    re.IGNORECASE,
                ):
                    raise WorkspaceError(
                        400,
                        "connection_data_rejected",
                        "request",
                        False,
                        "Connection data is not accepted by analytics configuration.",
                    )
                WorkspaceAdapter._reject_connection_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                WorkspaceAdapter._reject_connection_fields(nested)
        elif isinstance(value, str) and re.search(
            r"(?:rtsp|rtsps|https?|file|s3|camera)://", value, re.IGNORECASE
        ):
            raise WorkspaceError(
                400,
                "connection_data_rejected",
                "request",
                False,
                "Connection data is not accepted by analytics configuration.",
            )

    @staticmethod
    def _validate_analytics_config_shape(value: dict[str, Any]) -> None:
        expected = {
            "schema_version",
            "store_id",
            "camera_id",
            "config_version",
            "coordinate_space",
            "calibration_status",
            "source",
            "object_types",
            "tracking",
            "people_counting",
            "zones",
            "queue",
            "heatmap",
        }
        nested = {
            "source": {"model_id", "model_version", "topic"},
            "tracking": {"tracker_id", "ttl_seconds"},
            "queue": {
                "id",
                "zone_id",
                "length_threshold",
                "wait_threshold_seconds",
            },
            "heatmap": {"id", "columns", "rows", "emit_interval_seconds"},
        }
        valid = set(value) == expected
        valid = valid and all(
            isinstance(value.get(key), dict)
            and set(value[key]) == keys
            for key, keys in nested.items()
        )
        people = value.get("people_counting")
        line = people.get("line") if isinstance(people, dict) else None
        valid = (
            valid
            and isinstance(value.get("config_version"), int)
            and not isinstance(value.get("config_version"), bool)
            and value["config_version"] >= 1
            and isinstance(people, dict)
            and set(people) == {"line"}
            and isinstance(line, dict)
            and set(line)
            == {"id", "start", "end", "deadband", "directions"}
            and isinstance(line.get("directions"), dict)
            and set(line["directions"])
            == {"negative_to_positive", "positive_to_negative"}
            and isinstance(value.get("object_types"), list)
            and all(isinstance(item, str) for item in value["object_types"])
            and isinstance(value.get("zones"), list)
            and all(
                isinstance(zone, dict)
                and set(zone)
                == {
                    "id",
                    "name",
                    "type",
                    "polygon",
                    "dwell_threshold_seconds",
                }
                for zone in value["zones"]
            )
            and isinstance(
                value.get("queue", {}).get("length_threshold"), int
            )
            and not isinstance(
                value.get("queue", {}).get("length_threshold"), bool
            )
            and isinstance(
                value.get("queue", {}).get("wait_threshold_seconds"),
                (int, float),
            )
            and not isinstance(
                value.get("queue", {}).get("wait_threshold_seconds"), bool
            )
        )

        def finite(item: Any) -> bool:
            if isinstance(item, float):
                return math.isfinite(item)
            if isinstance(item, dict):
                return all(finite(nested_value) for nested_value in item.values())
            if isinstance(item, list):
                return all(finite(nested_value) for nested_value in item)
            return True

        if not valid or not finite(value):
            raise WorkspaceError(
                502,
                "invalid_analytics_config",
                "behavior-analytics",
                False,
                "Behavior analytics returned an unsupported configuration shape.",
            )

    @staticmethod
    def _validate_config_update(
        current: dict[str, Any], proposed: dict[str, Any]
    ) -> None:
        editable = {
            ("config_version",),
            ("queue", "length_threshold"),
            ("queue", "wait_threshold_seconds"),
        }

        def compare(old: Any, new: Any, path: tuple[str, ...]) -> None:
            if isinstance(old, dict):
                if not isinstance(new, dict) or set(new) != set(old):
                    raise WorkspaceError(
                        409,
                        "rule_shape_change_unavailable",
                        "behavior-analytics",
                        False,
                        "Creating, deleting or reshaping analytics rules is not available.",
                    )
                for key in old:
                    compare(old[key], new[key], path + (str(key),))
                return
            if isinstance(old, list):
                if new != old:
                    raise WorkspaceError(
                        409,
                        "rule_shape_change_unavailable",
                        "behavior-analytics",
                        False,
                        "This analytics rule field is read-only in the unified workspace.",
                    )
                return
            if path not in editable and new != old:
                raise WorkspaceError(
                    409,
                    "rule_field_read_only",
                    "behavior-analytics",
                    False,
                    "Only the existing queue thresholds can be updated safely.",
                )

        compare(current, proposed, ())
        _bounded_int(
            proposed.get("queue", {}).get("length_threshold"),
            "queue.length_threshold",
            1,
            1000,
        )
        _bounded_float(
            proposed.get("queue", {}).get("wait_threshold_seconds"),
            "queue.wait_threshold_seconds",
            1,
            86_400,
        )

    def update_analytics_config(
        self, payload: dict[str, Any], request_id: str
    ) -> tuple[int, dict[str, Any]]:
        self._reject_connection_fields(payload)
        if (
            payload.get("schema_version") != SCHEMA_VERSION
            or payload.get("store_id") != STORE_ID
            or payload.get("camera_id") != "cam-01"
        ):
            raise WorkspaceError(
                400,
                "identity_mismatch",
                "request",
                False,
                "Analytics identity fields do not match store-001/cam-01.",
            )
        current = self.analytics_config(request_id)
        if not isinstance(current, dict):
            raise WorkspaceError(
                502,
                "invalid_analytics_config",
                "behavior-analytics",
                True,
                "Behavior analytics returned an invalid configuration.",
            )
        expected = int(current.get("config_version", 0)) + 1
        if payload.get("config_version") != expected:
            raise WorkspaceError(
                409,
                "config_version_conflict",
                "behavior-analytics",
                False,
                f"config_version must be {expected}.",
            )
        self._validate_config_update(current, payload)
        status, value = self.client.json(
            "behavior-analytics",
            "PUT",
            "/api/v1/config",
            payload=payload,
            request_id=request_id,
            operation="analytics_config_update",
            timeout=10,
        )
        if (
            not isinstance(value, dict)
            or value.get("status") != "updated"
            or value.get("config_version") != expected
        ):
            raise WorkspaceError(
                502,
                "invalid_analytics_update",
                "behavior-analytics",
                True,
                "Behavior analytics returned a mismatched update result.",
            )
        return status, {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "camera_id": "cam-01",
            "status": "updated",
            "config_version": expected,
            "updated_at": utc_now(),
        }

    def incident_state(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "incidents",
            "GET",
            "/api/v1/state",
            request_id=request_id,
            operation="incident_state",
            timeout=6,
        )
        checked = self._require_identity(value, "incidents", "cam-01")
        self._remember_media(checked)
        return checked

    @staticmethod
    def _normalize_alert(value: dict[str, Any], source: str) -> dict[str, Any]:
        identifier_key = "incident_id" if source == "hybrid" else "direct_alert_id"
        identifier = str(value.get(identifier_key, ""))
        media_identifier = _selected_clip_id(value.get("asset_uri"))
        clip_sha256 = str(value.get("clip_sha256") or "")
        if HEX_ID_PATTERN.fullmatch(clip_sha256) is None:
            clip_sha256 = ""
        return {
            "id": identifier,
            "source": source,
            "source_label": (
                "Hybrid CV→VLM" if source == "hybrid" else "Direct RT-VLM"
            ),
            "schema_version": value.get("schema_version"),
            "store_id": value.get("store_id"),
            "camera_id": value.get("camera_id"),
            "event_type": value.get("event_type"),
            "timestamp": value.get("@timestamp") or value.get("created_at"),
            "start_time": value.get("start_time"),
            "end_time": value.get("end_time"),
            "clip_start_time": value.get("clip_start_time"),
            "clip_end_time": value.get("clip_end_time"),
            "status": value.get("status") or (
                "verified" if value.get("verdict") != "uncertain" else "needs_review"
            ),
            "verdict": value.get("verdict", "uncertain"),
            "confidence": value.get("confidence"),
            "reason": str(value.get("reason", ""))[:2000],
            "model_id": value.get("verifier_model_id") or value.get("model_id"),
            "model_version": value.get("verifier_model_version")
            or value.get("model_version"),
            "source_model_id": value.get("source_model_id"),
            "source_model_version": value.get("source_model_version"),
            "prompt_version": value.get("prompt_version"),
            "latency_ms": value.get("latency_ms"),
            "feedback_label": value.get("feedback_label"),
            "feedback_at": value.get("feedback_at"),
            "feedback_note": str(value.get("feedback_note", ""))[:1000],
            "evidence": value.get("evidence") if source == "hybrid" else None,
            "clip_sha256": clip_sha256 or None,
            "content_sha256": clip_sha256 or None,
            "clip_bytes": value.get("clip_bytes"),
            "asset_uri": (
                f"selected-clip://{media_identifier}.mp4"
                if media_identifier is not None
                else None
            ),
            "provenance": {
                "workflow": source,
                "source_model_id": value.get("source_model_id"),
                "source_model_version": value.get("source_model_version"),
                "verifier_model_id": value.get("verifier_model_id"),
                "verifier_model_version": value.get("verifier_model_version"),
                "prompt_version": value.get("prompt_version"),
            },
            "media_available": media_identifier == identifier and source == "hybrid",
            "media_url": (
                f"{WORKSPACE_PREFIX}/media/{media_identifier}.mp4"
                if media_identifier == identifier and source == "hybrid"
                else None
            ),
            "created_at": value.get("created_at"),
            "updated_at": value.get("updated_at"),
        }

    def _alert_rows(
        self, source: str, request_id: str, size: int = 500
    ) -> list[dict[str, Any]]:
        service_id = (
            "alert-verification" if source == "hybrid" else "direct-rt-vlm"
        )
        _, value = self.client.json(
            service_id,
            "GET",
            f"/api/v1/alerts?size={size}",
            request_id=request_id,
            operation=f"{source}_alerts",
            timeout=12,
        )
        rows = value.get("alerts", []) if isinstance(value, dict) else []
        if not isinstance(rows, list):
            raise WorkspaceError(
                502,
                "invalid_alerts",
                service_id,
                True,
                "The alert service returned an invalid list.",
            )
        identifier_key = "incident_id" if source == "hybrid" else "direct_alert_id"
        trusted = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("schema_version") == SCHEMA_VERSION
            and row.get("store_id") == STORE_ID
            and CAMERA_ID_PATTERN.fullmatch(str(row.get("camera_id", "")))
            and HEX_ID_PATTERN.fullmatch(str(row.get(identifier_key, "")))
        ]
        self._remember_media(trusted)
        return trusted

    def alerts(
        self, query: dict[str, list[str]], request_id: str
    ) -> dict[str, Any]:
        if set(query).difference(
            {
                "source",
                "camera_id",
                "verdict",
                "alert_type",
                "from",
                "to",
                "limit",
                "offset",
                "deleted",
            }
        ):
            raise WorkspaceError(
                400,
                "unsupported_query_parameter",
                "request",
                False,
                "Alert query contains unsupported parameters.",
            )
        source = _one(query, "source", "all").lower()
        if source not in {"all", "hybrid", "direct"}:
            raise WorkspaceError(
                400,
                "invalid_parameter",
                "request",
                False,
                "source must be all, hybrid or direct.",
            )
        sources = ["hybrid", "direct"] if source == "all" else [source]
        rows: list[dict[str, Any]] = []
        source_status: dict[str, dict[str, Any]] = {}
        failures: list[WorkspaceError] = []
        for selected in sources:
            try:
                selected_rows = self._alert_rows(selected, request_id)
                rows.extend(
                    self._normalize_alert(item, selected)
                    for item in selected_rows
                )
                source_status[selected] = {
                    "available": True,
                    "count": len(selected_rows),
                }
            except WorkspaceError as error:
                failures.append(error)
                source_status[selected] = {
                    "available": False,
                    "code": error.code,
                    "retryable": error.retryable,
                }
        if failures and len(failures) == len(sources):
            raise failures[0]
        camera_id = _one(query, "camera_id")
        if camera_id:
            self._camera(camera_id)
            rows = [item for item in rows if item.get("camera_id") == camera_id]
        verdict = _one(query, "verdict").lower()
        if verdict:
            if verdict not in {"confirmed", "rejected", "uncertain"}:
                raise WorkspaceError(
                    400,
                    "invalid_parameter",
                    "request",
                    False,
                    "verdict is invalid.",
                )
            rows = [item for item in rows if item.get("verdict") == verdict]
        event_type = _one(query, "alert_type")
        if event_type:
            rows = [item for item in rows if item.get("event_type") == event_type]
        from_utc = _one(query, "from")
        to_utc = _one(query, "to")
        lower = _utc(from_utc, "from") if from_utc else None
        upper = _utc(to_utc, "to") if to_utc else None
        if lower and upper and upper <= lower:
            raise WorkspaceError(
                400,
                "invalid_time_window",
                "request",
                False,
                "to must be after from.",
            )
        if lower or upper:
            filtered = []
            for item in rows:
                timestamp = item.get("start_time") or item.get("timestamp")
                try:
                    moment = _utc(timestamp, "alert.timestamp")
                except WorkspaceError:
                    continue
                if lower and moment < lower:
                    continue
                if upper and moment >= upper:
                    continue
                filtered.append(item)
            rows = filtered
        rows.sort(
            key=lambda item: str(item.get("timestamp") or item.get("start_time") or ""),
            reverse=True,
        )
        deleted_filter = _one(query, "deleted", "exclude").lower()
        if deleted_filter not in {"exclude", "include", "only"}:
            raise WorkspaceError(
                400,
                "invalid_parameter",
                "request",
                False,
                "deleted must be exclude, include or only.",
            )
        with self._governance_lock:
            tombstones = self._alert_tombstones()
        for item in rows:
            record = tombstones.get(
                self._tombstone_key(str(item.get("source")), str(item.get("id")))
            )
            item["deleted"] = record is not None
            item["deleted_at"] = record.get("deleted_at") if record else None
            item["restore_available"] = record is not None
        if deleted_filter == "exclude":
            rows = [item for item in rows if not item["deleted"]]
        elif deleted_filter == "only":
            rows = [item for item in rows if item["deleted"]]
        total = len(rows)
        limit = _bounded_int(_one(query, "limit", "100"), "limit", 1, 200)
        offset = _bounded_int(_one(query, "offset", "0"), "offset", 0, 1000)
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "source": source,
            "total": total,
            "offset": offset,
            "limit": limit,
            "alerts": rows[offset : offset + limit],
            "bounded_history": 500,
            "partial": bool(failures),
            "source_status": source_status,
            "deleted_filter": deleted_filter,
        }

    def _find_alert(
        self, source: str, identifier: str, request_id: str
    ) -> dict[str, Any]:
        if source not in {"hybrid", "direct"} or HEX_ID_PATTERN.fullmatch(identifier) is None:
            raise WorkspaceError(
                404, "alert_not_found", "request", False, "Alert was not found."
            )
        for item in self._alert_rows(source, request_id):
            normalized = self._normalize_alert(item, source)
            if normalized.get("id") == identifier:
                return normalized
        raise WorkspaceError(
            404, "alert_not_found", "request", False, "Alert was not found."
        )

    def _alert_reference_summary(
        self, alert: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        asset_id = _selected_clip_id(alert.get("asset_uri"))
        references: dict[str, int] = {"reports": 0, "summaries": 0, "alerts": 0}
        if asset_id is None:
            return {"counts": references, "types": []}
        try:
            reports = self.reports(request_id).get("reports", [])
            references["reports"] = sum(
                any(
                    _selected_clip_id(item.get("asset_uri")) == asset_id
                    for item in report.get("evidence", [])
                    if isinstance(item, dict)
                )
                for report in reports
                if isinstance(report, dict)
            )
        except WorkspaceError:
            pass
        try:
            jobs = self.summary_jobs(request_id).get("jobs", [])
            references["summaries"] = sum(
                any(
                    _selected_clip_id(item.get("asset_uri")) == asset_id
                    for item in job.get("chunks", [])
                    if isinstance(item, dict)
                )
                for job in jobs
                if isinstance(job, dict)
            )
        except WorkspaceError:
            pass
        try:
            references["alerts"] = sum(
                _selected_clip_id(item.get("asset_uri")) == asset_id
                for item in self._alert_rows("hybrid", request_id)
            )
        except WorkspaceError:
            pass
        return {
            "counts": references,
            "types": [key for key, count in references.items() if count],
        }

    def delete_alert(
        self,
        source: str,
        identifier: str,
        payload: dict[str, Any],
        request_id: str,
    ) -> tuple[int, dict[str, Any]]:
        if set(payload).difference(
            {"schema_version", "store_id", "idempotency_key"}
        ):
            raise WorkspaceError(
                400,
                "unsupported_delete_field",
                "request",
                False,
                "Alert delete contains unsupported fields.",
            )
        _validate_identity(payload, "Alert delete")
        _validate_idempotency_key(payload)
        if not payload.get("idempotency_key"):
            raise WorkspaceError(
                400,
                "idempotency_key_required",
                "request",
                False,
                "Alert delete requires an idempotency key.",
            )
        alert = self._find_alert(source, identifier, request_id)
        key = self._tombstone_key(source, identifier)
        idempotency_key = str(payload["idempotency_key"])
        with self._governance_lock:
            records = self._alert_tombstones()
            existing = records.get(key)
            if existing is not None:
                return 200, {
                    **existing,
                    "status": "already_deleted",
                    "idempotent_replay": existing.get("idempotency_key")
                    == idempotency_key,
                }
            references = self._alert_reference_summary(alert, request_id)
            record = {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "source": source,
                "alert_id": identifier,
                "camera_id": alert.get("camera_id"),
                "event_type": alert.get("event_type"),
                "start_time": alert.get("start_time"),
                "deleted": True,
                "deleted_at": utc_now(),
                "idempotency_key": idempotency_key,
                "references": references,
                "evidence_retained": True,
                "restore_available": True,
            }
            records[key] = record
            self._write_alert_tombstones(records)
        return 200, {"status": "deleted", **record}

    def restore_alert(
        self,
        source: str,
        identifier: str,
        payload: dict[str, Any],
        request_id: str,
    ) -> tuple[int, dict[str, Any]]:
        if set(payload).difference(
            {"schema_version", "store_id", "idempotency_key"}
        ):
            raise WorkspaceError(
                400,
                "unsupported_restore_field",
                "request",
                False,
                "Alert restore contains unsupported fields.",
            )
        _validate_identity(payload, "Alert restore")
        _validate_idempotency_key(payload)
        if not payload.get("idempotency_key"):
            raise WorkspaceError(
                400,
                "idempotency_key_required",
                "request",
                False,
                "Alert restore requires an idempotency key.",
            )
        self._find_alert(source, identifier, request_id)
        key = self._tombstone_key(source, identifier)
        with self._governance_lock:
            records = self._alert_tombstones()
            existing = records.pop(key, None)
            if existing is None:
                return 200, {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": STORE_ID,
                    "source": source,
                    "alert_id": identifier,
                    "status": "already_active",
                    "idempotent_replay": True,
                }
            self._write_alert_tombstones(records)
        return 200, {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "source": source,
            "alert_id": identifier,
            "status": "restored",
            "restored_at": utc_now(),
            "evidence_retained": True,
        }

    def feedback(
        self,
        source: str,
        identifier: str,
        payload: dict[str, Any],
        request_id: str,
    ) -> tuple[int, dict[str, Any]]:
        if source not in {"hybrid", "direct"} or HEX_ID_PATTERN.fullmatch(identifier) is None:
            raise WorkspaceError(
                404, "alert_not_found", "request", False, "Alert was not found."
            )
        allowed = {
            "schema_version",
            "store_id",
            "alert_id",
            "feedback_label",
            "label",
            "note",
            "idempotency_key",
        }
        if set(payload).difference(allowed):
            raise WorkspaceError(
                400,
                "unsupported_feedback_field",
                "request",
                False,
                "Feedback contains unsupported fields.",
            )
        _validate_identity(payload, "Feedback")
        _validate_idempotency_key(payload)
        supplied_id = payload.get("alert_id")
        if supplied_id is not None and str(supplied_id) != identifier:
            raise WorkspaceError(
                400,
                "identity_mismatch",
                "request",
                False,
                "Feedback alert_id does not match the exact route target.",
            )
        raw_label = payload.get("feedback_label") or payload.get("label") or ""
        if not isinstance(raw_label, str):
            raise WorkspaceError(
                400,
                "invalid_feedback",
                "request",
                False,
                "feedback_label must be text.",
            )
        label = raw_label
        if (
            payload.get("feedback_label") is not None
            and payload.get("label") is not None
            and payload.get("feedback_label") != payload.get("label")
        ):
            raise WorkspaceError(
                400,
                "feedback_label_mismatch",
                "request",
                False,
                "Feedback labels do not match.",
            )
        if label not in {"confirmed", "rejected", "uncertain"}:
            raise WorkspaceError(
                400,
                "invalid_feedback",
                "request",
                False,
                "feedback_label is invalid.",
            )
        note_value = payload.get("note", "")
        if not isinstance(note_value, str):
            raise WorkspaceError(
                400,
                "invalid_feedback",
                "request",
                False,
                "Feedback note must be text.",
            )
        note = note_value
        if len(note) > 1000:
            raise WorkspaceError(
                400,
                "invalid_feedback",
                "request",
                False,
                "Feedback note is too long.",
            )
        service_id = (
            "alert-verification" if source == "hybrid" else "direct-rt-vlm"
        )
        status, value = self.client.json(
            service_id,
            "POST",
            f"/api/v1/alerts/{identifier}/feedback",
            payload={"feedback_label": label, "note": note},
            request_id=request_id,
            operation=f"{source}_alert_feedback",
            timeout=12,
        )
        if not isinstance(value, dict):
            raise WorkspaceError(
                502,
                "invalid_alert",
                service_id,
                True,
                "The alert service returned an invalid record.",
            )
        identifier_key = (
            "incident_id" if source == "hybrid" else "direct_alert_id"
        )
        if (
            value.get("schema_version") != SCHEMA_VERSION
            or value.get("store_id") != STORE_ID
            or value.get(identifier_key) != identifier
            or CAMERA_ID_PATTERN.fullmatch(str(value.get("camera_id", "")))
            is None
        ):
            raise WorkspaceError(
                502,
                "upstream_identity_mismatch",
                service_id,
                True,
                "The alert service returned a mismatched record.",
            )
        self._remember_media(value)
        return status, self._normalize_alert(value, source)

    def _refresh_media_allowlist(self, request_id: str) -> None:
        for source in ("hybrid",):
            try:
                self._alert_rows(source, request_id)
            except WorkspaceError:
                pass
        try:
            _, value = self.client.json(
                "summarization",
                "GET",
                "/api/v1/jobs",
                request_id=request_id,
                operation="summary_media_allowlist",
                timeout=12,
            )
            self._remember_media(value)
        except WorkspaceError:
            pass

    def open_media(self, identifier: str, request_id: str) -> BinaryResponse:
        if HEX_ID_PATTERN.fullmatch(identifier) is None:
            raise WorkspaceError(
                404, "media_not_found", "request", False, "Media was not found."
            )
        if not self._media_known(identifier):
            self._refresh_media_allowlist(request_id)
        if not self._media_known(identifier):
            raise WorkspaceError(
                404,
                "media_not_allowlisted",
                "selected-media",
                False,
                "The selected media ID is not present in an allowlisted workflow.",
            )
        opened = self.client.open_binary(
            "alert-verification",
            f"/media/{identifier}.mp4",
            request_id=request_id,
            operation="selected_media",
            timeout=15,
            require_length=True,
            accept="video/mp4",
        )
        if opened.content_type != "video/mp4":
            opened.response.close()
            raise WorkspaceError(
                502,
                "invalid_media_type",
                "alert-verification",
                True,
                "The selected-media service did not return MP4.",
            )
        return opened

    def uploads(
        self, query: dict[str, list[str]], request_id: str
    ) -> dict[str, Any]:
        if set(query).difference({"deleted"}):
            raise WorkspaceError(
                400, "unsupported_query_parameter", "request", False, "Upload query contains unsupported parameters."
            )
        deleted = _one(query, "deleted", "exclude")
        if deleted not in {"exclude", "include", "only"}:
            raise WorkspaceError(
                400, "invalid_parameter", "request", False, "deleted filter is invalid."
            )
        _, value = self.client.json(
            "media-intake",
            "GET",
            f"/api/v1/assets?deleted={deleted}",
            request_id=request_id,
            operation="uploaded_assets",
            timeout=8,
        )
        checked = self._require_identity(value, "media-intake")
        assets = checked.get("assets", [])
        if not isinstance(assets, list):
            raise WorkspaceError(
                502, "invalid_assets", "media-intake", True, "Media intake returned an invalid asset list."
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "assets": [
                item
                for item in assets
                if isinstance(item, dict)
                and item.get("store_id") == STORE_ID
                and HEX_ID_PATTERN.fullmatch(str(item.get("asset_id") or ""))
            ],
        }

    def upload(
        self,
        body: bytes,
        filename: str,
        content_type: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[int, dict[str, Any]]:
        if (
            not idempotency_key
            or len(idempotency_key) > 160
            or any(not (character.isalnum() or character in "-_.:") for character in idempotency_key)
        ):
            raise WorkspaceError(
                400, "invalid_idempotency_key", "request", False, "Upload requires a valid idempotency key."
            )
        if Path(filename).name != filename or len(filename) > 600:
            raise WorkspaceError(
                400, "invalid_filename", "request", False, "Upload filename is invalid."
            )
        status, value = self.client.upload(
            body,
            filename=filename,
            content_type=content_type,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
        checked = self._require_identity(value, "media-intake")
        if HEX_ID_PATTERN.fullmatch(str(checked.get("asset_id") or "")) is None:
            raise WorkspaceError(
                502, "invalid_asset", "media-intake", True, "Media intake returned an invalid asset."
            )
        return status, checked

    def mutate_upload(
        self,
        identifier: str,
        payload: dict[str, Any],
        request_id: str,
        *,
        restore: bool,
    ) -> tuple[int, dict[str, Any]]:
        if HEX_ID_PATTERN.fullmatch(identifier) is None:
            raise WorkspaceError(
                404, "asset_not_found", "request", False, "Uploaded asset was not found."
            )
        if set(payload).difference({"schema_version", "store_id", "idempotency_key"}):
            raise WorkspaceError(
                400, "unsupported_mutation_field", "request", False, "Upload mutation contains unsupported fields."
            )
        _validate_identity(payload, "Upload mutation")
        _validate_idempotency_key(payload)
        if not payload.get("idempotency_key"):
            raise WorkspaceError(
                400, "idempotency_key_required", "request", False, "Upload mutation requires an idempotency key."
            )
        if not restore:
            jobs = self.summary_jobs(request_id).get("jobs", [])
            references = [
                str(job.get("job_id"))
                for job in jobs
                if any(
                    UPLOADED_MEDIA_PATTERN.fullmatch(str(item.get("asset_uri") or ""))
                    and str(item.get("asset_uri")).startswith(f"uploaded-media://{identifier}.")
                    for item in job.get("chunks", [])
                    if isinstance(item, dict)
                )
            ]
            if references:
                raise WorkspaceError(
                    409,
                    "asset_reference_conflict",
                    "media-intake",
                    False,
                    f"Uploaded asset is referenced by {len(references)} summary job(s).",
                )
        method = "POST" if restore else "DELETE"
        suffix = "/restore" if restore else ""
        status, value = self.client.json(
            "media-intake",
            method,
            f"/api/v1/assets/{identifier}{suffix}",
            payload={} if restore else None,
            request_id=request_id,
            operation="uploaded_asset_restore" if restore else "uploaded_asset_delete",
            timeout=12,
        )
        return status, self._require_identity(value, "media-intake")

    def open_upload_media(
        self, identifier: str, request_id: str
    ) -> BinaryResponse:
        if HEX_ID_PATTERN.fullmatch(identifier) is None:
            raise WorkspaceError(
                404, "asset_not_found", "request", False, "Uploaded media was not found."
            )
        assets = self.uploads({"deleted": ["exclude"]}, request_id)["assets"]
        if not any(
            item.get("asset_id") == identifier and item.get("summary_ready") is True
            for item in assets
        ):
            raise WorkspaceError(
                404, "asset_media_not_allowlisted", "media-intake", False, "Uploaded media is unavailable."
            )
        return self.client.open_binary(
            "media-intake",
            f"/api/v1/assets/{identifier}/media",
            request_id=request_id,
            operation="uploaded_asset_media",
            timeout=15,
            require_length=True,
            accept="video/mp4",
        )

    def vlm_test_state(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "vlm-test",
            "GET",
            "/api/v1/state",
            request_id=request_id,
            operation="vlm_test_state",
            timeout=8,
        )
        return self._require_identity(value, "vlm-test")

    def vlm_test_jobs(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "vlm-test",
            "GET",
            "/api/v1/jobs",
            request_id=request_id,
            operation="vlm_test_jobs",
            timeout=8,
        )
        checked = self._require_identity(value, "vlm-test")
        jobs = checked.get("jobs", [])
        if not isinstance(jobs, list):
            raise WorkspaceError(502, "invalid_jobs", "vlm-test", True, "VLM-test returned an invalid job list.")
        return {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "jobs": jobs}

    def vlm_test_job(self, job_id: str, request_id: str) -> dict[str, Any]:
        if HEX_ID_PATTERN.fullmatch(job_id) is None:
            raise WorkspaceError(404, "not_found", "request", False, "VLM-test job was not found.")
        _, value = self.client.json(
            "vlm-test",
            "GET",
            f"/api/v1/jobs/{job_id}",
            request_id=request_id,
            operation="vlm_test_job",
            timeout=8,
        )
        return self._require_identity(value, "vlm-test")

    def vlm_test_store(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "vlm-test",
            "GET",
            "/api/v1/store",
            request_id=request_id,
            operation="vlm_test_store",
            timeout=8,
        )
        checked = self._require_identity(value, "vlm-test")
        assets = checked.get("assets", [])
        if not isinstance(assets, list):
            raise WorkspaceError(502, "invalid_store_assets", "vlm-test", True, "VLM-test returned an invalid Store list.")
        return {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "assets": assets}

    def vlm_test_candidates(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "vlm-test",
            "GET",
            "/api/v1/realtime/candidates",
            request_id=request_id,
            operation="vlm_test_realtime_candidates",
            timeout=12,
        )
        return self._require_identity(value, "vlm-test")

    def vlm_test_upload(
        self,
        body: bytes,
        filename: str,
        content_type: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[int, dict[str, Any]]:
        if not idempotency_key or len(idempotency_key) > 160 or any(
            not (character.isalnum() or character in "-_.:") for character in idempotency_key
        ):
            raise WorkspaceError(400, "invalid_idempotency_key", "request", False, "VLM-test upload requires a valid idempotency key.")
        if Path(filename).name != filename or len(filename) > 200:
            raise WorkspaceError(400, "invalid_filename", "request", False, "VLM-test upload filename is invalid.")
        status, value = self.client.upload_to(
            "vlm-test",
            "/api/v1/uploads",
            body,
            filename=filename,
            content_type=content_type,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
        checked = self._require_identity(value, "vlm-test")
        if HEX_ID_PATTERN.fullmatch(str(checked.get("job_id", ""))) is None:
            raise WorkspaceError(502, "invalid_vlm_test_job", "vlm-test", True, "VLM-test returned an invalid job.")
        return status, checked

    def vlm_test_action(
        self,
        path: str,
        payload: dict[str, Any],
        request_id: str,
        operation: str,
    ) -> tuple[int, dict[str, Any]]:
        status, value = self.client.json(
            "vlm-test",
            "POST",
            path,
            payload=payload,
            request_id=request_id,
            operation=operation,
            timeout=15,
        )
        return status, self._require_identity(value, "vlm-test")

    def open_vlm_test_media(
        self, identifier: str, request_id: str, *, store: bool
    ) -> BinaryResponse:
        if HEX_ID_PATTERN.fullmatch(identifier) is None:
            raise WorkspaceError(404, "media_not_found", "request", False, "VLM-test media was not found.")
        service_path = (
            f"/api/v1/store/{identifier}/media"
            if store
            else f"/api/v1/jobs/{identifier}/media"
        )
        return self.client.open_binary(
            "vlm-test",
            service_path,
            request_id=request_id,
            operation="vlm_test_store_media" if store else "vlm_test_staging_media",
            timeout=30,
            require_length=True,
            accept="video/mp4, video/x-matroska",
        )

    def search_state(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "search",
            "GET",
            "/api/v1/state",
            request_id=request_id,
            operation="search_state",
            timeout=18,
        )
        value = dict(self._require_identity(value, "search"))
        value["capabilities"] = {
            "routes": ["auto", "action", "attribute", "fusion", "image"],
            "camera_filter": True,
            "time_filter": "bff_postfilter",
            "similarity_threshold": "bff_postfilter",
            "source_type_filter": ["all", "selected_clip"],
            "critic_max_results": 3,
        }
        return value

    @staticmethod
    def _result_time(value: dict[str, Any], end: bool = False) -> datetime | None:
        names = (
            ("end_time", "frame_time", "@timestamp")
            if end
            else ("start_time", "frame_time", "@timestamp")
        )
        for name in names:
            raw = value.get(name)
            if not raw:
                continue
            try:
                return _utc(raw, f"result.{name}")
            except WorkspaceError:
                continue
        return None

    @staticmethod
    def _normalize_critic(
        value: Any, critic_status: str, critic_requested: bool
    ) -> dict[str, Any]:
        source = value if isinstance(value, dict) else {}
        raw_verdict = str(source.get("verdict", "")).lower()
        if raw_verdict in {"relevant", "confirmed", "accepted"}:
            verdict = "confirmed"
        elif raw_verdict in {"not_relevant", "rejected"}:
            verdict = "rejected"
        elif raw_verdict == "uncertain":
            reason = str(source.get("reason", "")).lower()
            verdict = (
                "critic_unavailable"
                if "unavailable" in reason
                else "unverified"
            )
        elif critic_requested and critic_status != "completed":
            verdict = "critic_unavailable"
        else:
            verdict = "unverified"
        confidence = source.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and (
            not math.isfinite(confidence) or not 0 <= confidence <= 1
        ):
            confidence = None
        return {
            "verdict": verdict,
            "confidence": confidence,
            "reason": str(source.get("reason", ""))[:2000],
            "available": verdict != "critic_unavailable",
        }

    def _normalize_search_result(
        self,
        value: dict[str, Any],
        route: str,
        critic_status: str,
        critic_requested: bool,
    ) -> dict[str, Any]:
        raw_asset_uri = str(value.get("asset_uri") or "")
        media_identifier = _selected_clip_id(raw_asset_uri)
        safe_asset_uri = (
            raw_asset_uri
            if media_identifier is not None
            or SELECTED_SNAPSHOT_PATTERN.fullmatch(raw_asset_uri)
            else None
        )
        start = value.get("start_time") or value.get("frame_time") or value.get("@timestamp")
        end = value.get("end_time") or value.get("frame_time") or value.get("@timestamp")
        start_time = self._result_time(value, False)
        end_time = self._result_time(value, True)
        try:
            score = float(value.get("fusion_score", value.get("score", 0)) or 0)
        except (TypeError, ValueError):
            score = 0.0
        if not math.isfinite(score):
            score = 0.0
        content_sha256 = str(
            value.get("asset_sha256") or value.get("clip_sha256") or ""
        )
        if HEX_ID_PATTERN.fullmatch(content_sha256) is None:
            content_sha256 = ""
        critic = self._normalize_critic(
            value.get("critic"), critic_status, critic_requested
        )
        return {
            "id": str(
                value.get("id")
                or value.get("embedding_id")
                or value.get("object_embedding_id")
                or ""
            ),
            "store_id": value.get("store_id"),
            "camera_id": value.get("camera_id"),
            "source_type": value.get("source_type", "selected_clip"),
            "asset_id": value.get("asset_id"),
            "asset_uri": safe_asset_uri,
            "asset_sha256": content_sha256 or None,
            "content_sha256": content_sha256 or None,
            "start_time": start,
            "end_time": end,
            "duration_seconds": (
                max(0.0, (end_time - start_time).total_seconds())
                if start_time is not None and end_time is not None
                else None
            ),
            "score": score,
            "route": value.get("search_channel") or route,
            "object_id": value.get("object_id"),
            "track_id": value.get("track_id"),
            "object_class": value.get("object_class"),
            "bbox": value.get("bbox"),
            "model_id": value.get("model_id"),
            "model_version": value.get("model_version"),
            "schema_version": value.get("schema_version"),
            "critic": critic,
            "critic_verdict": critic["verdict"],
            "criteria": (
                value.get("criteria")
                if isinstance(value.get("criteria"), list)
                else []
            ),
            "evidence": value.get("evidence"),
            "provenance": {
                "search_channel": value.get("search_channel"),
                "model_id": value.get("model_id"),
                "model_version": value.get("model_version"),
                "embedding_generation": value.get("embedding_generation"),
                "schema_version": value.get("schema_version"),
            },
            "media_available": media_identifier is not None,
            "media_url": (
                f"{WORKSPACE_PREFIX}/media/{media_identifier}.mp4"
                if media_identifier is not None
                else None
            ),
        }

    def search(
        self, payload: dict[str, Any], request_id: str
    ) -> tuple[int, dict[str, Any]]:
        allowed = {
            "schema_version",
            "store_id",
            "query",
            "mode",
            "route",
            "camera_ids",
            "from",
            "from_utc",
            "to",
            "to_utc",
            "top_k",
            "similarity_threshold",
            "threshold",
            "critic_verification",
            "critic_top_k",
            "source_type",
            "asset_uri",
            "bbox",
            "image_width",
            "image_height",
        }
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise WorkspaceError(
                400,
                "unsupported_search_field",
                "request",
                False,
                "Search request contains unsupported fields.",
            )
        _validate_identity(payload, "Search")
        route = str(payload.get("route") or "auto").lower()
        if route not in {"auto", "action", "attribute", "fusion", "image"}:
            raise WorkspaceError(
                400, "invalid_route", "request", False, "Search route is invalid."
            )
        mode = str(payload.get("mode") or "manual").lower()
        if mode not in {"manual", "agent"}:
            raise WorkspaceError(
                400, "invalid_mode", "request", False, "Search mode is invalid."
            )
        camera_ids = payload.get("camera_ids") or []
        if not isinstance(camera_ids, list) or len(camera_ids) > 10:
            raise WorkspaceError(
                400,
                "invalid_camera_filter",
                "request",
                False,
                "camera_ids must be a bounded list.",
            )
        checked_cameras = []
        for camera_id in camera_ids:
            checked = str(camera_id)
            self._camera(checked)
            checked_cameras.append(checked)
        top_k = _bounded_int(payload.get("top_k", 5), "top_k", 1, 50)
        source_type = str(payload.get("source_type") or "all")
        if source_type not in {"all", "selected_clip"}:
            raise WorkspaceError(
                409,
                "source_filter_unavailable",
                "search",
                False,
                "The search index does not distinguish uploaded files from camera-selected clips.",
            )
        from_text = str(payload.get("from_utc") or payload.get("from") or "")
        to_text = str(payload.get("to_utc") or payload.get("to") or "")
        lower = _utc(from_text, "from") if from_text else None
        upper = _utc(to_text, "to") if to_text else None
        if lower and upper and upper <= lower:
            raise WorkspaceError(
                400,
                "invalid_time_window",
                "request",
                False,
                "to must be after from.",
            )
        threshold_value = payload.get(
            "similarity_threshold", payload.get("threshold")
        )
        threshold = (
            _bounded_float(threshold_value, "similarity_threshold", 0.0, 1.0)
            if threshold_value is not None
            else None
        )
        postfiltering = (
            lower is not None
            or upper is not None
            or threshold is not None
            or source_type != "all"
        )
        upstream_top_k = min(50, max(top_k, top_k * 3 if postfiltering else top_k))
        upstream: dict[str, Any] = {
            "top_k": upstream_top_k,
            "camera_ids": checked_cameras,
        }
        critic_requested = False
        if route == "image":
            asset_uri = str(payload.get("asset_uri") or "")
            if SELECTED_SNAPSHOT_PATTERN.fullmatch(asset_uri) is None:
                raise WorkspaceError(
                    400,
                    "invalid_snapshot",
                    "request",
                    False,
                    "Image search requires a safe selected-snapshot asset.",
                )
            upstream["asset_uri"] = asset_uri
            if "bbox" in payload:
                bbox = payload["bbox"]
                if not isinstance(bbox, list) or len(bbox) != 4:
                    raise WorkspaceError(
                        400,
                        "invalid_bbox",
                        "request",
                        False,
                        "bbox must contain four normalized values.",
                    )
                upstream["bbox"] = [
                    _bounded_float(item, "bbox", 0.0, 1.0) for item in bbox
                ]
                x, y, width, height = upstream["bbox"]
                if x + width > 1 or y + height > 1:
                    raise WorkspaceError(
                        400,
                        "invalid_bbox",
                        "request",
                        False,
                        "bbox must stay within normalized image bounds.",
                    )
                upstream["image_width"] = _bounded_int(
                    payload.get("image_width"), "image_width", 1, 16384
                )
                upstream["image_height"] = _bounded_int(
                    payload.get("image_height"), "image_height", 1, 16384
                )
            path = "/api/v1/search/image"
        else:
            query = str(payload.get("query") or "").strip()
            if not query or len(query) > 2000:
                raise WorkspaceError(
                    400,
                    "invalid_query",
                    "request",
                    False,
                    "A non-empty search query is required.",
                )
            upstream["query"] = query
            if route != "auto":
                upstream["route"] = route
            critic_flag = payload.get("critic_verification")
            if critic_flag is not None and not isinstance(critic_flag, bool):
                raise WorkspaceError(
                    400,
                    "invalid_critic_toggle",
                    "request",
                    False,
                    "critic_verification must be a boolean.",
                )
            requested_critic_top_k = _bounded_int(
                payload.get(
                    "critic_top_k",
                    min(top_k, 3) if critic_flag is True else 0,
                ),
                "critic_top_k",
                0,
                3,
            )
            critic_enabled = critic_flag is True or (
                critic_flag is None and requested_critic_top_k > 0
            )
            critic_top_k = (
                requested_critic_top_k
                if critic_enabled
                else 0
            )
            critic_requested = critic_enabled and critic_top_k > 0
            upstream["critic_top_k"] = critic_top_k
            path = "/api/v1/search"
        try:
            status, value = self.client.json(
                "search",
                "POST",
                path,
                payload=upstream,
                request_id=request_id,
                operation="image_search" if route == "image" else "video_search",
                timeout=330 if route in {"action", "fusion", "auto"} else 210,
            )
        except WorkspaceError as error:
            if error.code != "provider_standby":
                raise
            required_profile = (
                "search_assistant"
                if route == "auto"
                else "object_index"
                if route in {"attribute", "image"}
                else "video_index"
            )
            raise WorkspaceError(
                503,
                "provider_standby",
                "search",
                True,
                "Search capability is standby and requires explicit GPU admission.",
                {
                    "capability": f"{route} video search",
                    "required_profile": required_profile,
                    "queued": False,
                    "operator_action": {
                        "type": "request_gpu_profile",
                        "profile_id": required_profile,
                        "requires_confirmation": True,
                        "endpoint": "/api/v1/gpu-control/commands",
                    },
                },
            ) from error
        if not isinstance(value, dict) or not isinstance(value.get("results"), list):
            raise WorkspaceError(
                502,
                "invalid_search_response",
                "search",
                True,
                "Search returned an invalid response.",
            )
        self._require_identity(value, "search")
        raw_results = [item for item in value["results"] if isinstance(item, dict)]
        known_cameras = {
            str(camera.get("camera_id"))
            for camera in self._camera_registry().get("cameras", [])
            if isinstance(camera, dict)
        }
        filtered: list[dict[str, Any]] = []
        for result in raw_results:
            if (
                result.get("schema_version") != SCHEMA_VERSION
                or result.get("store_id") != STORE_ID
                or str(result.get("camera_id", "")) not in known_cameras
            ):
                continue
            if source_type == "selected_clip" and result.get("source_type") != "selected_clip":
                continue
            start = self._result_time(result, False)
            end = self._result_time(result, True) or start
            if lower and (end is None or end < lower):
                continue
            if upper and (start is None or start >= upper):
                continue
            try:
                score = float(
                    result.get("fusion_score", result.get("score", 0)) or 0
                )
            except (TypeError, ValueError):
                continue
            if not math.isfinite(score):
                continue
            if threshold is not None and score < threshold:
                continue
            filtered.append(result)
        filtered = filtered[:top_k]
        self._remember_media(filtered)
        resolved_route = str(value.get("route") or route)
        critic_status = str(value.get("critic_status", "unavailable"))
        degraded_channels = (
            value.get("degraded_channels")
            if isinstance(value.get("degraded_channels"), list)
            else []
        )
        provider_sources = (
            value.get("provider_sources")
            if isinstance(value.get("provider_sources"), dict)
            else {}
        )
        if value.get("provider_source") is not None:
            provider_sources = {
                **provider_sources,
                "image": str(value.get("provider_source"))[:80],
            }
        normalized = [
            self._normalize_search_result(
                item, resolved_route, critic_status, critic_requested
            )
            for item in filtered
        ]
        verdict_order = {
            "confirmed": 0,
            "unverified": 1,
            "critic_unavailable": 1,
            "rejected": 2,
        }
        normalized.sort(
            key=lambda item: (
                verdict_order.get(
                    str(item.get("critic_verdict", "unverified")), 1
                ),
                -float(item.get("score", 0) or 0),
            )
        )
        critic_partial = any(
            item.get("critic_verdict") == "critic_unavailable"
            for item in normalized
        )
        return status, {
            "schema_version": value.get("schema_version", SCHEMA_VERSION),
            "store_id": value.get("store_id", STORE_ID),
            "query": value.get("query") or payload.get("query"),
            "mode": mode,
            "route": resolved_route,
            "status": (
                "partial"
                if degraded_channels
                or (critic_requested and critic_status != "completed")
                or critic_partial
                else "completed"
            ),
            "processing_steps": [
                {
                    "id": "decompose",
                    "label": "Phân tích truy vấn",
                    "status": (
                        "completed"
                        if mode == "agent" or route == "auto"
                        else "skipped"
                    ),
                },
                {
                    "id": "search",
                    "label": "Fusion search" if resolved_route == "fusion" else "Video search",
                    "status": "completed",
                },
                {
                    "id": "verify",
                    "label": "Xác minh evidence",
                    "status": (
                        "partial"
                        if critic_partial
                        else "completed"
                        if critic_status == "completed"
                        else "unavailable"
                        if critic_requested
                        else "skipped"
                    ),
                },
            ],
            "provider_sources": provider_sources,
            "degraded_channels": degraded_channels,
            "critic_status": critic_status,
            "filters": {
                "camera_ids": checked_cameras,
                "from_utc": from_text or None,
                "to_utc": to_text or None,
                "similarity_threshold": threshold,
                "source_type": source_type,
            },
            "postfilter_applied": postfiltering,
            "upstream_result_count": len(raw_results),
            "result_count": len(normalized),
            "results": normalized,
            "searched_at": value.get("searched_at", utc_now()),
        }

    @staticmethod
    def _job(value: dict[str, Any]) -> dict[str, Any]:
        result = dict(value)
        chunks = value.get("chunks", [])
        if not isinstance(chunks, list):
            chunks = []
        completed = sum(
            isinstance(chunk, dict) and chunk.get("caption_status") == "completed"
            for chunk in chunks
        )
        result["progress"] = {
            "completed_chunks": completed,
            "total_chunks": len(chunks),
            "percent": round(100 * completed / len(chunks), 1) if chunks else 0,
        }
        return result

    def summary_state(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "summarization",
            "GET",
            "/api/v1/state",
            request_id=request_id,
            operation="summary_state",
            timeout=18,
        )
        value = dict(self._require_identity(value, "summarization"))
        value["capabilities"] = {
            "selected_video": True,
            "camera_time_window": False,
            "time_window_selected_media_jobs": True,
            "camera_archive_selection": False,
            "image": False,
            "general_live_stream": False,
            "grounded_qa": True,
            "reports": ["incident", "shift", "daily"],
        }
        return value

    def summary_jobs(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "summarization",
            "GET",
            "/api/v1/jobs",
            request_id=request_id,
            operation="summary_jobs",
            timeout=15,
        )
        jobs = value.get("jobs", []) if isinstance(value, dict) else []
        if not isinstance(jobs, list):
            raise WorkspaceError(
                502,
                "invalid_jobs",
                "summarization",
                True,
                "Summarization returned an invalid job list.",
            )
        jobs = [
            self._job(item)
            for item in jobs
            if isinstance(item, dict)
            and item.get("schema_version") == SCHEMA_VERSION
            and item.get("store_id") == STORE_ID
            and CAMERA_ID_PATTERN.fullmatch(str(item.get("camera_id", "")))
            and HEX_ID_PATTERN.fullmatch(str(item.get("job_id", "")))
        ]
        jobs.sort(
            key=lambda item: (str(item.get("created_at", "")), str(item.get("job_id", ""))),
            reverse=True,
        )
        self._remember_media(jobs)
        return {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "jobs": jobs}

    @staticmethod
    def _job_asset_ids(job: dict[str, Any]) -> set[str]:
        identifiers: set[str] = set()
        for chunk in job.get("chunks", []):
            if not isinstance(chunk, dict):
                continue
            identifier = _selected_clip_id(chunk.get("asset_uri"))
            if identifier is not None:
                identifiers.add(identifier)
        return identifiers

    @staticmethod
    def _required_summary_profile(status: str) -> str | None:
        if status in {"queued_caption", "failed"}:
            return "summary_caption"
        if status == "queued_summary":
            return "summary_reasoning"
        return None

    def _resolve_alert_media(
        self,
        alert_id: str,
        source: str | None,
        request_id: str,
    ) -> tuple[str, dict[str, Any]]:
        if HEX_ID_PATTERN.fullmatch(alert_id) is None:
            raise WorkspaceError(
                404, "alert_not_found", "request", False, "Alert was not found."
            )
        if source is not None and source not in {"hybrid", "direct"}:
            raise WorkspaceError(
                400,
                "invalid_alert_source",
                "request",
                False,
                "Alert source must be hybrid or direct.",
            )
        selected_sources = [source] if source else ["hybrid", "direct"]
        for selected in selected_sources:
            for alert in self._alert_rows(str(selected), request_id):
                identifier_key = (
                    "incident_id" if selected == "hybrid" else "direct_alert_id"
                )
                if alert.get(identifier_key) != alert_id:
                    continue
                asset_id = _selected_clip_id(alert.get("asset_uri"))
                if asset_id is None and isinstance(alert.get("evidence"), dict):
                    asset_id = _selected_clip_id(alert["evidence"].get("reference"))
                if asset_id is None:
                    raise WorkspaceError(
                        409,
                        "alert_media_unavailable",
                        str(selected),
                        False,
                        "Alert này chưa có selected clip được backend xác nhận.",
                    )
                return asset_id, alert
        raise WorkspaceError(
            404, "alert_not_found", "request", False, "Alert was not found."
        )

    def evidence_assistant(
        self, payload: dict[str, Any], request_id: str
    ) -> tuple[int, dict[str, Any]]:
        """Resolve exact evidence before Q&A; this path never invokes search."""
        allowed = {
            "schema_version",
            "store_id",
            "question",
            "context",
            "idempotency_key",
        }
        if set(payload).difference(allowed):
            raise WorkspaceError(
                400,
                "unsupported_assistant_field",
                "request",
                False,
                "Evidence Assistant request contains unsupported fields.",
            )
        _validate_identity(payload, "Evidence Assistant")
        _validate_idempotency_key(payload)
        question = str(payload.get("question") or "").strip()
        if not question or len(question) > 4000:
            raise WorkspaceError(
                400,
                "invalid_question",
                "request",
                False,
                "Evidence Assistant requires a bounded question.",
            )
        context = payload.get("context")
        if not isinstance(context, dict):
            raise WorkspaceError(
                400,
                "exact_context_required",
                "request",
                False,
                "Evidence Assistant requires one exact clip, alert or summary context.",
            )
        context_allowed = {
            "type",
            "asset_id",
            "alert_id",
            "alert_source",
            "summary_id",
            "camera_id",
            "start_time",
            "end_time",
        }
        if set(context).difference(context_allowed):
            raise WorkspaceError(
                400,
                "unsupported_context_field",
                "request",
                False,
                "Evidence context contains unsupported fields.",
            )
        context_type = str(context.get("type") or "")
        if context_type == "summary":
            summary_id = str(context.get("summary_id") or "")
            job = self.summary_job(summary_id, request_id)
            if job.get("status") != "completed":
                required_profile = self._required_summary_profile(
                    str(job.get("status") or "")
                )
                return 200, self._assistant_preparation(job, required_profile, False)
            try:
                status, answer = self.summary_qa(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "store_id": STORE_ID,
                        "summary_id": summary_id,
                        "question": question,
                        "idempotency_key": payload.get("idempotency_key"),
                    },
                    request_id,
                )
            except WorkspaceError as error:
                if error.code != "provider_standby":
                    raise
                return 200, self._assistant_provider_standby(
                    "Grounded Q&A", "summary_reasoning", job
                )
            return status, {
                **answer,
                "workflow": "grounded_qa",
                "summary_id": summary_id,
                "scope": {
                    "store_id": STORE_ID,
                    "camera_id": job.get("camera_id"),
                    "start_time": job.get("window_start"),
                    "end_time": job.get("window_end"),
                    "asset_ids": sorted(self._job_asset_ids(job)),
                },
            }
        if context_type not in {"clip", "alert", "search_result"}:
            raise WorkspaceError(
                400,
                "exact_context_required",
                "request",
                False,
                "Evidence context must be an exact clip, alert or completed summary.",
            )

        authoritative: dict[str, Any] | None = None
        if context_type == "alert":
            asset_id, authoritative = self._resolve_alert_media(
                str(context.get("alert_id") or ""),
                (
                    str(context.get("alert_source"))
                    if context.get("alert_source") is not None
                    else None
                ),
                request_id,
            )
            supplied_asset = str(context.get("asset_id") or "")
            if supplied_asset and supplied_asset != asset_id:
                raise WorkspaceError(
                    409,
                    "evidence_identity_mismatch",
                    "selected-media",
                    False,
                    "Attached alert and selected clip do not match.",
                )
        else:
            asset_id = str(context.get("asset_id") or "")
            if HEX_ID_PATTERN.fullmatch(asset_id) is None:
                raise WorkspaceError(
                    400,
                    "invalid_asset",
                    "request",
                    False,
                    "An exact selected-clip asset ID is required.",
                )

        if not self._media_known(asset_id):
            self._refresh_media_allowlist(request_id)
        record = self._media_record(asset_id)
        if record is None or record.get("conflict"):
            raise WorkspaceError(
                409 if record else 404,
                "media_provenance_mismatch" if record else "media_not_allowlisted",
                "selected-media",
                False,
                "Selected clip provenance is missing or conflicts with an allowlisted workflow.",
            )
        expected_camera = str(
            (authoritative or {}).get("camera_id") or context.get("camera_id") or ""
        )
        expected_start = (
            (authoritative or {}).get("clip_start_time")
            or (authoritative or {}).get("start_time")
            or context.get("start_time")
        )
        expected_end = (
            (authoritative or {}).get("clip_end_time")
            or (authoritative or {}).get("end_time")
            or context.get("end_time")
        )
        canonical_start = _utc(expected_start, "context.start_time").isoformat()
        canonical_end = _utc(expected_end, "context.end_time").isoformat()
        if (
            CAMERA_ID_PATTERN.fullmatch(expected_camera) is None
            or canonical_end <= canonical_start
            or record.get("camera_id") != expected_camera
            or record.get("start_time") != canonical_start
            or record.get("end_time") != canonical_end
            or HEX_ID_PATTERN.fullmatch(str(record.get("content_sha256") or "")) is None
        ):
            raise WorkspaceError(
                409,
                "media_provenance_mismatch",
                "selected-media",
                False,
                "Attached asset, camera, UTC range or digest does not match authoritative provenance.",
            )

        jobs_value = self.summary_jobs(request_id)
        exact_jobs = [
            job
            for job in jobs_value["jobs"]
            if self._job_asset_ids(job) == {asset_id}
            and job.get("camera_id") == expected_camera
            and _utc(job.get("window_start"), "job.window_start").isoformat()
            == canonical_start
            and _utc(job.get("window_end"), "job.window_end").isoformat()
            == canonical_end
        ]
        exact_jobs.sort(
            key=lambda item: (
                item.get("status") == "completed",
                str(item.get("updated_at") or item.get("created_at") or ""),
            ),
            reverse=True,
        )
        if exact_jobs:
            job = exact_jobs[0]
        else:
            status, job = self.create_summary_job(
                {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": STORE_ID,
                    "camera_id": expected_camera,
                    "source_type": "selected_video",
                    "window_start": str(expected_start),
                    "window_end": str(expected_end),
                    "assets": [
                        {
                            "asset_uri": f"selected-clip://{asset_id}.mp4",
                            "asset_sha256": record["content_sha256"],
                            "start_time": str(expected_start),
                            "end_time": str(expected_end),
                        }
                    ],
                    "idempotency_key": payload.get("idempotency_key")
                    or f"evidence-assistant:{asset_id}",
                    "title": (
                        f"Evidence Assistant · {str((authoritative or {}).get('event_type') or asset_id)[:120]}"
                    ),
                },
                request_id,
            )
            return status, self._assistant_preparation(
                job, "summary_caption", True
            )

        if job.get("status") != "completed":
            return 200, self._assistant_preparation(
                job,
                self._required_summary_profile(str(job.get("status") or "")),
                False,
            )
        try:
            status, answer = self.summary_qa(
                {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": STORE_ID,
                    "summary_id": job["job_id"],
                    "question": question,
                    "idempotency_key": payload.get("idempotency_key"),
                },
                request_id,
            )
        except WorkspaceError as error:
            if error.code != "provider_standby":
                raise
            return 200, self._assistant_provider_standby(
                "Grounded Q&A", "summary_reasoning", job
            )
        return status, {
            **answer,
            "workflow": "grounded_qa",
            "summary_id": job["job_id"],
            "scope": {
                "store_id": STORE_ID,
                "camera_id": expected_camera,
                "start_time": str(expected_start),
                "end_time": str(expected_end),
                "asset_ids": [asset_id],
            },
        }

    @staticmethod
    def _assistant_preparation(
        job: dict[str, Any], required_profile: str | None, created: bool
    ) -> dict[str, Any]:
        status = str(job.get("status") or "queued_caption")
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "workflow": "evidence_preparation",
            "status": status,
            "queued": status.startswith("queued"),
            "created": created,
            "answered": False,
            "summary_id": job.get("job_id"),
            "required_profile": required_profile,
            "capability": (
                "Caption selected clip"
                if required_profile == "summary_caption"
                else "Tổng hợp summary evidence"
                if required_profile == "summary_reasoning"
                else "Evidence preparation"
            ),
            "operator_action": (
                {
                    "type": "request_gpu_profile",
                    "profile_id": required_profile,
                    "requires_confirmation": True,
                    "endpoint": "/api/v1/gpu-control/commands",
                }
                if required_profile
                else {"type": "wait_for_job"}
            ),
            "job": WorkspaceAdapter._job(job),
            "scope": {
                "store_id": STORE_ID,
                "camera_id": job.get("camera_id"),
                "start_time": job.get("window_start"),
                "end_time": job.get("window_end"),
                "asset_ids": sorted(WorkspaceAdapter._job_asset_ids(job)),
            },
        }

    @staticmethod
    def _assistant_provider_standby(
        capability: str, required_profile: str, job: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            **WorkspaceAdapter._assistant_preparation(
                job, required_profile, False
            ),
            "workflow": "provider_standby",
            "status": "provider_standby",
            "queued": False,
            "capability": capability,
        }

    def summary_job(self, job_id: str, request_id: str) -> dict[str, Any]:
        if HEX_ID_PATTERN.fullmatch(job_id) is None:
            raise WorkspaceError(
                404, "job_not_found", "request", False, "Summary job was not found."
            )
        _, value = self.client.json(
            "summarization",
            "GET",
            f"/api/v1/jobs/{job_id}",
            request_id=request_id,
            operation="summary_job",
            timeout=10,
        )
        if not isinstance(value, dict):
            raise WorkspaceError(
                502,
                "invalid_job",
                "summarization",
                True,
                "Summarization returned an invalid job.",
            )
        self._require_identity(value, "summarization")
        if (
            value.get("job_id") != job_id
            or CAMERA_ID_PATTERN.fullmatch(str(value.get("camera_id", ""))) is None
        ):
            raise WorkspaceError(
                502,
                "upstream_identity_mismatch",
                "summarization",
                True,
                "Summarization returned a mismatched job.",
            )
        self._remember_media(value)
        return self._job(value)

    def create_summary_job(
        self, payload: dict[str, Any], request_id: str
    ) -> tuple[int, dict[str, Any]]:
        allowed = {
            "schema_version",
            "store_id",
            "camera_id",
            "source_type",
            "window_start",
            "window_end",
            "assets",
            "idempotency_key",
            "title",
            "priority",
        }
        if set(payload).difference(allowed):
            raise WorkspaceError(
                400,
                "unsupported_summary_field",
                "request",
                False,
                "Summary request contains unsupported fields.",
            )
        value = dict(payload)
        value.setdefault("schema_version", SCHEMA_VERSION)
        value.setdefault("store_id", STORE_ID)
        if value.get("schema_version") != SCHEMA_VERSION or value.get("store_id") != STORE_ID:
            raise WorkspaceError(
                400,
                "identity_mismatch",
                "request",
                False,
                "Summary identity fields must target store-001.",
            )
        camera_id = str(value.get("camera_id") or "")
        self._camera(camera_id)
        if value.get("source_type") not in {"selected_video", "time_window"}:
            raise WorkspaceError(
                400,
                "invalid_source_type",
                "request",
                False,
                "Summary source_type is invalid.",
            )
        title = value.get("title")
        if title is not None and (
            not isinstance(title, str) or len(title.strip()) > 200
        ):
            raise WorkspaceError(
                400,
                "invalid_title",
                "request",
                False,
                "Summary title is invalid.",
            )
        if "priority" in value:
            value["priority"] = _bounded_int(
                value["priority"], "priority", 0, 100
            )
        _validate_idempotency_key(value)
        start = _utc(value.get("window_start"), "window_start")
        end = _utc(value.get("window_end"), "window_end")
        if end <= start:
            raise WorkspaceError(
                400,
                "invalid_time_window",
                "request",
                False,
                "window_end must be after window_start.",
            )
        assets = value.get("assets")
        if not isinstance(assets, list) or not 1 <= len(assets) <= 100:
            raise WorkspaceError(
                400,
                "invalid_assets",
                "request",
                False,
                "Summary jobs require a bounded selected-media list.",
            )
        if value.get("source_type") == "selected_video" and len(assets) != 1:
            raise WorkspaceError(
                400,
                "invalid_assets",
                "request",
                False,
                "Selected-video summaries require exactly one selected clip.",
            )
        for asset in assets:
            if not isinstance(asset, dict):
                raise WorkspaceError(
                    400,
                    "invalid_assets",
                    "request",
                    False,
                    "Each selected asset must be an object.",
                )
            if set(asset).difference(
                {"asset_uri", "asset_sha256", "start_time", "end_time"}
            ):
                raise WorkspaceError(
                    400,
                    "unsupported_asset_field",
                    "request",
                    False,
                    "Selected asset contains unsupported fields.",
                )
            asset_uri = str(asset.get("asset_uri") or "")
            identifier = _selected_clip_id(asset_uri)
            uploaded_match = UPLOADED_MEDIA_PATTERN.fullmatch(asset_uri)
            uploaded_identifier = uploaded_match.group(1) if uploaded_match else None
            if identifier is None and uploaded_identifier is None:
                raise WorkspaceError(
                    400,
                    "invalid_asset",
                    "request",
                    False,
                    "Only exact prepared selected-clip or uploaded-media assets are accepted.",
                )
            if uploaded_identifier is not None:
                record = next(
                    (
                        item
                        for item in self.uploads(
                            {"deleted": ["exclude"]}, request_id
                        )["assets"]
                        if item.get("asset_id") == uploaded_identifier
                        and item.get("summary_ready") is True
                    ),
                    None,
                )
            else:
                if not self._media_known(identifier):
                    self._refresh_media_allowlist(request_id)
                record = self._media_record(identifier)
            if record is None:
                raise WorkspaceError(
                    404, "media_not_allowlisted", "selected-media", False, "A selected asset is not present in an allowlisted workflow."
                )
            asset_start = _utc(asset.get("start_time"), "asset.start_time")
            asset_end = _utc(asset.get("end_time"), "asset.end_time")
            if asset_end <= asset_start or asset_start < start or asset_end > end:
                raise WorkspaceError(
                    400,
                    "invalid_asset_window",
                    "request",
                    False,
                    "Selected asset bounds must be within the summary window.",
                )
            digest = asset.get("asset_sha256")
            if (
                not isinstance(digest, str)
                or HEX_ID_PATTERN.fullmatch(digest) is None
            ):
                raise WorkspaceError(
                    400,
                    "invalid_digest",
                    "request",
                    False,
                    "A verified asset_sha256 is required.",
                )
            expected = {"content_sha256": digest}
            if uploaded_identifier is None:
                expected.update(
                    {
                        "camera_id": camera_id,
                        "start_time": asset_start.isoformat(),
                        "end_time": asset_end.isoformat(),
                    }
                )
            if record.get("conflict") or any(
                record.get(field) is None or record.get(field) != expected[field]
                for field in expected
            ):
                raise WorkspaceError(
                    409,
                    "media_provenance_mismatch",
                    "selected-media",
                    False,
                    "Selected media identity, UTC bounds or content digest do not match authoritative provenance.",
                )
        status, created = self.client.json(
            "summarization",
            "POST",
            "/api/v1/summaries",
            payload=value,
            request_id=request_id,
            operation="summary_job_create",
            timeout=30,
        )
        if not isinstance(created, dict):
            raise WorkspaceError(
                502,
                "invalid_job",
                "summarization",
                True,
                "Summarization returned an invalid job.",
            )
        self._require_identity(created, "summarization", camera_id)
        if HEX_ID_PATTERN.fullmatch(str(created.get("job_id", ""))) is None:
            raise WorkspaceError(
                502,
                "invalid_job",
                "summarization",
                True,
                "Summarization returned an invalid job ID.",
            )
        self._remember_media(created)
        return status, self._job(created)

    def summary_action(
        self, job_id: str, action: str, request_id: str
    ) -> tuple[int, dict[str, Any]]:
        if HEX_ID_PATTERN.fullmatch(job_id) is None or action not in {
            "caption",
            "summarize",
            "retry",
        }:
            raise WorkspaceError(
                404, "action_not_found", "request", False, "Summary action was not found."
            )
        timeout = 330 if action == "caption" else 210 if action == "summarize" else 15
        try:
            status, value = self.client.json(
                "summarization",
                "POST",
                f"/api/v1/jobs/{job_id}/{action}",
                payload={},
                request_id=request_id,
                operation=f"summary_{action}",
                timeout=timeout,
            )
        except WorkspaceError as error:
            # A queued job is durable work. If the fixed provider is still
            # warming up, keep the job queued and let the CPU service consume
            # it once the explicitly admitted provider becomes ready.
            if action in {"caption", "summarize"} and error.code == "provider_standby":
                job = self.summary_job(job_id, request_id)
                required_profile = self._required_summary_profile(
                    str(job.get("status") or "")
                )
                return 202, {
                    **job,
                    "workflow": "waiting_for_provider",
                    "execution": "queued",
                    "required_profile": required_profile,
                    "provider_status": "standby",
                    "message": "Job đã được giữ trong queue; provider GPU đang khởi động.",
                }
            raise
        if not isinstance(value, dict):
            raise WorkspaceError(
                502,
                "invalid_job",
                "summarization",
                True,
                "Summarization returned an invalid job.",
            )
        self._require_identity(value, "summarization")
        if value.get("job_id") != job_id:
            raise WorkspaceError(
                502,
                "upstream_identity_mismatch",
                "summarization",
                True,
                "Summarization returned a mismatched job.",
            )
        self._remember_media(value)
        return status, self._job(value)

    def summary_qa(
        self, payload: dict[str, Any], request_id: str
    ) -> tuple[int, dict[str, Any]]:
        if set(payload).difference(
            {
                "schema_version",
                "store_id",
                "summary_id",
                "question",
                "idempotency_key",
            }
        ):
            raise WorkspaceError(
                400,
                "unsupported_question_field",
                "request",
                False,
                "Q&A request contains unsupported fields.",
            )
        _validate_identity(payload, "Q&A")
        _validate_idempotency_key(payload)
        summary_id = str(payload.get("summary_id") or "")
        question = str(payload.get("question") or "").strip()
        if HEX_ID_PATTERN.fullmatch(summary_id) is None or not question or len(question) > 4000:
            raise WorkspaceError(
                400,
                "invalid_question",
                "request",
                False,
                "A valid summary_id and bounded question are required.",
            )
        status, value = self.client.json(
            "summarization",
            "POST",
            "/api/v1/qa",
            payload={"summary_id": summary_id, "question": question},
            request_id=request_id,
            operation="summary_qa",
            timeout=210,
        )
        if not isinstance(value, dict):
            raise WorkspaceError(
                502,
                "invalid_answer",
                "summarization",
                True,
                "Summarization returned an invalid answer.",
            )
        self._require_identity(value, "summarization")
        self._remember_media(value)
        return status, value

    @staticmethod
    def _report(value: dict[str, Any]) -> dict[str, Any]:
        upstream_downloads = value.get("downloads")
        if isinstance(upstream_downloads, dict):
            json_available = upstream_downloads.get("json") is not None
            markdown_available = upstream_downloads.get("markdown") is not None
        else:
            json_available = bool(value.get("json_path"))
            markdown_available = bool(value.get("markdown_path"))
        result = {
            key: nested
            for key, nested in value.items()
            if key not in {"json_path", "markdown_path", "downloads"}
        }
        report_id = str(value.get("report_id", ""))
        if HEX_ID_PATTERN.fullmatch(report_id):
            result["downloads"] = {
                "json": (
                    {
                        "href": f"{WORKSPACE_PREFIX}/reports/{report_id}.json",
                        "content_type": "application/json",
                    }
                    if json_available
                    else None
                ),
                "markdown": (
                    {
                        "href": f"{WORKSPACE_PREFIX}/reports/{report_id}.md",
                        "content_type": "text/markdown",
                    }
                    if markdown_available
                    else None
                ),
            }
        return result

    def reports(self, request_id: str) -> dict[str, Any]:
        _, value = self.client.json(
            "summarization",
            "GET",
            "/api/v1/reports",
            request_id=request_id,
            operation="reports_list",
            timeout=12,
        )
        reports = value.get("reports", []) if isinstance(value, dict) else []
        self._require_identity(value, "summarization")
        if not isinstance(reports, list):
            raise WorkspaceError(
                502,
                "invalid_reports",
                "summarization",
                True,
                "Summarization returned an invalid report list.",
            )
        self._remember_media(reports)
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "reports": [
                self._report(item)
                for item in reports
                if isinstance(item, dict)
                and item.get("schema_version") == SCHEMA_VERSION
                and item.get("store_id") == STORE_ID
                and HEX_ID_PATTERN.fullmatch(str(item.get("report_id", "")))
            ],
        }

    def open_report_media(
        self, report_id: str, identifier: str, request_id: str
    ) -> BinaryResponse:
        if (
            HEX_ID_PATTERN.fullmatch(report_id) is None
            or HEX_ID_PATTERN.fullmatch(identifier) is None
        ):
            raise WorkspaceError(
                404, "report_media_not_found", "request", False, "Report evidence was not found."
            )
        report = next(
            (
                item
                for item in self.reports(request_id).get("reports", [])
                if item.get("report_id") == report_id
            ),
            None,
        )
        if report is None or report.get("store_id") != STORE_ID:
            raise WorkspaceError(
                404, "report_not_found", "summarization", False, "Report was not found."
            )
        allowed = {
            _selected_clip_id(item.get("asset_uri"))
            for item in report.get("evidence", [])
            if isinstance(item, dict)
        }
        if identifier not in allowed:
            raise WorkspaceError(
                403,
                "report_media_scope_denied",
                "selected-media",
                False,
                "Selected media is outside the requested report evidence scope.",
            )
        return self.open_media(identifier, request_id)

    def create_report(
        self, report_type: str, payload: dict[str, Any], request_id: str
    ) -> tuple[int, dict[str, Any]]:
        if report_type not in {"incident", "shift", "daily"}:
            raise WorkspaceError(
                404, "report_type_not_found", "request", False, "Report type was not found."
            )
        envelope = {"schema_version", "store_id", "idempotency_key"}
        allowed = (
            {"summary_ids", "incident_id"} | envelope
            if report_type == "incident"
            else {"summary_ids"} | envelope
        )
        if set(payload).difference(allowed):
            raise WorkspaceError(
                400,
                "unsupported_report_field",
                "request",
                False,
                "Report request contains unsupported fields.",
            )
        _validate_identity(payload, "Report")
        _validate_idempotency_key(payload)
        summary_ids = payload.get("summary_ids")
        if (
            not isinstance(summary_ids, list)
            or not 1 <= len(summary_ids) <= 100
            or any(HEX_ID_PATTERN.fullmatch(str(item)) is None for item in summary_ids)
        ):
            raise WorkspaceError(
                400,
                "invalid_summary_ids",
                "request",
                False,
                "summary_ids must contain valid job IDs.",
            )
        upstream = {"summary_ids": [str(item) for item in summary_ids]}
        if report_type == "incident":
            incident_id = str(payload.get("incident_id") or "")
            if HEX_ID_PATTERN.fullmatch(incident_id) is None:
                raise WorkspaceError(
                    400,
                    "invalid_incident_id",
                    "request",
                    False,
                    "An exact incident_id is required.",
                )
            upstream["incident_id"] = incident_id
        status, value = self.client.json(
            "summarization",
            "POST",
            f"/api/v1/reports/{report_type}",
            payload=upstream,
            request_id=request_id,
            operation="report_create",
            timeout=30,
        )
        if not isinstance(value, dict):
            raise WorkspaceError(
                502,
                "invalid_report",
                "summarization",
                True,
                "Summarization returned an invalid report.",
            )
        self._require_identity(value, "summarization")
        if HEX_ID_PATTERN.fullmatch(str(value.get("report_id", ""))) is None:
            raise WorkspaceError(
                502,
                "invalid_report",
                "summarization",
                True,
                "Summarization returned an invalid report ID.",
            )
        return status, self._report(value)

    def report_download(self, name: str, request_id: str) -> tuple[bytes, str]:
        if REPORT_NAME_PATTERN.fullmatch(name) is None:
            raise WorkspaceError(
                404, "report_not_found", "request", False, "Report was not found."
            )
        expected = "application/json" if name.endswith(".json") else "text/markdown"
        limit = JSON_LIMIT if expected == "application/json" else BINARY_LIMIT
        opened = self.client.open_binary(
            "summarization",
            f"/api/v1/reports/{name}",
            request_id=request_id,
            operation="report_download",
            timeout=15,
            require_length=True,
            max_bytes=limit,
            accept=expected,
        )
        try:
            content = opened.response.read(limit + 1)
        finally:
            opened.response.close()
        if len(content) > limit:
            raise WorkspaceError(
                502,
                "report_too_large",
                "summarization",
                False,
                "The report exceeded the configured limit.",
            )
        if opened.content_type not in {expected, "text/plain"}:
            raise WorkspaceError(
                502,
                "invalid_report_type",
                "summarization",
                True,
                "Summarization returned an invalid report type.",
            )
        if expected == "application/json":
            try:
                report = json.loads(
                    content, parse_constant=_reject_json_constant
                )
            except (ValueError, json.JSONDecodeError) as error:
                raise WorkspaceError(
                    502,
                    "invalid_report",
                    "summarization",
                    True,
                    "Summarization returned invalid report JSON.",
                ) from error
            expected_id = name.removesuffix(".json")
            if (
                not isinstance(report, dict)
                or report.get("schema_version") != SCHEMA_VERSION
                or report.get("store_id") != STORE_ID
                or report.get("report_id") != expected_id
            ):
                raise WorkspaceError(
                    502,
                    "upstream_identity_mismatch",
                    "summarization",
                    True,
                    "Summarization returned a mismatched report.",
                )
        self.client.binary_complete(opened, len(content), "success")
        return content, expected

    def bootstrap(self, request_id: str) -> dict[str, Any]:
        calls: dict[str, Callable[[], Any]] = {
            "cameras": lambda: self.cameras(request_id),
            "analytics": lambda: self.analytics_state(request_id),
            "incidents": lambda: self.incident_state(request_id),
            "search": lambda: self.search_state(request_id),
            "summaries": lambda: self.summary_state(request_id),
        }
        components: dict[str, Any] = {}

        def invoke(name: str) -> tuple[str, Any]:
            try:
                return name, {"available": True, "data": calls[name]()}
            except WorkspaceError as error:
                return name, {
                    "available": False,
                    "error": {
                        "code": error.code,
                        "service_id": error.service_id,
                        "retryable": error.retryable,
                    },
                }

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            for name, value in pool.map(invoke, calls):
                components[name] = value
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "generated_at": utc_now(),
            "phase": "PHASE-15",
            "phase_status": "PARTIAL",
            "components": components,
            "capabilities": {
                "same_origin_workspace": True,
                "camera_live_ids": ["cam-01"],
                "video_upload": {
                    "enabled": False,
                    "reason": "No safe project-owned media intake contract is available.",
                },
                "add_camera": {
                    "enabled": False,
                    "reason": "Camera onboarding requires the operator secret-reference runbook.",
                },
                "image_search": True,
                "image_summarization": False,
                "general_live_summarization": False,
                "grounded_qa": True,
                "reports": ["incident", "shift", "daily"],
            },
        }


def parse_single_range(header: str, size: int) -> tuple[int, int] | None:
    if not header:
        return None
    if size <= 0 or not header.startswith("bytes=") or "," in header:
        raise WorkspaceError(
            416, "invalid_range", "selected-media", False, "Requested byte range is invalid."
        )
    value = header[6:].strip()
    if "-" not in value:
        raise WorkspaceError(
            416, "invalid_range", "selected-media", False, "Requested byte range is invalid."
        )
    start_text, end_text = value.split("-", 1)
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                raise ValueError
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_text)
            end = size - 1 if not end_text else int(end_text)
            if start < 0 or end < start:
                raise ValueError
            end = min(end, size - 1)
    except ValueError as error:
        raise WorkspaceError(
            416, "invalid_range", "selected-media", False, "Requested byte range is invalid."
        ) from error
    if start >= size:
        raise WorkspaceError(
            416,
            "range_not_satisfiable",
            "selected-media",
            False,
            "Requested byte range is outside the media.",
        )
    return start, end
