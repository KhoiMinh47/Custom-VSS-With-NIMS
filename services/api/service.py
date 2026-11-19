from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import uuid
from email.parser import BytesParser
from email.policy import compat32
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from catalog import TOOL_CATALOG, execute_tool
from gpu_control import (
    control_snapshot,
    enqueue_model_power,
    enqueue_switch,
    enqueue_vlm_test,
    model_control_snapshot,
)
from registry import build_snapshot, load_registry, read_admission_state, utc_now
from router import route_query
from security import audit, permitted, principal, read_audit
from vss_ui import VSSUIAdapter
from workspace import (
    BINARY_LIMIT,
    JSON_LIMIT,
    WORKSPACE_PREFIX,
    BinaryResponse,
    WorkspaceAdapter,
    WorkspaceError,
    parse_single_range,
)


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
LOG_LOCK = threading.Lock()


def reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def structured_log(event: str, **fields: Any) -> None:
    line = json.dumps(
        {
            "@timestamp": utc_now(),
            "level": "INFO",
            "service": "phase15-unified-api",
            "event": event,
            **fields,
        },
        separators=(",", ":"),
        allow_nan=False,
    )
    with LOG_LOCK:
        print(line, flush=True)


class Runtime:
    def __init__(self) -> None:
        self.registry_path = Path(
            os.environ.get("SERVICE_REGISTRY", "/config/application/service-registry.json")
        )
        self.camera_registry_path = Path(
            os.environ.get(
                "CAMERA_REGISTRY", "/config/cameras/cameras.hybrid.json"
            )
        )
        self.vss_ui_url = os.environ.get("VSS_UI_URL", "http://127.0.0.1:39511")
        self.openapi_path = Path(
            os.environ.get("OPENAPI_PATH", "/config/openapi/phase15.openapi.json")
        )
        self.admission_root = Path(os.environ.get("ADMISSION_DIR", "/runtime/admission"))
        self.audit_path = Path(
            os.environ.get("AUDIT_LOG", "/runtime/phase15/audit/audit.jsonl")
        )
        self.gpu_control_root = Path(
            os.environ.get("GPU_CONTROL_DIR", "/runtime/phase15/gpu-control")
        )
        self.governance_root = Path(
            os.environ.get("GOVERNANCE_DIR", "/runtime/phase15/governance")
        )
        self.token_store = Path(
            os.environ.get(
                "TOKEN_STORE", "/run/secrets/phase15-token-hashes.json"
            )
        )
        self.trusted_full_access = (
            os.environ.get("PHASE15_TRUSTED_LOOPBACK_FULL_ACCESS", "false").lower()
            == "true"
        )
        self.probe_timeout = float(os.environ.get("PROBE_TIMEOUT_SECONDS", "1.5"))
        self.cache_seconds = float(os.environ.get("SNAPSHOT_CACHE_SECONDS", "5"))
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self._snapshot: dict[str, Any] | None = None
        self._snapshot_at = 0.0
        self.requests = 0
        self.denied = 0
        self.tool_calls = 0
        self.probe_failures = 0
        self.registry = load_registry(self.registry_path)
        self.workspace = WorkspaceAdapter(
            self.camera_registry_path,
            structured_log,
            self.governance_root,
        )
        self.vss_ui = VSSUIAdapter(
            self.workspace,
            self.vss_ui_url,
            os.environ.get("UPLOAD_STAGING_DIR", "/runtime/phase15/vss-upload-staging"),
            vlm_test_upload_mode=os.environ.get("VLM_TEST_UPLOAD_MODE", "false").lower() == "true",
            admission_root=self.admission_root,
        )

    def snapshot(self, force: bool = False) -> dict[str, Any]:
        with self.lock:
            now = time.monotonic()
            if (
                not force
                and self._snapshot is not None
                and now - self._snapshot_at < self.cache_seconds
            ):
                return self._snapshot
            self.registry = load_registry(self.registry_path)
            self._snapshot = build_snapshot(self.registry, self.probe_timeout)
            admission = self.admission()
            active_profiles = {
                lease["profile"]
                for lease in admission["leases"]
                if lease.get("status") == "granted"
            }
            violations = []
            for service in self._snapshot["services"]:
                if (
                    service.get("pausable_by_gpu")
                    and admission["active_count"] > 0
                    and service["status"] == "unavailable"
                ):
                    service["status"] = "paused_for_gpu"
                    service["policy_state"] = "serialized"
                profiles = set(service.get("admission_profiles", []))
                if not profiles:
                    continue
                if service["status"] == "healthy" and not profiles.intersection(active_profiles):
                    service["policy_state"] = "unleased_active"
                    violations.append(service["id"])
                elif service["status"] == "healthy":
                    service["policy_state"] = "admitted"
                else:
                    service["policy_state"] = "standby"
            self._snapshot["admission_summary"] = {
                "active_leases": admission["active_count"],
                "policy_violations": violations,
                "read_only": False,
                "control_requires_operator": True,
            }
            statuses = (
                "healthy",
                "degraded",
                "unavailable",
                "standby",
                "locked",
                "deferred",
                "unknown",
                "browser_only",
                "paused_for_gpu",
            )
            self._snapshot["counts"] = {
                status: sum(
                    service["status"] == status for service in self._snapshot["services"]
                )
                for status in statuses
            }
            self._snapshot["ready"] = all(
                service["status"] in {"healthy", "browser_only", "paused_for_gpu"}
                for service in self._snapshot["services"]
                if service["expected_state"] == "always_on"
            )
            self._snapshot_at = now
            self.probe_failures = self._snapshot["counts"]["unavailable"]
            return self._snapshot

    def admission(self) -> dict[str, Any]:
        return read_admission_state(self.admission_root)

    def gpu_control(self) -> dict[str, Any]:
        return control_snapshot(self.gpu_control_root, self.admission_root)

    def gpu_models(self) -> dict[str, Any]:
        return model_control_snapshot(self.gpu_control_root, self.admission_root)

    def queue_vlm_test(
        self,
        job_id: str,
        identity: dict[str, Any],
        request_id: str,
        workflow: str = "upload_rtcv_vlm",
    ) -> dict[str, Any]:
        worker = self.gpu_control().get("worker", {})
        if worker.get("status") != "online":
            raise RuntimeError("GPU control worker is offline")
        return enqueue_vlm_test(
            self.gpu_control_root,
            job_id=job_id,
            identity=identity,
            request_id=request_id,
            workflow=workflow,
        )

    def metrics(self) -> str:
        current = self.snapshot()
        return "\n".join(
            [
                "# HELP phase15_unified_api_ready Unified control-plane readiness.",
                "# TYPE phase15_unified_api_ready gauge",
                "phase15_unified_api_ready 1",
                f"phase15_managed_services {len(current['services'])}",
                f"phase15_managed_ports {current['managed_ports']}",
                f"phase15_services_healthy {current['counts']['healthy']}",
                f"phase15_services_unavailable {current['counts']['unavailable']}",
                f"phase15_services_standby {current['counts']['standby']}",
                f"phase15_http_requests_total {self.requests}",
                f"phase15_authorization_denied_total {self.denied}",
                f"phase15_tool_calls_total {self.tool_calls}",
                f"phase15_active_gpu_leases {self.admission()['active_count']}",
                f"phase15_gpu_policy_violations {len(current['admission_summary']['policy_violations'])}",
                f"phase15_gpu_control_worker_online {int(self.gpu_control()['worker'].get('status') == 'online')}",
                "",
            ]
        )


class Handler(BaseHTTPRequestHandler):
    runtime: Runtime
    server_version = "NTC-VSS"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def parse_request(self) -> bool:
        # VS Code Remote SSH may leave a short NUL prefix on a forwarded
        # connection after its target container is recreated. Only normalize
        # a bounded prefix followed by a supported HTTP method.
        original = self.raw_requestline
        cleaned = original.lstrip(b"\x00")
        nul_count = len(original) - len(cleaned)
        if (
            0 < nul_count <= 4096
            and cleaned.startswith(
                (b"GET ", b"HEAD ", b"POST ", b"PUT ", b"DELETE ")
            )
        ):
            self.raw_requestline = cleaned
            structured_log("forwarded_request_normalized", nul_prefix_bytes=nul_count)
        if not super().parse_request():
            return False
        port = int(os.environ.get("HTTP_PORT", "39510"))
        host = self.headers.get("Host", "").strip().lower()
        if host not in {
            f"127.0.0.1:{port}",
            f"localhost:{port}",
        }:
            request_id = self._request_id()
            structured_log(
                "request_host_rejected",
                request_id=request_id,
                error_type="invalid_host",
            )
            self._json(
                421,
                {
                    "status": "misdirected_request",
                    "request_id": request_id,
                },
            )
            return False
        return True

    def _security_headers(self, *, ui: bool = False) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if ui:
            policy = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https://webassets.nvidia.com; "
                "font-src 'self' data: https://webassets.nvidia.com; "
                "img-src 'self' data: blob:; media-src 'self' blob:; "
                "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                "base-uri 'self'; form-action 'self'"
            )
        else:
            policy = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; media-src 'self'; connect-src 'self'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
                "form-action 'self'"
            )
        self.send_header("Content-Security-Policy", policy)

    def _json(
        self,
        status: int,
        value: Any,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        try:
            body = json.dumps(
                value, separators=(",", ":"), allow_nan=False
            ).encode()
        except (TypeError, ValueError):
            status = 502
            body = b'{"schema_version":"1.0.0","status":"error","code":"invalid_response"}'
        if len(body) > JSON_LIMIT:
            status = 502
            body = b'{"schema_version":"1.0.0","status":"error","code":"response_too_large"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, nested in (extra_headers or {}).items():
            self.send_header(key, nested)
        self._security_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _text(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        ui: bool = False,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self._security_headers(ui=ui)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _identity(self) -> dict[str, Any]:
        return principal(
            self.headers,
            self.runtime.token_store,
            trusted_full_access=self.runtime.trusted_full_access,
        )

    def _request_id(self) -> str:
        value = self.headers.get("X-Request-ID", "")
        if 1 <= len(value) <= 100 and all(character.isalnum() or character in "-_." for character in value):
            return value
        return uuid.uuid4().hex

    def _authorized(self, permission: str, request_id: str) -> dict[str, Any] | None:
        identity = self._identity()
        if permitted(identity, permission):
            return identity
        self.runtime.denied += 1
        audit(
            self.runtime.audit_path,
            identity=identity,
            action=permission,
            outcome="denied",
            request_id=request_id,
            resource=urlsplit(self.path).path,
        )
        self._json(403, {"status": "forbidden", "request_id": request_id})
        return None

    def _same_origin_request(self) -> bool:
        fetch_site = self.headers.get("Sec-Fetch-Site", "").strip().lower()
        if fetch_site not in {"", "none", "same-origin"}:
            return False
        origin = self.headers.get("Origin", "").strip().lower()
        port = int(os.environ.get("HTTP_PORT", "39510"))
        return not origin or origin in {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }

    def _read_json(self, max_bytes: int = 64 * 1024) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("application/json is required")
        if not self._same_origin_request():
            raise ValueError("cross-origin mutation rejected")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > max_bytes:
            raise ValueError("invalid request payload size")
        value = json.loads(
            self.rfile.read(length),
            parse_constant=reject_json_constant,
        )
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        json.dumps(value, allow_nan=False)
        return value

    def _read_upload(self) -> tuple[bytes, str, str, str]:
        if not self._same_origin_request():
            raise ValueError("cross-origin mutation rejected")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > BINARY_LIMIT:
            raise ValueError("invalid upload payload size")
        filename = self.headers.get("X-File-Name", "")
        content_type = (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        idempotency_key = self.headers.get("Idempotency-Key", "")
        return self.rfile.read(length), filename, content_type, idempotency_key

    def _read_vss_chunk(self) -> tuple[bytes, str, str]:
        if not self._same_origin_request():
            raise ValueError("cross-origin mutation rejected")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > BINARY_LIMIT or "multipart/form-data" not in self.headers.get("Content-Type", "").lower():
            raise ValueError("invalid multipart upload")
        raw = self.rfile.read(length)
        envelope = (f"Content-Type: {self.headers.get('Content-Type')}\r\nMIME-Version: 1.0\r\n\r\n").encode() + raw
        message = BytesParser(policy=compat32).parsebytes(envelope)
        media = None; filename = self.headers.get("nvstreamer-file-name", "")
        for part in message.walk():
            if part.is_multipart():
                continue
            disp = part.get("Content-Disposition", "")
            if 'name="mediaFile"' in disp:
                if media is not None: raise ValueError("duplicate mediaFile")
                media = part.get_payload(decode=True) or b""
            elif 'name="filename"' in disp:
                filename = (part.get_payload(decode=True) or b"").decode("utf-8", "ignore")
        if media is None or not filename:
            raise ValueError("mediaFile and filename are required")
        return media, filename, self.headers.get("Content-Type", "")

    def _workspace_system(self, force: bool = False) -> dict[str, Any]:
        current = self.runtime.snapshot(force=force)
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "generated_at": current.get("generated_at"),
            "phase": current.get("phase"),
            "phase_status": current.get("phase_status"),
            "phase14_status": current.get("phase14_status"),
            "ready": current.get("ready"),
            "counts": current.get("counts", {}),
            "admission_summary": current.get("admission_summary", {}),
            "services": [
                {
                    key: service.get(key)
                    for key in (
                        "id",
                        "name",
                        "category",
                        "phase",
                        "status",
                        "expected_state",
                        "policy_state",
                        "pausable_by_gpu",
                    )
                }
                for service in current.get("services", [])
            ],
        }

    def _workspace_error(self, error: WorkspaceError, request_id: str) -> None:
        structured_log(
            "workspace_request_failed",
            request_id=request_id,
            service_id=error.service_id,
            error_code=error.code,
            retryable=error.retryable,
            http_status=error.status,
        )
        self._json(error.status, error.public(request_id))

    def _workspace_audit(
        self,
        identity: dict[str, Any],
        action: str,
        request_id: str,
        resource: str,
        *,
        mutating: bool,
        outcome: str = "success",
    ) -> None:
        audit(
            self.runtime.audit_path,
            identity=identity,
            action=action,
            outcome=outcome,
            request_id=request_id,
            resource=resource,
            detail={"mutating": mutating},
        )

    def _queue_vlm_test_workflow(
        self,
        identity: dict[str, Any],
        request_id: str,
        value: dict[str, Any],
        workflow: str = "upload_rtcv_vlm",
    ) -> None:
        job_id = str(value.get("job_id") or value.get("vlmTestJobId") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", job_id):
            return
        allowed_statuses = (
            {"ready_to_launch", "waiting_for_gpu", "failed"}
            if workflow == "vlm_only"
            else {"queued_for_rtcv", "awaiting_rtcv_candidate"}
        )
        if "status" in value and value.get("status") not in allowed_statuses:
            return
        try:
            command = self.runtime.queue_vlm_test(job_id, identity, request_id, workflow)
        except (RuntimeError, ValueError) as error:
            value["workflow_status"] = "blocked_gpu_worker"
            value["workflow_message"] = str(error)[:240]
            structured_log(
                "vlm_test_workflow_queue_failed",
                request_id=request_id,
                job_id=job_id,
                error_type=type(error).__name__,
            )
            return
        value["workflow_status"] = "queued"
        value["workflow_command_id"] = command["command_id"]
        value["workflow_message"] = "Upload → RT-CV → VLM đã được xếp hàng trên host worker."

    def _send_binary_headers(
        self,
        status: int,
        content_type: str,
        *,
        content_length: int | None = None,
        content_range: str | None = None,
        disposition: str | None = None,
        accept_ranges: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if content_length is not None:
            self.send_header("Content-Length", str(content_length))
        if content_range is not None:
            self.send_header("Content-Range", content_range)
        if disposition is not None:
            self.send_header("Content-Disposition", disposition)
        if accept_ranges:
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()

    @staticmethod
    def _discard(response: Any, amount: int) -> int:
        discarded = 0
        while discarded < amount:
            chunk = response.read(min(64 * 1024, amount - discarded))
            if not chunk:
                break
            discarded += len(chunk)
        return discarded

    def _serve_live(self, opened: BinaryResponse) -> None:
        transferred = 0
        outcome = "client_disconnected"
        try:
            content_type = opened.content_type_header
            if "boundary=" not in content_type.lower():
                content_type = "multipart/x-mixed-replace; boundary=frame"
            self._send_binary_headers(200, content_type)
            while True:
                chunk = opened.response.read(64 * 1024)
                if not chunk:
                    outcome = "completed"
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                transferred += len(chunk)
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            outcome = "client_disconnected"
        finally:
            opened.response.close()
            self.runtime.workspace.client.binary_complete(
                opened, transferred, outcome
            )

    def _serve_media(self, opened: BinaryResponse, range_header: str) -> None:
        if opened.content_length is None:
            opened.response.close()
            raise WorkspaceError(
                502,
                "missing_content_length",
                opened.service_id,
                False,
                "The selected media response omitted its content length.",
            )
        size = opened.content_length
        try:
            selected = parse_single_range(range_header, size)
        except WorkspaceError as error:
            opened.response.close()
            structured_log(
                "workspace_request_failed",
                request_id=opened.request_id,
                service_id=error.service_id,
                error_code=error.code,
                retryable=error.retryable,
                http_status=error.status,
            )
            self._json(
                error.status,
                error.public(opened.request_id),
                {"Content-Range": f"bytes */{size}"},
            )
            return
        start, end = selected if selected is not None else (0, size - 1)
        expected = end - start + 1
        if start and self._discard(opened.response, start) != start:
            opened.response.close()
            raise WorkspaceError(
                502,
                "truncated_media",
                opened.service_id,
                True,
                "The selected media response was truncated.",
            )
        self._send_binary_headers(
            206 if selected is not None else 200,
            opened.content_type or "video/mp4",
            content_length=expected,
            content_range=(
                f"bytes {start}-{end}/{size}" if selected is not None else None
            ),
            accept_ranges=True,
        )
        transferred = 0
        outcome = "completed"
        try:
            while transferred < expected:
                chunk = opened.response.read(min(64 * 1024, expected - transferred))
                if not chunk:
                    outcome = "truncated"
                    break
                self.wfile.write(chunk)
                transferred += len(chunk)
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            outcome = "client_disconnected"
        finally:
            opened.response.close()
            self.runtime.workspace.client.binary_complete(
                opened, transferred, outcome
            )

    def _serve_download(
        self, body: bytes, content_type: str, safe_name: str
    ) -> None:
        self._send_binary_headers(
            200,
            content_type,
            content_length=len(body),
            disposition=f'attachment; filename="{safe_name}"',
        )
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _redirect(self, location: str) -> None:
        self.send_response(308)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self._security_headers(ui=True)
        self.end_headers()

    def _ui(self, path: str, query: str, method: str = "GET") -> None:
        response = self.runtime.vss_ui.ui(path, query, method)
        self._text(
            response.status,
            response.body,
            response.content_type,
            ui=True,
            cache_control=response.cache_control,
        )

    def do_GET(self) -> None:  # noqa: N802
        self.runtime.requests += 1
        request_id = self._request_id()
        path = urlsplit(self.path).path
        try:
            if path == "/health/live":
                self._json(200, {"status": "live", "schema_version": SCHEMA_VERSION})
                return
            if path == "/health/ready":
                self.runtime.snapshot()
                self._json(
                    200,
                    {
                        "status": "ready",
                        "schema_version": SCHEMA_VERSION,
                        "store_id": STORE_ID,
                    },
                )
                return
            if path == "/metrics":
                self._text(
                    200,
                    self.runtime.metrics().encode(),
                    "text/plain; version=0.0.4",
                )
                return
            if path == "/openapi.json":
                self._text(
                    200,
                    self.runtime.openapi_path.read_bytes(),
                    "application/json; charset=utf-8",
                )
                return
            if path == "/api/v1/vlm-test/overlay.js":
                overlay_path = Path(__file__).with_name("vlm_test_overlay.js")
                self._text(
                    200,
                    overlay_path.read_bytes(),
                    "application/javascript; charset=utf-8",
                    ui=True,
                    cache_control="no-store",
                )
                return
            if path == "/api/v1/gpu-control/overlay.js":
                overlay_path = Path(__file__).with_name("gpu_control_overlay.js")
                self._text(
                    200,
                    overlay_path.read_bytes(),
                    "application/javascript; charset=utf-8",
                    ui=True,
                    cache_control="no-store",
                )
                return
            if path == "/api/v1/stream-sources/overlay.js":
                overlay_path = Path(__file__).with_name("stream_sources_overlay.js")
                self._text(
                    200,
                    overlay_path.read_bytes(),
                    "application/javascript; charset=utf-8",
                    ui=True,
                    cache_control="no-store",
                )
                return
            if path == "/api/v1/session":
                self._json(200, self._identity())
                return
            if path.startswith("/compat/"):
                if not self._same_origin_request():
                    self._json(403, {"status": "forbidden", "request_id": request_id})
                    return
                if self._authorized("overview:read", request_id) is None:
                    return
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                adapter = self.runtime.vss_ui
                if path == "/compat/vst/api/v1/sensor/list":
                    self._json(200, adapter.sensor_inventory(request_id))
                    return
                if path == "/compat/vst/api/v1/replay/streams":
                    self._json(200, adapter.replay_streams(request_id))
                    return
                if path == "/compat/vst/api/v1/storage/size":
                    if set(query).difference({"timelines"}):
                        raise WorkspaceError(400, "invalid_storage_query", "request", False, "Storage query is invalid.")
                    self._json(200, adapter.storage_size(request_id))
                    return
                picture_match = re.fullmatch(
                    r"/compat/vst/api/v1/(?:replay|live)/stream/([A-Za-z0-9_-]{1,100})/picture",
                    path,
                )
                if picture_match:
                    if set(query).difference({"startTime", "width", "height"}) or any(len(values) != 1 for values in query.values()):
                        raise WorkspaceError(400, "invalid_picture_query", "request", False, "Picture query is invalid.")
                    body = adapter.picture(
                        picture_match.group(1), query.get("startTime", [""])[0], request_id
                    )
                    self._text(200, body, "image/jpeg")
                    return
                url_match = re.fullmatch(
                    r"/compat/vst/api/v1/storage/file/([A-Za-z0-9_-]{1,100})/url",
                    path,
                )
                if url_match:
                    self._json(200, adapter.video_url(url_match.group(1), query, request_id))
                    return
                media_match = re.fullmatch(
                    r"/compat/vst/storage/temp_files/([A-Za-z0-9][A-Za-z0-9._-]{0,239}\.mp4)",
                    path,
                )
                if media_match:
                    self._serve_media(
                        adapter.open_video(media_match.group(1), request_id),
                        self.headers.get("Range", ""),
                    )
                    return
                upload_media = re.fullmatch(r"/compat/vst/storage/uploads/([0-9a-f]{64})\.mp4", path)
                if upload_media:
                    self._serve_media(
                        self.runtime.workspace.client.open_binary("media-intake", f"/api/v1/assets/{upload_media.group(1)}/media", request_id=request_id, operation="vss_ui_uploaded_media", timeout=30, require_length=True, accept="video/mp4"),
                        self.headers.get("Range", ""),
                    )
                    return
                if path == "/compat/mdx/incidents":
                    self._json(200, adapter.incidents(query, request_id))
                    return
                if path == "/compat/mdx/frames":
                    self._json(
                        200,
                        {
                            "schema_version": SCHEMA_VERSION,
                            "store_id": STORE_ID,
                            "frames": [],
                        },
                    )
                    return
                realtime_alert_match = re.fullmatch(
                    r"/compat/alert-bridge/api/v1/realtime(?:/([A-Za-z0-9_-]{1,100}))?",
                    path,
                )
                if realtime_alert_match:
                    if query:
                        raise WorkspaceError(
                            400,
                            "unsupported_query_parameter",
                            "request",
                            False,
                            "Realtime alert query parameters are not supported.",
                        )
                    upstream_path = "/api/v1/realtime"
                    if realtime_alert_match.group(1):
                        upstream_path += f"/{realtime_alert_match.group(1)}"
                    status, value = self.runtime.workspace.realtime_alert_rules(
                        "GET", upstream_path, request_id
                    )
                    self._json(status, value)
                    return
                self._json(404, {"status": "not_found", "request_id": request_id})
                return
            if path == WORKSPACE_PREFIX or path.startswith(f"{WORKSPACE_PREFIX}/"):
                if not self._same_origin_request():
                    structured_log(
                        "workspace_cross_origin_rejected",
                        request_id=request_id,
                        error_type="cross_origin",
                    )
                    self._json(
                        403,
                        {
                            "status": "forbidden",
                            "request_id": request_id,
                        },
                    )
                    return
                if self._authorized("overview:read", request_id) is None:
                    return
                query = parse_qs(
                    urlsplit(self.path).query, keep_blank_values=True
                )
                workspace = self.runtime.workspace
                if path == WORKSPACE_PREFIX:
                    if set(query).difference({"refresh"}):
                        raise WorkspaceError(
                            400,
                            "unsupported_query_parameter",
                            "request",
                            False,
                            "Workspace query contains unsupported parameters.",
                        )
                    value = workspace.bootstrap(request_id)
                    value["system"] = self._workspace_system(
                        force=query.get("refresh") == ["true"]
                    )
                    self._json(200, value)
                    return
                if path == f"{WORKSPACE_PREFIX}/cameras":
                    self._json(200, workspace.cameras(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/stream-sources":
                    self._json(200, workspace.stream_sources(request_id))
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/cameras/(cam-[0-9]{{2}})/state",
                    path,
                )
                if match:
                    self._json(200, workspace.camera_state(match.group(1), request_id))
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/cameras/(cam-[0-9]{{2}})/live\.mjpeg",
                    path,
                )
                if match:
                    self._serve_live(workspace.open_live(match.group(1), request_id))
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/cameras/(cam-[0-9]{{2}})/thumbnail\.jpg",
                    path,
                )
                if match:
                    if set(query).difference({"at"}) or len(
                        query.get("at", [])
                    ) > 1:
                        raise WorkspaceError(
                            400,
                            "unsupported_query_parameter",
                            "request",
                            False,
                            "Thumbnail query contains unsupported parameters.",
                        )
                    body = workspace.thumbnail(
                        match.group(1), query.get("at", [""])[0], request_id
                    )
                    self._text(200, body, "image/jpeg")
                    return
                if path == f"{WORKSPACE_PREFIX}/analytics/state":
                    self._json(200, workspace.analytics_state(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/analytics/events":
                    self._json(200, workspace.analytics_events(query, request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/analytics/config":
                    self._json(200, workspace.analytics_config(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/incidents/state":
                    self._json(200, workspace.incident_state(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/alerts":
                    self._json(200, workspace.alerts(query, request_id))
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/media/([0-9a-f]{{64}})\.mp4",
                    path,
                )
                if match:
                    self._serve_media(
                        workspace.open_media(match.group(1), request_id),
                        self.headers.get("Range", ""),
                    )
                    return
                if path == f"{WORKSPACE_PREFIX}/search/state":
                    self._json(200, workspace.search_state(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/summaries/state":
                    self._json(200, workspace.summary_state(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/summaries/jobs":
                    self._json(200, workspace.summary_jobs(request_id))
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/summaries/jobs/([0-9a-f]{{64}})",
                    path,
                )
                if match:
                    self._json(200, workspace.summary_job(match.group(1), request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/reports":
                    self._json(200, workspace.reports(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/uploads":
                    self._json(200, workspace.uploads(query, request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/vlm-tests/state":
                    self._json(200, workspace.vlm_test_state(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/vlm-tests/jobs":
                    self._json(200, workspace.vlm_test_jobs(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/vlm-tests/store":
                    self._json(200, workspace.vlm_test_store(request_id))
                    return
                if path == f"{WORKSPACE_PREFIX}/vlm-tests/realtime/candidates":
                    self._json(200, workspace.vlm_test_candidates(request_id))
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/vlm-tests/jobs/([0-9a-f]{{64}})",
                    path,
                )
                if match:
                    jobs = workspace.vlm_test_jobs(request_id)["jobs"]
                    job = next((item for item in jobs if item.get("job_id") == match.group(1)), None)
                    if job is None:
                        raise WorkspaceError(404, "job_not_found", "vlm-test", False, "VLM-test job was not found.")
                    self._json(200, {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "job": job})
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/vlm-tests/jobs/([0-9a-f]{{64}})/media",
                    path,
                )
                if match:
                    self._serve_media(
                        workspace.open_vlm_test_media(match.group(1), request_id, store=False),
                        self.headers.get("Range", ""),
                    )
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/vlm-tests/store/([0-9a-f]{{64}})/media",
                    path,
                )
                if match:
                    self._serve_media(
                        workspace.open_vlm_test_media(match.group(1), request_id, store=True),
                        self.headers.get("Range", ""),
                    )
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/uploads/([0-9a-f]{{64}})/media",
                    path,
                )
                if match:
                    self._serve_media(
                        workspace.open_upload_media(match.group(1), request_id),
                        self.headers.get("Range", ""),
                    )
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/reports/([0-9a-f]{{64}})/media/([0-9a-f]{{64}})\.mp4",
                    path,
                )
                if match:
                    self._serve_media(
                        workspace.open_report_media(
                            match.group(1), match.group(2), request_id
                        ),
                        self.headers.get("Range", ""),
                    )
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/reports/([0-9a-f]{{64}}\.(?:json|md))",
                    path,
                )
                if match:
                    body, content_type = workspace.report_download(
                        match.group(1), request_id
                    )
                    self._serve_download(body, content_type, match.group(1))
                    return
                self._json(
                    404, {"status": "not_found", "request_id": request_id}
                )
                return
            if path in {"/api/v1/overview", "/api/v1/services"}:
                identity = self._authorized("overview:read", request_id)
                if identity is None:
                    return
                value = self.runtime.snapshot(force=parse_qs(urlsplit(self.path).query).get("refresh") == ["true"])
                self._json(200, value)
                return
            if path == "/api/v1/ports":
                if self._authorized("ports:read", request_id) is None:
                    return
                current = self.runtime.snapshot()
                self._json(
                    200,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "store_id": STORE_ID,
                        "ports": [
                            {
                                "service_id": service["id"],
                                "name": service["name"],
                                "port": service.get("port"),
                                "exposure": service.get("exposure"),
                                "status": service["status"],
                                "public_url": service.get("public_url"),
                            }
                            for service in current["services"]
                            if service.get("port") is not None
                        ],
                    },
                )
                return
            if path == "/api/v1/admission":
                if self._authorized("admission:read", request_id) is None:
                    return
                self._json(200, self.runtime.admission())
                return
            if path == "/api/v1/gpu-control":
                if self._authorized("admission:read", request_id) is None:
                    return
                self._json(200, self.runtime.gpu_control())
                return
            if path == "/api/v1/gpu-control/models":
                if self._authorized("admission:read", request_id) is None:
                    return
                self._json(200, self.runtime.gpu_models())
                return
            if path == "/api/v1/audit":
                if self._authorized("audit:read", request_id) is None:
                    return
                limit = int(parse_qs(urlsplit(self.path).query).get("limit", ["100"])[0])
                self._json(200, {"records": read_audit(self.runtime.audit_path, limit)})
                return
            if path == "/api/v1/tools":
                if self._authorized("tools:list", request_id) is None:
                    return
                self._json(200, {"tools": TOOL_CATALOG, "read_only": True})
                return
            if path.startswith("/api/"):
                self._json(404, {"status": "not_found", "request_id": request_id})
                return
            if path == "/dashboard":
                self._redirect("/")
                return
            self._ui(path, urlsplit(self.path).query)
        except WorkspaceError as error:
            self._workspace_error(error, request_id)
        except (ValueError, OSError, json.JSONDecodeError) as error:
            structured_log("request_rejected", request_id=request_id, error_type=type(error).__name__)
            self._json(400, {"status": "rejected", "request_id": request_id})

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in {"/health/live", "/health/ready"}:
            body = b'{"status":"ready"}'
            content_type = "application/json"
        elif path == "/openapi.json":
            body = self.runtime.openapi_path.read_bytes()
            content_type = "application/json; charset=utf-8"
        elif path == "/dashboard":
            self._redirect("/")
            return
        else:
            try:
                self._ui(path, urlsplit(self.path).query, "HEAD")
            except WorkspaceError:
                self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        self.runtime.requests += 1
        request_id = self._request_id()
        path = urlsplit(self.path).path
        workspace_attempt: tuple[dict[str, Any], str, str] | None = None
        gpu_attempt: dict[str, Any] | None = None
        try:
            if path == "/compat/agent/api/v1/search":
                identity = self._authorized("tools:execute", request_id)
                if identity is None:
                    return
                payload = self._read_json()
                status, value = self.runtime.vss_ui.search(payload, request_id)
                self._workspace_audit(
                    identity,
                    "vss-ui.search",
                    request_id,
                    "semantic-search",
                    mutating=False,
                )
                self._json(status, value)
                return
            if path == "/api/chat":
                identity = self._authorized("tools:execute", request_id)
                if identity is None:
                    return
                payload = self._read_json(max_bytes=256 * 1024)
                answer = self.runtime.vss_ui.chat(payload, request_id)
                self._workspace_audit(
                    identity,
                    "vss-ui.chat",
                    request_id,
                    "grounded-assistant",
                    mutating=False,
                )
                self._text(200, answer.encode("utf-8"), "text/plain; charset=utf-8")
                return
            if path == "/compat/chat/stream":
                identity = self._authorized("tools:execute", request_id)
                if identity is None:
                    return
                payload = self._read_json(max_bytes=256 * 1024)
                answer = self.runtime.vss_ui.chat(payload, request_id)
                self._workspace_audit(
                    identity,
                    "vss-ui.chat.stream",
                    request_id,
                    "grounded-assistant",
                    mutating=False,
                )
                event = json.dumps(
                    {
                        "id": f"chatcmpl-{request_id}",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": answer},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                    separators=(",", ":"),
                    allow_nan=False,
                )
                body = f"data: {event}\n\ndata: [DONE]\n\n".encode("utf-8")
                self._text(
                    200,
                    body,
                    "text/event-stream; charset=utf-8",
                    cache_control="no-store",
                )
                return
            if path == "/compat/vst/api/v1/storage/file":
                identity = self._authorized("tools:execute", request_id)
                if identity is None: return
                body, filename, multipart_type = self._read_vss_chunk()
                number = int(self.headers.get("nvstreamer-chunk-number", "0")); total = int(self.headers.get("nvstreamer-total-chunks", "0"))
                status, value = self.runtime.vss_ui.upload_chunk(body, filename=filename, identifier=self.headers.get("nvstreamer-identifier", ""), number=number, total=total, content_type="video/x-matroska" if filename.lower().endswith(".mkv") else "video/mp4", request_id=request_id)
                if value.get("vlmTestJobId"):
                    self._queue_vlm_test_workflow(identity, request_id, value)
                self._json(status, value); return
            realtime_alert_match = re.fullmatch(
                r"/compat/alert-bridge/api/v1/realtime(?:/([A-Za-z0-9_-]{1,100}))?",
                path,
            )
            if realtime_alert_match:
                identity = self._authorized("tools:execute", request_id)
                if identity is None:
                    return
                payload = self._read_json(max_bytes=256 * 1024)
                if not isinstance(payload, dict):
                    raise ValueError("realtime alert rule requires a JSON object")
                upstream_path = "/api/v1/realtime"
                if realtime_alert_match.group(1):
                    upstream_path += f"/{realtime_alert_match.group(1)}"
                status, value = self.runtime.workspace.realtime_alert_rules(
                    "POST", upstream_path, request_id, payload
                )
                self._workspace_audit(
                    identity,
                    "workspace.realtime_alert_rule.create",
                    request_id,
                    realtime_alert_match.group(1) or "new",
                    mutating=True,
                )
                self._json(status, value)
                return
            complete = re.fullmatch(r"/compat/agent/api/v1/videos/([0-9a-f]{64})/complete", path)
            if complete:
                self._authorized("tools:execute", request_id)
                self._read_json(max_bytes=256 * 1024)
                self._json(200, {"status": "accepted", "sensorId": complete.group(1), "schema_version": SCHEMA_VERSION, "store_id": STORE_ID}); return
            if path == f"{WORKSPACE_PREFIX}/uploads":
                identity = self._authorized("gpu:control", request_id)
                if identity is None:
                    return
                body, filename, content_type, idempotency_key = self._read_upload()
                status, value = self.runtime.workspace.upload(
                    body,
                    filename,
                    content_type,
                    idempotency_key,
                    request_id,
                )
                self._workspace_audit(
                    identity,
                    "workspace.upload.create",
                    request_id,
                    str(value.get("asset_id", "uploaded-asset")),
                    mutating=True,
                )
                self._json(status, value)
                return
            if path == f"{WORKSPACE_PREFIX}/vlm-tests/uploads":
                identity = self._authorized("gpu:control", request_id)
                if identity is None:
                    return
                body, filename, content_type, idempotency_key = self._read_upload()
                status, value = self.runtime.workspace.vlm_test_upload(
                    body, filename, content_type, idempotency_key, request_id
                )
                self._workspace_audit(
                    identity,
                    "workspace.vlm_test.upload_stage",
                    request_id,
                    str(value.get("job_id", "vlm-test-upload")),
                    mutating=True,
                )
                self._queue_vlm_test_workflow(identity, request_id, value)
                self._json(status, value)
                return
            if path == f"{WORKSPACE_PREFIX}/stream-sources":
                identity = self._authorized("stream:control", request_id)
                if identity is None:
                    return
                payload = self._read_json()
                status, value = self.runtime.workspace.add_stream_source(payload, request_id)
                self._workspace_audit(
                    identity,
                    "workspace.stream_source.add",
                    request_id,
                    str(value.get("source", {}).get("source_id", "stream-source")),
                    mutating=True,
                )
                self._json(status, value)
                return
            vlm_job_action = re.fullmatch(
                rf"{re.escape(WORKSPACE_PREFIX)}/vlm-tests/jobs/([0-9a-f]{{64}})/(candidate|launch|save|rtcv-start)",
                path,
            )
            vlm_store_launch = re.fullmatch(
                rf"{re.escape(WORKSPACE_PREFIX)}/vlm-tests/store/([0-9a-f]{{64}})/launch",
                path,
            )
            vlm_realtime_launch = re.fullmatch(
                rf"{re.escape(WORKSPACE_PREFIX)}/vlm-tests/realtime/([0-9a-f]{{64}})/launch",
                path,
            )
            if vlm_job_action or vlm_store_launch or vlm_realtime_launch:
                identity = self._authorized("gpu:control", request_id)
                if identity is None:
                    return
                payload = self._read_json()
                if vlm_job_action:
                    identifier, action = vlm_job_action.groups()
                    if action in {"launch", "save", "rtcv-start"} and payload:
                        raise ValueError(f"VLM-test {action} requires an empty JSON object")
                    if action == "rtcv-start":
                        command = self.runtime.queue_vlm_test(identifier, identity, request_id)
                        status = 202
                        value = {
                            "schema_version": SCHEMA_VERSION,
                            "store_id": STORE_ID,
                            "job_id": identifier,
                            "status": "queued_for_rtcv",
                            "workflow_status": "queued",
                            "workflow_command_id": command["command_id"],
                        }
                    elif action == "launch":
                        current = self.runtime.workspace.vlm_test_job(identifier, request_id)
                        # Upload jobs that already have an RT-CV candidate must
                        # be launched by the host worker. Calling the VLM
                        # service directly skips the admission lease and
                        # leaves the job in waiting_for_gpu forever.
                        if isinstance(current.get("candidate_event"), dict):
                            value = dict(current)
                            self._queue_vlm_test_workflow(
                                identity,
                                request_id,
                                value,
                                "vlm_only",
                            )
                            if value.get("workflow_status") == "queued":
                                value.update(
                                    {
                                        "status": "waiting_for_gpu",
                                        "vlm_status": "waiting_for_admission",
                                        "blocked_gate": "local_vlm_lease",
                                        "workflow_message": "VLM retry đã được xếp hàng qua GPU worker; đang chờ local_vlm admission.",
                                    }
                                )
                            status = 202
                        else:
                            status, value = self.runtime.workspace.vlm_test_action(
                                f"/api/v1/jobs/{identifier}/{action}",
                                payload,
                                request_id,
                                f"vlm_test_{action}",
                            )
                    else:
                        status, value = self.runtime.workspace.vlm_test_action(
                            f"/api/v1/jobs/{identifier}/{action}",
                            payload,
                            request_id,
                            f"vlm_test_{action}",
                        )
                    resource = identifier
                    audit_action = f"workspace.vlm_test.{action}"
                elif vlm_store_launch:
                    identifier = vlm_store_launch.group(1)
                    if payload:
                        raise ValueError("VLM-test Store launch requires an empty JSON object")
                    status, value = self.runtime.workspace.vlm_test_action(
                        f"/api/v1/store/{identifier}/stage",
                        payload,
                        request_id,
                        "vlm_test_store_stage",
                    )
                    self._queue_vlm_test_workflow(identity, request_id, value, "vlm_only")
                    resource = identifier
                    audit_action = "workspace.vlm_test.store_stage"
                else:
                    identifier = vlm_realtime_launch.group(1)
                    if payload:
                        raise ValueError("VLM-test realtime launch requires an empty JSON object")
                    status, value = self.runtime.workspace.vlm_test_action(
                        "/api/v1/realtime/candidates/stage",
                        {"incident_id": identifier},
                        request_id,
                        "vlm_test_realtime_stage",
                    )
                    self._queue_vlm_test_workflow(identity, request_id, value, "vlm_only")
                    resource = identifier
                    audit_action = "workspace.vlm_test.realtime_stage"
                self._workspace_audit(identity, audit_action, request_id, resource, mutating=True)
                self._json(status, value)
                return
            if (
                path
                in {
                    f"{WORKSPACE_PREFIX}/search",
                    f"{WORKSPACE_PREFIX}/assistant/evidence",
                    f"{WORKSPACE_PREFIX}/summaries/jobs",
                    f"{WORKSPACE_PREFIX}/summaries/qa",
                }
                or re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/alerts/(?:hybrid|direct)/[0-9a-f]{{64}}/feedback",
                    path,
                )
                or re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/alerts/(?:hybrid|direct)/[0-9a-f]{{64}}/restore",
                    path,
                )
                or re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/uploads/[0-9a-f]{{64}}/restore",
                    path,
                )
                or re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/summaries/jobs/[0-9a-f]{{64}}/actions/(?:caption|summarize|retry)",
                    path,
                )
                or re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/reports/(?:incident|shift|daily)",
                    path,
                )
            ):
                permission = (
                    "tools:execute"
                    if path
                    in {
                        f"{WORKSPACE_PREFIX}/search",
                        f"{WORKSPACE_PREFIX}/summaries/qa",
                    }
                    else "gpu:control"
                )
                identity = self._authorized(permission, request_id)
                if identity is None:
                    return
                if permission == "gpu:control":
                    feedback_target = re.fullmatch(
                        rf"{re.escape(WORKSPACE_PREFIX)}/alerts/(hybrid|direct)/([0-9a-f]{{64}})/feedback",
                        path,
                    )
                    restore_target = re.fullmatch(
                        rf"{re.escape(WORKSPACE_PREFIX)}/alerts/(hybrid|direct)/([0-9a-f]{{64}})/restore",
                        path,
                    )
                    upload_restore_target = re.fullmatch(
                        rf"{re.escape(WORKSPACE_PREFIX)}/uploads/([0-9a-f]{{64}})/restore",
                        path,
                    )
                    action_target = re.fullmatch(
                        rf"{re.escape(WORKSPACE_PREFIX)}/summaries/jobs/([0-9a-f]{{64}})/actions/(caption|summarize|retry)",
                        path,
                    )
                    report_target = re.fullmatch(
                        rf"{re.escape(WORKSPACE_PREFIX)}/reports/(incident|shift|daily)",
                        path,
                    )
                    if feedback_target:
                        workspace_attempt = (
                            identity,
                            "workspace.alert.feedback",
                            f"{feedback_target.group(1)}:{feedback_target.group(2)}",
                        )
                    elif restore_target:
                        workspace_attempt = (
                            identity,
                            "workspace.alert.restore",
                            f"{restore_target.group(1)}:{restore_target.group(2)}",
                        )
                    elif upload_restore_target:
                        workspace_attempt = (
                            identity,
                            "workspace.upload.restore",
                            upload_restore_target.group(1),
                        )
                    elif action_target:
                        workspace_attempt = (
                            identity,
                            f"workspace.summary.{action_target.group(2)}",
                            action_target.group(1),
                        )
                    elif report_target:
                        workspace_attempt = (
                            identity,
                            "workspace.report.create",
                            f"{report_target.group(1)}-report",
                        )
                    else:
                        workspace_attempt = (
                            identity,
                            (
                                "workspace.assistant.evidence"
                                if path == f"{WORKSPACE_PREFIX}/assistant/evidence"
                                else "workspace.summary.create"
                            ),
                            (
                                "exact-evidence"
                                if path == f"{WORKSPACE_PREFIX}/assistant/evidence"
                                else "summary-job"
                            ),
                        )
                payload = self._read_json()
                workspace = self.runtime.workspace
                if path == f"{WORKSPACE_PREFIX}/search":
                    status, value = workspace.search(payload, request_id)
                    self._workspace_audit(
                        identity,
                        "workspace.search",
                        request_id,
                        "semantic-search",
                        mutating=False,
                    )
                    self._json(status, value)
                    return
                if path == f"{WORKSPACE_PREFIX}/assistant/evidence":
                    status, value = workspace.evidence_assistant(
                        payload, request_id
                    )
                    self._workspace_audit(
                        identity,
                        "workspace.assistant.evidence",
                        request_id,
                        str(value.get("summary_id", "exact-evidence")),
                        mutating=value.get("created") is True,
                    )
                    self._json(status, value)
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/uploads/([0-9a-f]{{64}})/restore",
                    path,
                )
                if match:
                    status, value = workspace.mutate_upload(
                        match.group(1), payload, request_id, restore=True
                    )
                    self._workspace_audit(
                        identity,
                        "workspace.upload.restore",
                        request_id,
                        match.group(1),
                        mutating=True,
                    )
                    self._json(status, value)
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/alerts/(hybrid|direct)/([0-9a-f]{{64}})/feedback",
                    path,
                )
                if match:
                    status, value = workspace.feedback(
                        match.group(1), match.group(2), payload, request_id
                    )
                    self._workspace_audit(
                        identity,
                        "workspace.alert.feedback",
                        request_id,
                        f"{match.group(1)}:{match.group(2)}",
                        mutating=True,
                    )
                    self._json(status, value)
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/alerts/(hybrid|direct)/([0-9a-f]{{64}})/restore",
                    path,
                )
                if match:
                    status, value = workspace.restore_alert(
                        match.group(1), match.group(2), payload, request_id
                    )
                    self._workspace_audit(
                        identity,
                        "workspace.alert.restore",
                        request_id,
                        f"{match.group(1)}:{match.group(2)}",
                        mutating=True,
                    )
                    self._json(status, value)
                    return
                if path == f"{WORKSPACE_PREFIX}/summaries/jobs":
                    status, value = workspace.create_summary_job(
                        payload, request_id
                    )
                    self._workspace_audit(
                        identity,
                        "workspace.summary.create",
                        request_id,
                        str(value.get("job_id", "summary-job")),
                        mutating=True,
                    )
                    self._json(status, value)
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/summaries/jobs/([0-9a-f]{{64}})/actions/(caption|summarize|retry)",
                    path,
                )
                if match:
                    if payload:
                        raise WorkspaceError(
                            400,
                            "unexpected_payload",
                            "request",
                            False,
                            "Summary actions require an empty JSON object.",
                        )
                    status, value = workspace.summary_action(
                        match.group(1), match.group(2), request_id
                    )
                    self._workspace_audit(
                        identity,
                        f"workspace.summary.{match.group(2)}",
                        request_id,
                        match.group(1),
                        mutating=True,
                    )
                    self._json(status, value)
                    return
                if path == f"{WORKSPACE_PREFIX}/summaries/qa":
                    status, value = workspace.summary_qa(payload, request_id)
                    self._workspace_audit(
                        identity,
                        "workspace.summary.qa",
                        request_id,
                        str(payload.get("summary_id", "grounded-qa")),
                        mutating=False,
                    )
                    self._json(status, value)
                    return
                match = re.fullmatch(
                    rf"{re.escape(WORKSPACE_PREFIX)}/reports/(incident|shift|daily)",
                    path,
                )
                if match:
                    status, value = workspace.create_report(
                        match.group(1), payload, request_id
                    )
                    self._workspace_audit(
                        identity,
                        "workspace.report.create",
                        request_id,
                        str(value.get("report_id", f"{match.group(1)}-report")),
                        mutating=True,
                    )
                    self._json(status, value)
                    return
                self._json(
                    404, {"status": "not_found", "request_id": request_id}
                )
                return
            model_power = re.fullmatch(r"/api/v1/gpu-control/models/(llm|vlm)", path)
            if model_power:
                identity = self._authorized("gpu:control", request_id)
                if identity is None:
                    return
                gpu_attempt = identity
                payload = self._read_json()
                if set(payload).difference({"enabled", "confirmed"}):
                    raise ValueError("model power command contains unsupported fields")
                if not isinstance(payload.get("enabled"), bool):
                    raise ValueError("enabled must be boolean")
                with self.runtime.lock:
                    control = self.runtime.gpu_control()
                    if control["worker"].get("status") != "online":
                        raise RuntimeError("GPU control worker is offline")
                    command = enqueue_model_power(
                        self.runtime.gpu_control_root,
                        model_id=model_power.group(1),
                        enabled=payload["enabled"],
                        identity=identity,
                        request_id=request_id,
                        confirmed=payload.get("confirmed") is True,
                    )
                audit(
                    self.runtime.audit_path,
                    identity=identity,
                    action="gpu.model.power",
                    outcome="queued",
                    request_id=request_id,
                    resource=model_power.group(1),
                    detail={"command_id": command["command_id"], "mutating": True},
                )
                self._json(202, command)
                return
            if path == "/api/v1/gpu-control/commands":
                identity = self._authorized("gpu:control", request_id)
                if identity is None:
                    return
                gpu_attempt = identity
                payload = self._read_json()
                allowed_gpu_fields = {
                    "target_profile",
                    "confirmed",
                    "managed_job_id",
                    "auto_restore",
                }
                if set(payload).difference(allowed_gpu_fields):
                    raise ValueError("GPU command contains unsupported fields")
                with self.runtime.lock:
                    control = self.runtime.gpu_control()
                    if control["worker"].get("status") != "online":
                        raise RuntimeError("GPU control worker is offline")
                    command = enqueue_switch(
                        self.runtime.gpu_control_root,
                        target_profile=str(payload.get("target_profile", "")),
                        identity=identity,
                        request_id=request_id,
                        confirmed=payload.get("confirmed") is True,
                        managed_job_id=(
                            str(payload.get("managed_job_id"))
                            if payload.get("managed_job_id") is not None
                            else None
                        ),
                        auto_restore=payload.get("auto_restore") is True,
                    )
                audit(
                    self.runtime.audit_path,
                    identity=identity,
                    action="gpu.profile.switch",
                    outcome="queued",
                    request_id=request_id,
                    resource=str(command["target_profile"]),
                    detail={
                        "command_id": command["command_id"],
                        "mutating": True,
                    },
                )
                self._json(202, command)
                return
            if path not in {"/api/v1/tools/execute", "/api/v1/agent/query"}:
                self._json(404, {"status": "not_found", "request_id": request_id})
                return
            identity = self._authorized("tools:execute", request_id)
            if identity is None:
                return
            payload = self._read_json()
            if path == "/api/v1/agent/query":
                question = str(payload.get("question", "")).strip()
                if not question:
                    raise ValueError("question is required")
                tool_name = route_query(question)
                arguments = {}
            else:
                tool_name = str(payload.get("name", ""))
                arguments = payload.get("arguments", {})
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be an object")
            tool = next((item for item in TOOL_CATALOG if item["name"] == tool_name), None)
            if tool is None or not permitted(identity, str(tool["permission"])):
                raise PermissionError("tool is not permitted")
            result = execute_tool(
                tool_name,
                arguments,
                snapshot=lambda: self.runtime.snapshot(force=True),
                admission=self.runtime.admission,
            )
            self.runtime.tool_calls += 1
            audit(
                self.runtime.audit_path,
                identity=identity,
                action="tool.execute",
                outcome="success",
                request_id=request_id,
                resource=tool_name,
                detail={"mutating": False},
            )
            self._json(
                200,
                {
                    "schema_version": SCHEMA_VERSION,
                    "request_id": request_id,
                    "tool": tool_name,
                    "read_only": True,
                    "result": result,
                },
            )
        except WorkspaceError as error:
            if workspace_attempt is not None:
                self._workspace_audit(
                    workspace_attempt[0],
                    workspace_attempt[1],
                    request_id,
                    workspace_attempt[2],
                    mutating=True,
                    outcome="rejected" if error.status < 500 else "failed",
                )
            self._workspace_error(error, request_id)
        except PermissionError:
            self.runtime.denied += 1
            self._json(403, {"status": "forbidden", "request_id": request_id})
        except RuntimeError as error:
            if gpu_attempt is not None:
                audit(
                    self.runtime.audit_path,
                    identity=gpu_attempt,
                    action="gpu.profile.switch",
                    outcome="failed",
                    request_id=request_id,
                    resource="gpu-profile",
                    detail={"mutating": True},
                )
            structured_log("gpu_command_conflict", request_id=request_id)
            self._json(
                409,
                {
                    "status": "conflict",
                    "request_id": request_id,
                    "message": str(error)[:200],
                },
            )
        except (ValueError, json.JSONDecodeError) as error:
            if workspace_attempt is not None:
                self._workspace_audit(
                    workspace_attempt[0],
                    workspace_attempt[1],
                    request_id,
                    workspace_attempt[2],
                    mutating=True,
                    outcome="rejected",
                )
            if gpu_attempt is not None:
                audit(
                    self.runtime.audit_path,
                    identity=gpu_attempt,
                    action="gpu.profile.switch",
                    outcome="rejected",
                    request_id=request_id,
                    resource="gpu-profile",
                    detail={"mutating": True},
                )
            structured_log("tool_rejected", request_id=request_id, error_type=type(error).__name__)
            self._json(400, {"status": "rejected", "request_id": request_id})

    def do_PUT(self) -> None:  # noqa: N802
        self.runtime.requests += 1
        request_id = self._request_id()
        path = urlsplit(self.path).path
        identity: dict[str, Any] | None = None
        try:
            if path != f"{WORKSPACE_PREFIX}/analytics/config":
                self._json(
                    404, {"status": "not_found", "request_id": request_id}
                )
                return
            identity = self._authorized("gpu:control", request_id)
            if identity is None:
                return
            payload = self._read_json(max_bytes=256 * 1024)
            status, value = self.runtime.workspace.update_analytics_config(
                payload, request_id
            )
            self._workspace_audit(
                identity,
                "workspace.analytics.config.update",
                request_id,
                "behavior-analytics-config",
                mutating=True,
            )
            self._json(status, value)
        except WorkspaceError as error:
            if identity is not None:
                self._workspace_audit(
                    identity,
                    "workspace.analytics.config.update",
                    request_id,
                    "behavior-analytics-config",
                    mutating=True,
                    outcome="rejected" if error.status < 500 else "failed",
                )
            self._workspace_error(error, request_id)
        except (ValueError, json.JSONDecodeError) as error:
            if identity is not None:
                self._workspace_audit(
                    identity,
                    "workspace.analytics.config.update",
                    request_id,
                    "behavior-analytics-config",
                    mutating=True,
                    outcome="rejected",
                )
            structured_log(
                "workspace_update_rejected",
                request_id=request_id,
                error_type=type(error).__name__,
            )
            self._json(400, {"status": "rejected", "request_id": request_id})

    def do_DELETE(self) -> None:  # noqa: N802
        self.runtime.requests += 1
        request_id = self._request_id()
        path = urlsplit(self.path).path
        identity: dict[str, Any] | None = None
        match = re.fullmatch(
            rf"{re.escape(WORKSPACE_PREFIX)}/alerts/(hybrid|direct)/([0-9a-f]{{64}})",
            path,
        )
        upload_match = re.fullmatch(
            rf"{re.escape(WORKSPACE_PREFIX)}/uploads/([0-9a-f]{{64}})",
            path,
        )
        stream_source_match = re.fullmatch(
            rf"{re.escape(WORKSPACE_PREFIX)}/stream-sources/([A-Za-z0-9_-]{{1,100}})",
            path,
        )
        compat_rtsp_delete_match = re.fullmatch(
            r"/compat/agent/api/v1/rtsp-streams/delete/([^/]{1,240})",
            path,
        )
        compat_realtime_alert_delete_match = re.fullmatch(
            r"/compat/alert-bridge/api/v1/realtime/([A-Za-z0-9_-]{1,100})",
            path,
        )
        if (
            match is None
            and upload_match is None
            and stream_source_match is None
            and compat_rtsp_delete_match is None
            and compat_realtime_alert_delete_match is None
        ):
            self._json(404, {"status": "not_found", "request_id": request_id})
            return
        try:
            identity = self._authorized(
                "tools:execute"
                if compat_realtime_alert_delete_match is not None
                else (
                    "stream:control"
                    if stream_source_match is not None or compat_rtsp_delete_match is not None
                    else "gpu:control"
                ),
                request_id,
            )
            if identity is None:
                return
            if compat_rtsp_delete_match is not None:
                if not self._same_origin_request():
                    raise ValueError("cross-origin mutation rejected")
                source_name = unquote(compat_rtsp_delete_match.group(1))
                status, value = self.runtime.workspace.delete_stream_source_by_name(
                    source_name, request_id
                )
                action = "workspace.stream_source.delete"
                resource = source_name
            elif compat_realtime_alert_delete_match is not None:
                if not self._same_origin_request():
                    raise ValueError("cross-origin mutation rejected")
                payload = self._read_json(max_bytes=64 * 1024)
                if payload:
                    raise ValueError("realtime alert rule delete requires an empty JSON object")
                identifier = compat_realtime_alert_delete_match.group(1)
                status, value = self.runtime.workspace.realtime_alert_rules(
                    "DELETE", f"/api/v1/realtime/{identifier}", request_id
                )
                action = "workspace.realtime_alert_rule.delete"
                resource = identifier
            elif stream_source_match is not None:
                payload = self._read_json()
                if payload:
                    raise ValueError("stream source delete requires an empty JSON object")
                status, value = self.runtime.workspace.delete_stream_source(
                    stream_source_match.group(1), request_id
                )
                action = "workspace.stream_source.delete"
                resource = stream_source_match.group(1)
            else:
                payload = self._read_json()
                if upload_match is not None:
                    status, value = self.runtime.workspace.mutate_upload(
                        upload_match.group(1), payload, request_id, restore=False
                    )
                    action = "workspace.upload.delete"
                    resource = upload_match.group(1)
                else:
                    status, value = self.runtime.workspace.delete_alert(
                        match.group(1), match.group(2), payload, request_id
                    )
                    action = "workspace.alert.delete"
                    resource = f"{match.group(1)}:{match.group(2)}"
            self._workspace_audit(
                identity,
                action,
                request_id,
                resource,
                mutating=True,
            )
            self._json(status, value)
        except WorkspaceError as error:
            if identity is not None:
                self._workspace_audit(
                    identity,
                    action if "action" in locals() else (
                        "workspace.realtime_alert_rule.delete"
                        if compat_realtime_alert_delete_match is not None
                        else (
                            "workspace.stream_source.delete"
                            if stream_source_match is not None or compat_rtsp_delete_match is not None
                            else ("workspace.upload.delete" if upload_match is not None else "workspace.alert.delete")
                        )
                    ),
                    request_id,
                    resource if "resource" in locals() else (
                        stream_source_match.group(1)
                        if stream_source_match is not None
                        else (unquote(compat_rtsp_delete_match.group(1)) if compat_rtsp_delete_match is not None
                        else (upload_match.group(1) if upload_match is not None else (
                            compat_realtime_alert_delete_match.group(1)
                            if compat_realtime_alert_delete_match is not None
                            else f"{match.group(1)}:{match.group(2)}"
                        )))
                    ),
                    mutating=True,
                    outcome="rejected" if error.status < 500 else "failed",
                )
            self._workspace_error(error, request_id)
        except (ValueError, json.JSONDecodeError) as error:
            structured_log(
                "workspace_delete_rejected",
                request_id=request_id,
                error_type=type(error).__name__,
            )
            self._json(400, {"status": "rejected", "request_id": request_id})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    runtime = Runtime()
    Handler.runtime = runtime
    host = os.environ.get("HTTP_HOST", "127.0.0.1")
    if host != "127.0.0.1":
        raise RuntimeError("phase15 unified API must bind to 127.0.0.1")
    port = int(os.environ.get("HTTP_PORT", "39510"))
    server = ThreadingHTTPServer((host, port), Handler)
    structured_log(
        "service_started",
        host=host,
        port=port,
        access_mode=(
            "trusted-loopback-admin"
            if runtime.trusted_full_access
            else "bearer-rbac"
        ),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
