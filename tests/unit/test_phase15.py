from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import sys
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "services/api"
MCP = ROOT / "services/mcp"
AGENT = ROOT / "services/agent"
GPU_WORKER = ROOT / "services/gpu-control-worker"
MEDIA_INTAKE = ROOT / "services/media-intake"
for path in (API, MCP, AGENT, GPU_WORKER):
    sys.path.insert(0, str(path))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


registry = load("phase15_registry", API / "registry.py")
security = load("phase15_security", API / "security.py")
configure_token = load("phase15_configure_token", API / "configure_token.py")
catalog = load("phase15_catalog", MCP / "catalog.py")
router = load("phase15_router", AGENT / "router.py")
gpu_control = load("phase15_gpu_control", API / "gpu_control.py")
gpu_worker = load("phase15_gpu_worker", GPU_WORKER / "worker.py")
workspace = load("phase15_workspace", API / "workspace.py")
vss_ui = load("vss_ui", API / "vss_ui.py")
service = load("phase15_service", API / "service.py")
media_intake = load("phase15_media_intake", MEDIA_INTAKE / "service.py")


def test_registry_is_versioned_unique_and_locks_phase14() -> None:
    value = registry.load_registry(ROOT / "config/application/service-registry.json")
    services = value["services"]
    ports = [service["port"] for service in services if service["port"] is not None]
    assert value["schema_version"] == "1.0.0"
    assert value["store_id"] == "store-001"
    assert len(ports) == len(set(ports))
    retail = next(service for service in services if service["id"] == "retail-ai")
    assert retail["expected_state"] == "locked"
    assert retail["port"] is None


def test_gpu_profiles_are_on_demand_and_control_plane_reconciles_without_gpu() -> None:
    source = json.loads(
        (ROOT / "config/application/service-registry.json").read_text(encoding="utf-8")
    )
    by_id = {item["id"]: item for item in source["services"]}
    assert by_id["direct-rt-vlm"]["expected_state"] == "on_demand"
    assert by_id["rt-embedding-provider"]["expected_state"] == "on_demand"
    script = (ROOT / "scripts/ensure-control-plane.sh").read_text(encoding="utf-8")
    assert "phase15_compose up -d media-intake vlm-test vss-ui phase15-api" in script
    assert "phase12_compose up -d search" in script
    assert "phase13_compose up -d summarization" in script
    assert "--profile" not in script
    assert "127.0.0.1:39510" in script
    assert 'scripts/ensure-control-plane.sh' in (ROOT / 'scripts/start-phase15.sh').read_text(encoding='utf-8')
    stop_phase12 = (ROOT / "scripts/stop-phase12.sh").read_text(encoding="utf-8")
    assert "rt-embedding siglip-object-embedding" in stop_phase12
    assert "--profile rt-embedding --profile siglip stop\n" not in stop_phase12


def test_registry_rejects_duplicate_port(tmp_path: Path) -> None:
    source = json.loads(
        (ROOT / "config/application/service-registry.json").read_text(encoding="utf-8")
    )
    source["services"][1]["port"] = source["services"][0]["port"]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate managed port"):
        registry.load_registry(path)


def test_locked_snapshot_never_probes_or_claims_health() -> None:
    value = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "services": [
            {
                "id": "retail-ai",
                "name": "Retail",
                "category": "analytics",
                "expected_state": "locked",
                "port": None,
                "health_url": None,
            }
        ],
    }
    snapshot = registry.build_snapshot(value, timeout=0.01)
    assert snapshot["phase14_status"] == "LOCKED_BY_USER"
    assert snapshot["services"][0]["status"] == "locked"
    assert snapshot["architecture"]["raw_video_plane_independent"] is True


def test_probe_failure_distinguishes_outage_from_normal_standby() -> None:
    value = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "services": [
            {
                "id": "always-on",
                "name": "Always on",
                "category": "platform",
                "expected_state": "always_on",
                "port": 1,
                "health_url": "http://127.0.0.1:1/ready",
            },
            {
                "id": "on-demand",
                "name": "On demand",
                "category": "gpu",
                "expected_state": "on_demand",
                "port": 2,
                "health_url": "http://127.0.0.1:2/ready",
            },
        ],
    }
    snapshot = registry.build_snapshot(value, timeout=0.01)
    statuses = {service["id"]: service["status"] for service in snapshot["services"]}
    assert statuses == {"always-on": "unavailable", "on-demand": "standby"}
    assert snapshot["ready"] is False


def test_bearer_token_hash_maps_to_operator_without_plaintext_storage(tmp_path: Path) -> None:
    token = "unit-test-operator-token"
    token_store = tmp_path / "tokens.json"
    token_store.write_text(
        json.dumps(
            {
                "principals": [
                    {
                        "subject": "test-operator",
                        "role": "operator",
                        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    identity = security.principal({"Authorization": f"Bearer {token}"}, token_store)
    assert identity == {
        "subject": "test-operator",
        "role": "operator",
        "authenticated": True,
    }
    assert token not in token_store.read_text(encoding="utf-8")
    assert security.permitted(identity, "admission:read")


def test_token_configuration_replaces_subject_and_uses_mode_600(tmp_path: Path) -> None:
    path = tmp_path / "token-hashes.json"
    configure_token.update_token_store(path, "operator-1", "operator", "a" * 24)
    configure_token.update_token_store(path, "operator-1", "admin", "b" * 24)
    value = json.loads(path.read_text(encoding="utf-8"))
    assert len(value["principals"]) == 1
    assert value["principals"][0]["role"] == "admin"
    assert value["principals"][0]["token_sha256"] == hashlib.sha256(b"b" * 24).hexdigest()
    assert path.stat().st_mode & 0o777 == 0o600
    assert "b" * 24 not in path.read_text(encoding="utf-8")


def test_anonymous_is_viewer_and_cannot_read_admission(tmp_path: Path) -> None:
    identity = security.principal({}, tmp_path / "missing.json")
    assert identity["role"] == "viewer"
    assert security.permitted(identity, "overview:read")
    assert not security.permitted(identity, "admission:read")
    assert not security.permitted(identity, "gpu:control")


def test_trusted_loopback_mode_grants_full_admin_without_a_token(tmp_path: Path) -> None:
    identity = security.principal(
        {},
        tmp_path / "missing.json",
        trusted_full_access=True,
    )
    assert identity == {
        "subject": "trusted-loopback",
        "role": "admin",
        "authenticated": True,
    }
    assert security.permitted(identity, "gpu:control")
    assert security.permitted(identity, "audit:read")


def test_operator_can_control_gpu_but_analyst_cannot() -> None:
    assert security.permitted({"role": "operator"}, "gpu:control")
    assert security.permitted({"role": "model_engineer"}, "gpu:control")
    assert not security.permitted({"role": "analyst"}, "gpu:control")


def test_audit_is_structured_and_never_contains_authorization(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    security.audit(
        path,
        identity={"subject": "operator-1", "role": "operator"},
        action="tool.execute",
        outcome="success",
        request_id="request-1",
        resource="port.map",
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["store_id"] == "store-001"
    assert value["request_id"] == "request-1"
    assert "authorization" not in path.read_text(encoding="utf-8").lower()


def test_tool_catalog_is_allowlisted_and_read_only() -> None:
    assert catalog.TOOL_CATALOG
    assert all(tool["mutating"] is False for tool in catalog.TOOL_CATALOG)
    snapshot = lambda: {"services": [{"id": "search", "public_url": None, "launchable": False}]}
    with pytest.raises(ValueError, match="not allowlisted"):
        catalog.execute_tool(
            "runtime.start",
            {},
            snapshot=snapshot,
            admission=lambda: {},
        )


def test_deterministic_agent_routes_only_to_allowlisted_tools() -> None:
    names = {tool["name"] for tool in catalog.TOOL_CATALOG}
    assert router.route_query("GPU lease hiện tại?") == "admission.state"
    assert router.route_query("port nào cho search?") == "port.map"
    assert router.route_query("system status") in names


def test_vss_ui_uses_exact_pinned_upstream_sources() -> None:
    manifest = json.loads(
        (ROOT / "apps/vss-ui/SOURCE-MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["release_baseline"] == "3.2.1"
    assert manifest["source_tag"] == "v3.2.1"
    assert manifest["source_commit"] == "7640d917047cf7b0fd3085eefb8282754b56bc94"
    assert manifest["image"].endswith("vss-agent-ui:3.2.0")
    assert manifest["image_digest"] == "sha256:6362151a839067f517766f1997a19c302296fe80b9b0251aaee8f16b379503d9"
    assert not (ROOT / "apps/dashboard").exists()
    home = (
        ROOT
        / "third_party/video-search-and-summarization/services/ui/apps/nv-metropolis-bp-vss-ui/components/Home.tsx"
    ).read_text(encoding="utf-8")
    assert "NV-logo-white.svg" in home
    assert "enableAlertsTab" in home
    assert "enableSearchTab" in home
    assert "enableVideoManagementTab" in home


def test_vss_ui_runtime_is_same_origin_cpu_only_and_secret_free() -> None:
    compose = (ROOT / "deploy/compose/phase15.compose.yml").read_text(encoding="utf-8")
    env = (ROOT / "config/ui/vss-ui.env").read_text(encoding="utf-8")
    assert "vss-agent-ui:3.2.0@sha256:6362151a839067f" in compose
    assert "VSS_UI_URL: http://127.0.0.1:39511" in compose
    assert "../../apps/dashboard" not in compose
    assert "devices:" not in compose
    assert "runtime/raw-video" not in compose
    assert "NEXT_PUBLIC_ENABLE_ALERTS_TAB=true" in env
    assert "NEXT_PUBLIC_ENABLE_SEARCH_TAB=true" in env
    assert "NEXT_PUBLIC_ENABLE_VIDEO_MANAGEMENT_TAB=true" in env
    assert "NEXT_PUBLIC_VIDEO_MANAGEMENT_TAB_ADD_RTSP_ENABLE=true" in env
    assert "NEXT_PUBLIC_VIDEO_MANAGEMENT_VIDEO_UPLOAD_ENABLE=true" in env
    assert "NGC_API_KEY" not in env
    assert "rtsp://" not in env


class _VSSUIWorkspace:
    def cameras(self, _request_id: str):
        return {
            "cameras": [
                {
                    "camera_id": "cam-01",
                    "main_stream": {"codec": "h265", "width": 2560, "height": 1440, "fps": 25},
                }
            ]
        }

    def _vios_inventory(self, _request_id: str):
        return {"cam-01": "sensor-1"}, {"cam-01": "offline"}, True


def test_vss_ui_inventory_exposes_stable_ids_without_camera_credentials() -> None:
    adapter = vss_ui.VSSUIAdapter(_VSSUIWorkspace(), "http://127.0.0.1:39511")
    assert adapter.sensor_inventory("request-1") == [
        {"name": "cam-01", "sensorId": "sensor-1", "state": "offline"}
    ]
    text = json.dumps(adapter.replay_streams("request-1"))
    assert "cam-01" in text
    assert "camera-ref.invalid" in text
    assert "password" not in text
    assert "192.168." not in text


def test_stream_source_adapter_scrubs_urls_and_protects_stable_camera() -> None:
    class StreamClient:
        def __init__(self):
            self.calls = []

        def json(self, service_id, method, path, **kwargs):
            self.calls.append((service_id, method, path, kwargs.get("payload")))
            if path == "/api/v1/sensor/streams":
                return 200, [{"sensor-1": [{"streamId": "sensor-1", "name": "cam-01", "url": "rtsp://secret.invalid/main"}]}, {"sensor-2": [{"streamId": "sensor-2", "name": "warehouse", "url": "rtsp://user:password@camera.invalid/live"}]}]
            if path == "/api/v1/sensor/status":
                return 200, {"sensor-1": {"state": "running"}, "sensor-2": {"state": "offline"}}
            if method == "POST":
                return 200, {"sensorId": "sensor-3", "url": "rtsp://user:password@camera.invalid/live"}
            if method == "DELETE":
                return 200, {}
            raise AssertionError((service_id, method, path))

    adapter = workspace.WorkspaceAdapter(ROOT / "config/cameras/cameras.hybrid.json")
    client = StreamClient()
    adapter.client = client
    inventory = adapter.stream_sources("stream-inventory")
    text = json.dumps(inventory)
    assert "warehouse" in text
    assert "secret.invalid" not in text
    assert "password" not in text
    assert next(item for item in inventory["sources"] if item["name"] == "cam-01")["can_delete"] is False
    status, added = adapter.add_stream_source(
        {"schema_version": "1.0.0", "store_id": "store-001", "name": "new-source", "url": "rtsp://user:password@camera.invalid/live"},
        "stream-add",
    )
    assert status == 200
    assert added["source"]["source_id"] == "sensor-3"
    assert "password" not in json.dumps(added)
    add_call = next(call for call in client.calls if call[1] == "POST")
    assert add_call[3]["sensorUrl"].startswith("rtsp://")
    status, deleted = adapter.delete_stream_source("sensor-2", "stream-delete")
    assert status == 200
    assert deleted["source_id"] == "sensor-2"
    status, deleted_by_name = adapter.delete_stream_source_by_name("warehouse", "stream-delete-name")
    assert status == 200
    assert deleted_by_name["source_id"] == "sensor-2"
    with pytest.raises(workspace.WorkspaceError, match="stable_camera_protected"):
        adapter.delete_stream_source("sensor-1", "stream-protected")


def test_legacy_vss_rtsp_delete_resolves_name_without_request_body() -> None:
    handler = object.__new__(service.Handler)
    calls: list[tuple[str, str]] = []
    responses: list[tuple[int, object]] = []
    identity = {"subject": "operator-1", "role": "operator"}

    class DeleteWorkspace:
        @staticmethod
        def delete_stream_source_by_name(name: str, request_id: str):
            calls.append((name, request_id))
            return 200, {"status": "deleted", "source_id": "sensor-2"}

    handler.runtime = SimpleNamespace(requests=0, workspace=DeleteWorkspace())
    handler.path = "/compat/agent/api/v1/rtsp-streams/delete/Warehouse%20Camera%202"
    handler.headers = {
        "Sec-Fetch-Site": "same-origin",
        "Origin": "http://127.0.0.1:39510",
    }
    handler._request_id = lambda: "req-legacy-delete"
    handler._authorized = lambda _permission, _request_id: identity
    handler._workspace_audit = lambda *_args, **_kwargs: None
    handler._json = lambda status, value: responses.append((status, value))

    service.Handler.do_DELETE(handler)

    assert calls == [("Warehouse Camera 2", "req-legacy-delete")]
    assert responses == [(200, {"status": "deleted", "source_id": "sensor-2"})]


def test_vss_ui_replay_inventory_includes_added_stream_sources() -> None:
    class AllStreamWorkspace(_VSSUIWorkspace):
        def stream_sources(self, _request_id: str):
            return {
                "sources": [
                    {
                        "source_id": "sensor-added",
                        "name": "warehouse",
                        "metadata": {"codec": "H264", "resolution": "1920x1080", "framerate": "25"},
                    }
                ]
            }

        def cameras(self, _request_id: str):
            raise AssertionError("replay inventory should use all VIOS stream sources")

    adapter = vss_ui.VSSUIAdapter(AllStreamWorkspace(), "http://127.0.0.1:39511")
    value = adapter.replay_streams("stream-replay")
    assert value[0]["sensor-added"][0]["name"] == "warehouse"
    assert value[0]["sensor-added"][0]["url"] == "rtsp://camera-ref.invalid/sensor-added"


def test_vss_ui_search_adapter_preserves_identity_and_utc() -> None:
    class SearchWorkspace(_VSSUIWorkspace):
        def search(self, payload, request_id):
            assert payload["schema_version"] == "1.0.0"
            assert payload["store_id"] == "store-001"
            assert payload["camera_ids"] == ["cam-01"]
            assert payload["from_utc"] == "2026-08-04T01:00:00.000Z"
            assert request_id == "request-search"
            return 200, {
                "results": [
                    {
                        "camera_id": "cam-01",
                        "start_time": "2026-08-04T01:00:01.000Z",
                        "end_time": "2026-08-04T01:00:03.000Z",
                        "score": 0.91,
                        "object_id": "person-1",
                        "route": "attribute",
                        "critic": {"verdict": "confirmed"},
                    }
                ]
            }

    adapter = vss_ui.VSSUIAdapter(SearchWorkspace(), "http://127.0.0.1:39511")
    status, value = adapter.search(
        {
            "query": "person",
            "video_sources": ["cam-01"],
            "timestamp_start": "2026-08-04T08:00:00",
            "top_k": 5,
            "agent_mode": False,
        },
        "request-search",
    )
    assert status == 200
    assert value["schema_version"] == "1.0.0"
    assert value["store_id"] == "store-001"
    assert value["data"][0]["sensor_id"] == "sensor-1"
    assert value["data"][0]["critic_result"]["result"] == "confirmed"


def test_vss_ui_incident_adapter_keeps_contract_identity() -> None:
    class AlertWorkspace(_VSSUIWorkspace):
        def alerts(self, query, request_id):
            assert query["source"] == ["all"]
            assert request_id == "request-alert"
            return {
                "partial": False,
                "alerts": [
                    {
                        "id": "a" * 64,
                        "camera_id": "cam-01",
                        "event_type": "person_presence",
                        "source_label": "Direct RT-VLM",
                        "start_time": "2026-08-04T01:00:00.000Z",
                        "end_time": "2026-08-04T01:00:05.000Z",
                        "verdict": "uncertain",
                        "reason": "needs review",
                        "model_version": "model-v1",
                        "media_available": False,
                    }
                ],
            }

    adapter = vss_ui.VSSUIAdapter(AlertWorkspace(), "http://127.0.0.1:39511")
    value = adapter.incidents({"maxResultSize": ["10"]}, "request-alert")
    incident = value["incidents"][0]
    assert value["schema_version"] == "1.0.0"
    assert incident["store_id"] == "store-001"
    assert incident["camera_id"] == "cam-01"
    assert incident["analyticsModule"]["info"]["verdict"] == "verification-failed"
    assert "videoSource" not in incident["info"]


def test_vss_ui_proxy_rejects_traversal_before_network() -> None:
    adapter = vss_ui.VSSUIAdapter(_VSSUIWorkspace(), "http://127.0.0.1:39511")
    with pytest.raises(vss_ui.WorkspaceError, match="ui_path_not_found"):
        adapter.ui("/../secrets", "")


class _FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "application/json",
        content_length: str | None = None,
    ) -> None:
        self.body = io.BytesIO(body)
        self.status = status
        self.closed = False
        self.headers: dict[str, str] = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def read(self, amount: int = -1) -> bytes:
        return self.body.read(amount)

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


class _FakeOpener:
    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, **_kwargs):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def test_workspace_bff_uses_only_fixed_loopback_upstreams_and_rejects_ssrf() -> None:
    expected = {
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
    assert workspace.UPSTREAMS == expected
    for service_id, base in expected.items():
        assert workspace.FixedUpstreamClient._url(service_id, "/health/ready") == (
            f"{base}/health/ready"
        )
    rejected = (
        ("unknown", "/health/ready"),
        ("search", "http://169.254.169.254/latest/meta-data"),
        ("search", "https://example.invalid/"),
        ("search", "/api/v1/search\r\nHost: attacker.invalid"),
        ("search", "api/v1/search"),
    )
    for service_id, path in rejected:
        with pytest.raises(RuntimeError):
            workspace.FixedUpstreamClient._url(service_id, path)


def test_workspace_client_bounds_json_and_normalizes_provider_errors() -> None:
    client = workspace.FixedUpstreamClient()
    declared = _FakeResponse(b"{}", content_length="9")
    client._opener = _FakeOpener(declared)
    with pytest.raises(workspace.WorkspaceError) as raised:
        client.json(
            "search",
            "GET",
            "/api/v1/state",
            request_id="req-size",
            operation="state",
            max_bytes=8,
        )
    assert (raised.value.status, raised.value.code, raised.value.retryable) == (
        502,
        "response_too_large",
        False,
    )
    assert declared.closed

    streamed = _FakeResponse(b'{"value":"too long"}')
    client._opener = _FakeOpener(streamed)
    with pytest.raises(workspace.WorkspaceError) as raised:
        client.json(
            "search",
            "GET",
            "/api/v1/state",
            request_id="req-stream",
            operation="state",
            max_bytes=8,
        )
    assert raised.value.code == "response_too_large"

    invalid = _FakeResponse(b"not-json")
    client._opener = _FakeOpener(invalid)
    with pytest.raises(workspace.WorkspaceError) as raised:
        client.json(
            "search",
            "GET",
            "/api/v1/state",
            request_id="req-json",
            operation="state",
        )
    assert (raised.value.status, raised.value.code, raised.value.retryable) == (
        502,
        "invalid_upstream_json",
        True,
    )

    client._opener = _FakeOpener(error=TimeoutError())
    with pytest.raises(workspace.WorkspaceError) as raised:
        client.json(
            "search",
            "GET",
            "/api/v1/state",
            request_id="req-timeout",
            operation="state",
        )
    assert (raised.value.status, raised.value.code, raised.value.retryable) == (
        504,
        "upstream_timeout",
        True,
    )
    standby = workspace.FixedUpstreamClient._mapped_http_error("search", 503)
    assert standby.public("req-provider") == {
        "schema_version": "1.0.0",
        "status": "error",
        "code": "provider_standby",
        "service_id": "search",
        "retryable": True,
        "message": "The service or admitted provider is currently unavailable.",
        "request_id": "req-provider",
    }


def test_workspace_camera_capabilities_expose_only_active_physical_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    stream_ids = {f"cam-{index:02d}": f"stream-{index:02d}" for index in range(1, 11)}
    states = {camera_id: "online" for camera_id in stream_ids}
    monkeypatch.setattr(
        adapter,
        "_vios_inventory",
        lambda _request_id: (stream_ids, states, True),
    )
    monkeypatch.setattr(
        adapter,
        "_ai_state",
        lambda _request_id: {
            "camera_id": "cam-01",
            "ai_status": "connected",
            "ai_connected": True,
            "metadata_timestamp_utc": "2026-07-31T08:00:00Z",
            "source_fps": 25,
        },
    )

    value = adapter.cameras("req-cameras")
    cameras = {item["camera_id"]: item for item in value["cameras"]}
    assert value["store_id"] == "store-001"
    assert value["count"] == 1
    assert set(cameras) == {"cam-01"}
    assert cameras["cam-01"]["source_type"] == "physical"
    assert cameras["cam-01"]["browser_preview"] is True
    assert cameras["cam-01"]["ai_enabled"] is True
    assert cameras["cam-01"]["live_url"].startswith("/api/v1/workspace/")
    serialized = json.dumps(value)
    assert "uri_secret_ref" not in serialized
    assert "camera://" not in serialized
    assert "rtsp://" not in serialized

    with pytest.raises(workspace.WorkspaceError) as raised:
        adapter.open_live("cam-02", "req-live")
    assert (raised.value.status, raised.value.code) == (404, "camera_not_found")


class _RecordingJsonClient:
    def __init__(self, responder) -> None:
        self.responder = responder
        self.calls: list[dict[str, object]] = []

    def json(self, service_id, method, path, **kwargs):
        call = {
            "service_id": service_id,
            "method": method,
            "path": path,
            **kwargs,
        }
        self.calls.append(call)
        return self.responder(call)


def test_workspace_search_preserves_filter_identity_and_normalizes_results() -> None:
    clip_a = "a" * 64
    clip_b = "b" * 64
    raw_results = [
        {
            "id": "confirmed-result",
            "store_id": "store-001",
            "camera_id": "cam-01",
            "asset_uri": f"selected-clip://{clip_a}.mp4",
            "start_time": "2026-07-31T08:01:00Z",
            "end_time": "2026-07-31T08:01:08Z",
            "fusion_score": 0.82,
            "search_channel": "fusion",
            "schema_version": "1.0.0",
            "model_version": "unit-model",
            "critic": {"verdict": "relevant", "confidence": 0.9, "reason": "match"},
        },
        {
            "id": "rejected-result",
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "camera_id": "cam-01",
            "asset_uri": f"selected-clip://{clip_b}.mp4",
            "start_time": "2026-07-31T08:02:00Z",
            "end_time": "2026-07-31T08:02:10Z",
            "fusion_score": 0.97,
            "critic": {"verdict": "not_relevant", "confidence": 0.8},
        },
        {
            "id": "below-threshold",
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "camera_id": "cam-01",
            "start_time": "2026-07-31T08:03:00Z",
            "end_time": "2026-07-31T08:03:05Z",
            "score": 0.2,
        },
        {
            "id": "outside-window",
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "camera_id": "cam-01",
            "start_time": "2026-07-31T10:00:00Z",
            "end_time": "2026-07-31T10:00:05Z",
            "score": 0.99,
        },
    ]
    client = _RecordingJsonClient(
        lambda _call: (
            200,
            {
                "schema_version": "1.0.0",
                "store_id": "store-001",
                "query": "forklift near loading zone",
                "route": "fusion",
                "critic_status": "completed",
                "results": raw_results,
                "searched_at": "2026-07-31T08:05:00Z",
            },
        )
    )
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    adapter.client = client
    payload = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "query": "forklift near loading zone",
        "mode": "agent",
        "route": "fusion",
        "camera_ids": ["cam-01"],
        "from_utc": "2026-07-31T08:00:00Z",
        "to_utc": "2026-07-31T09:00:00Z",
        "top_k": 2,
        "similarity_threshold": 0.5,
        "critic_verification": True,
        "critic_top_k": 2,
        "source_type": "all",
    }

    status, value = adapter.search(payload, "req-search")
    assert status == 200
    assert value["store_id"] == "store-001"
    assert value["filters"] == {
        "camera_ids": ["cam-01"],
        "from_utc": "2026-07-31T08:00:00Z",
        "to_utc": "2026-07-31T09:00:00Z",
        "similarity_threshold": 0.5,
        "source_type": "all",
    }
    assert value["postfilter_applied"] is True
    assert value["upstream_result_count"] == 4
    assert [item["id"] for item in value["results"]] == [
        "confirmed-result",
        "rejected-result",
    ]
    assert [item["critic_verdict"] for item in value["results"]] == [
        "confirmed",
        "rejected",
    ]
    assert value["results"][0]["duration_seconds"] == 8
    assert value["results"][0]["media_url"] == (
        f"/api/v1/workspace/media/{clip_a}.mp4"
    )
    upstream = client.calls[0]
    assert upstream["service_id"] == "search"
    assert upstream["path"] == "/api/v1/search"
    assert upstream["payload"] == {
        "top_k": 6,
        "camera_ids": ["cam-01"],
        "query": "forklift near loading zone",
        "route": "fusion",
        "critic_top_k": 2,
    }


def test_workspace_search_rejects_wrong_identity_and_unsupported_source_filter() -> None:
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    with pytest.raises(workspace.WorkspaceError) as raised:
        adapter.search(
            {
                "schema_version": "1.0.0",
                "store_id": "store-999",
                "query": "person",
            },
            "req-identity",
        )
    assert raised.value.code == "identity_mismatch"
    with pytest.raises(workspace.WorkspaceError) as raised:
        adapter.search(
            {
                "schema_version": "1.0.0",
                "store_id": "store-001",
                "query": "person",
                "source_type": "uploaded_video",
            },
            "req-source",
        )
    assert (raised.value.status, raised.value.code) == (
        409,
        "source_filter_unavailable",
    )


@pytest.mark.parametrize(
    "answer",
    [
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "grounded": True,
            "status": "completed",
            "answer": "Observed in the selected clip.",
            "evidence": [
                {
                    "asset_uri": f"selected-clip://{'c' * 64}.mp4",
                    "start_time": "2026-07-31T08:00:00Z",
                    "end_time": "2026-07-31T08:00:05Z",
                }
            ],
        },
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "grounded": False,
            "status": "refused",
            "answer": "",
            "refusal_reason": "insufficient_evidence",
            "evidence": [],
        },
    ],
)
def test_workspace_summary_qa_preserves_grounded_or_refused_state(answer) -> None:
    client = _RecordingJsonClient(lambda _call: (200, answer))
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    adapter.client = client
    summary_id = "d" * 64
    status, value = adapter.summary_qa(
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "summary_id": summary_id,
            "question": "Có forklift trong clip không?",
            "idempotency_key": "qa-unit-1",
        },
        "req-qa",
    )
    assert status == 200
    assert value["grounded"] is answer["grounded"]
    assert value["status"] == answer["status"]
    assert value.get("evidence") == answer["evidence"]
    assert client.calls[0]["payload"] == {
        "summary_id": summary_id,
        "question": "Có forklift trong clip không?",
    }
    if not answer["grounded"]:
        assert value["answer"] == ""
        assert value["refusal_reason"] == "insufficient_evidence"


def _assistant_job(
    job_id: str,
    asset_id: str,
    digest: str,
    *,
    status: str,
    start: str = "2026-07-31T08:00:00Z",
    end: str = "2026-07-31T08:00:10Z",
) -> dict:
    return {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "job_id": job_id,
        "status": status,
        "window_start": start,
        "window_end": end,
        "created_at": "2026-07-31T08:01:00Z",
        "updated_at": "2026-07-31T08:01:00Z",
        "chunks": [
            {
                "asset_uri": f"selected-clip://{asset_id}.mp4",
                "asset_sha256": digest,
                "start_time": start,
                "end_time": end,
                "caption_status": (
                    "completed" if status in {"queued_summary", "completed"} else "pending"
                ),
            }
        ],
    }


def _remember_assistant_media(
    adapter, asset_id: str, digest: str, *, start="2026-07-31T08:00:00Z", end="2026-07-31T08:00:10Z"
) -> None:
    adapter._remember_media(
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "camera_id": "cam-01",
            "asset_uri": f"selected-clip://{asset_id}.mp4",
            "clip_start_time": start,
            "clip_end_time": end,
            "clip_sha256": digest,
        }
    )


def test_evidence_assistant_attached_clip_never_calls_search_and_queues_real_job() -> None:
    asset_id, digest, job_id = "1" * 64, "2" * 64, "3" * 64
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    _remember_assistant_media(adapter, asset_id, digest)
    queued = _assistant_job(job_id, asset_id, digest, status="queued_caption")

    def respond(call):
        if call["path"] == "/api/v1/jobs":
            return 200, {"jobs": []}
        if call["path"] == "/api/v1/summaries":
            return 201, queued
        raise AssertionError(f"unexpected call: {call}")

    client = _RecordingJsonClient(respond)
    adapter.client = client
    status, value = adapter.evidence_assistant(
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "question": "họ đang làm gì",
            "context": {
                "type": "clip",
                "asset_id": asset_id,
                "camera_id": "cam-01",
                "start_time": "2026-07-31T08:00:00Z",
                "end_time": "2026-07-31T08:00:10Z",
            },
            "idempotency_key": "assistant-clip-unit",
        },
        "req-assistant-clip",
    )
    assert status == 201
    assert value["status"] == "queued_caption"
    assert value["queued"] is True
    assert value["answered"] is False
    assert value["required_profile"] == "summary_caption"
    assert value["operator_action"] == {
        "type": "request_gpu_profile",
        "profile_id": "summary_caption",
        "requires_confirmation": True,
        "endpoint": "/api/v1/gpu-control/commands",
    }
    assert value["scope"]["asset_ids"] == [asset_id]
    assert "answer" not in value
    assert all(call["service_id"] != "search" for call in client.calls)
    assert client.calls[-1]["payload"]["assets"] == [
        {
            "asset_uri": f"selected-clip://{asset_id}.mp4",
            "asset_sha256": digest,
            "start_time": "2026-07-31T08:00:00Z",
            "end_time": "2026-07-31T08:00:10Z",
        }
    ]


def test_evidence_assistant_attached_alert_resolves_authoritative_selected_clip() -> None:
    alert_id, digest, job_id = "4" * 64, "5" * 64, "6" * 64
    raw_alert = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "incident_id": alert_id,
        "event_type": "restricted_zone.entry",
        "asset_uri": f"selected-clip://{alert_id}.mp4",
        "clip_start_time": "2026-07-31T08:00:00Z",
        "clip_end_time": "2026-07-31T08:00:10Z",
        "clip_sha256": digest,
    }
    queued = _assistant_job(job_id, alert_id, digest, status="queued_caption")

    def respond(call):
        if call["path"] == "/api/v1/alerts?size=500":
            return 200, {"alerts": [raw_alert]}
        if call["path"] == "/api/v1/jobs":
            return 200, {"jobs": []}
        if call["path"] == "/api/v1/summaries":
            return 201, queued
        raise AssertionError(f"unexpected call: {call}")

    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    client = _RecordingJsonClient(respond)
    adapter.client = client
    _, value = adapter.evidence_assistant(
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "question": "họ đang làm gì",
            "context": {
                "type": "alert",
                "alert_id": alert_id,
                "alert_source": "hybrid",
                "asset_id": alert_id,
                "camera_id": "cam-01",
                "start_time": "2026-07-31T08:00:00Z",
                "end_time": "2026-07-31T08:00:10Z",
            },
            "idempotency_key": "assistant-alert-unit",
        },
        "req-assistant-alert",
    )
    assert value["scope"]["asset_ids"] == [alert_id]
    assert value["scope"]["camera_id"] == "cam-01"
    assert client.calls[-1]["payload"]["assets"][0]["asset_uri"] == (
        f"selected-clip://{alert_id}.mp4"
    )
    assert all(call["service_id"] != "search" for call in client.calls)


def test_evidence_assistant_completed_summary_calls_grounded_qa() -> None:
    asset_id, digest, job_id = "7" * 64, "8" * 64, "9" * 64
    completed = _assistant_job(job_id, asset_id, digest, status="completed")
    answer = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "status": "completed",
        "grounded": True,
        "answer": "Hai người đang làm việc tại bàn.",
        "answer_source": "evidence_extract_fallback",
        "evidence": [],
    }

    def respond(call):
        if call["path"] == f"/api/v1/jobs/{job_id}":
            return 200, completed
        if call["path"] == "/api/v1/qa":
            return 200, answer
        raise AssertionError(f"unexpected call: {call}")

    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    client = _RecordingJsonClient(respond)
    adapter.client = client
    _, value = adapter.evidence_assistant(
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "question": "họ đang làm gì",
            "context": {"type": "summary", "summary_id": job_id},
            "idempotency_key": "assistant-summary-unit",
        },
        "req-assistant-summary",
    )
    assert value["workflow"] == "grounded_qa"
    assert value["grounded"] is True
    assert [call["path"] for call in client.calls] == [
        f"/api/v1/jobs/{job_id}",
        "/api/v1/qa",
    ]
    assert client.calls[-1]["payload"] == {
        "summary_id": job_id,
        "question": "họ đang làm gì",
    }


def test_evidence_assistant_standby_is_structured_and_never_fabricates() -> None:
    asset_id, digest, job_id = "a" * 64, "b" * 64, "c" * 64
    completed = _assistant_job(job_id, asset_id, digest, status="completed")

    def respond(call):
        if call["path"] == f"/api/v1/jobs/{job_id}":
            return 200, completed
        if call["path"] == "/api/v1/qa":
            raise workspace.WorkspaceError(
                503,
                "provider_standby",
                "summarization",
                True,
                "provider standby",
            )
        raise AssertionError(f"unexpected call: {call}")

    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    client = _RecordingJsonClient(respond)
    adapter.client = client
    _, value = adapter.evidence_assistant(
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "question": "họ đang làm gì",
            "context": {"type": "summary", "summary_id": job_id},
        },
        "req-assistant-standby",
    )
    assert value["status"] == "provider_standby"
    assert value["required_profile"] == "summary_reasoning"
    assert value["operator_action"]["requires_confirmation"] is True
    assert value["answered"] is False
    assert "answer" not in value
    assert all(call["service_id"] != "search" for call in client.calls)


def test_summary_action_keeps_job_queued_during_provider_startup() -> None:
    job_id = "d" * 64
    queued = _assistant_job(job_id, "e" * 64, "f" * 64, status="queued_caption")

    def respond(call):
        if call["method"] == "POST":
            raise workspace.WorkspaceError(
                503,
                "provider_standby",
                "summarization",
                True,
                "provider standby",
            )
        if call["path"] == f"/api/v1/jobs/{job_id}":
            return 200, queued
        raise AssertionError(f"unexpected call: {call}")

    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    client = _RecordingJsonClient(respond)
    adapter.client = client
    status, value = adapter.summary_action(job_id, "caption", "req-caption-standby")
    assert status == 202
    assert value["status"] == "queued_caption"
    assert value["workflow"] == "waiting_for_provider"
    assert value["required_profile"] == "summary_caption"
    assert [call["method"] for call in client.calls] == ["POST", "GET"]


def test_vss_ui_chat_ignores_browser_selected_upstream_and_keeps_gpu_standby() -> None:
    adapter = vss_ui.VSSUIAdapter(_VSSUIWorkspace(), "http://127.0.0.1:39511")
    answer = adapter.chat(
        {
            "messages": [{"role": "user", "content": "GPU status"}],
            "chatCompletionURL": "http://untrusted.invalid/private",
        },
        "request-chat",
    )
    assert "admission-controlled" in answer
    assert "does not start a model automatically" in answer
    assert "untrusted.invalid" not in answer


def test_vss_ui_chat_uses_admitted_nemotron_and_strips_reasoning(tmp_path: Path) -> None:
    lease_root = tmp_path / "admission"
    lease_root.mkdir()
    (lease_root / "phase13.lease").write_text(
        json.dumps({"status": "granted", "profile": "summarization_llm"}),
        encoding="utf-8",
    )
    adapter = vss_ui.VSSUIAdapter(
        workspace.WorkspaceAdapter(ROOT / "config/cameras/cameras.hybrid.json"),
        "http://127.0.0.1:39511",
        admission_root=lease_root,
    )
    client = _RecordingJsonClient(
        lambda call: (
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": "internal draft</think>\n\nNemotron đang hoạt động."
                        }
                    }
                ]
            },
        )
    )
    adapter.workspace.client = client
    answer = adapter.chat(
        {"messages": [{"role": "user", "content": "LLM nào đang chạy?"}]},
        "request-admitted-chat",
    )
    assert answer == "Nemotron đang hoạt động."
    assert client.calls[0]["service_id"] == "nemotron"
    assert client.calls[0]["path"] == "/v1/chat/completions"
    assert client.calls[0]["payload"]["model"] == "nvidia/nvidia-nemotron-nano-9b-v2"


def test_workspace_report_normalization_hides_paths_and_uses_same_origin_downloads() -> None:
    report_id = "e" * 64
    summary_id = "f" * 64
    incident_id = "1" * 64
    client = _RecordingJsonClient(
        lambda _call: (
            201,
            {
                "schema_version": "1.0.0",
                "store_id": "store-001",
                "report_id": report_id,
                "report_type": "incident",
                "json_path": "/runtime/private/report.json",
                "markdown_path": "/runtime/private/report.md",
            },
        )
    )
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    adapter.client = client
    status, value = adapter.create_report(
        "incident",
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "summary_ids": [summary_id],
            "incident_id": incident_id,
            "idempotency_key": "report-unit-1",
        },
        "req-report",
    )
    assert status == 201
    assert "json_path" not in value
    assert "markdown_path" not in value
    assert value["downloads"] == {
        "json": {
            "href": f"/api/v1/workspace/reports/{report_id}.json",
            "content_type": "application/json",
        },
        "markdown": {
            "href": f"/api/v1/workspace/reports/{report_id}.md",
            "content_type": "text/markdown",
        },
    }
    assert client.calls[0]["path"] == "/api/v1/reports/incident"
    assert client.calls[0]["payload"] == {
        "summary_ids": [summary_id],
        "incident_id": incident_id,
    }


def test_selected_media_requires_allowlisted_exact_id_and_parses_single_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    monkeypatch.setattr(adapter, "_refresh_media_allowlist", lambda _request_id: None)
    with pytest.raises(workspace.WorkspaceError) as raised:
        adapter.open_media("a" * 64, "req-media")
    assert (raised.value.status, raised.value.code) == (
        404,
        "media_not_allowlisted",
    )
    with pytest.raises(workspace.WorkspaceError) as raised:
        adapter.open_media("../private", "req-traversal")
    assert (raised.value.status, raised.value.code) == (404, "media_not_found")

    assert workspace.parse_single_range("", 100) is None
    assert workspace.parse_single_range("bytes=0-9", 100) == (0, 9)
    assert workspace.parse_single_range("bytes=10-", 100) == (10, 99)
    assert workspace.parse_single_range("bytes=-10", 100) == (90, 99)
    assert workspace.parse_single_range("bytes=95-200", 100) == (95, 99)
    for invalid in ("items=0-1", "bytes=0-1,4-5", "bytes=-0", "bytes=100-"):
        with pytest.raises(workspace.WorkspaceError) as raised:
            workspace.parse_single_range(invalid, 100)
        assert raised.value.status == 416


def test_summary_creation_binds_allowlisted_media_provenance() -> None:
    media_id = "2" * 64
    content_sha256 = "3" * 64
    job_id = "4" * 64
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    adapter._remember_media(
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "camera_id": "cam-01",
            "asset_uri": f"selected-clip://{media_id}.mp4",
            "clip_start_time": "2026-07-31T08:00:00Z",
            "clip_end_time": "2026-07-31T08:00:10Z",
            "clip_sha256": content_sha256,
        }
    )
    adapter._remember_media(
        {
            "camera_id": "cam-01",
            "evidence": [
                {
                    "asset_uri": f"selected-clip://{media_id}.mp4",
                    "start_time": "2026-07-31T08:00:02Z",
                    "end_time": "2026-07-31T08:00:04Z",
                }
            ],
        }
    )
    assert adapter._media_record(media_id)["conflict"] is False
    client = _RecordingJsonClient(
        lambda _call: (
            201,
            {
                "schema_version": "1.0.0",
                "store_id": "store-001",
                "camera_id": "cam-01",
                "job_id": job_id,
                "status": "queued_caption",
                "chunks": [],
            },
        )
    )
    adapter.client = client
    payload = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "source_type": "selected_video",
        "window_start": "2026-07-31T08:00:00Z",
        "window_end": "2026-07-31T08:00:10Z",
        "assets": [
            {
                "asset_uri": f"selected-clip://{media_id}.mp4",
                "asset_sha256": content_sha256,
                "start_time": "2026-07-31T08:00:00Z",
                "end_time": "2026-07-31T08:00:10Z",
            }
        ],
    }
    status, value = adapter.create_summary_job(payload, "req-summary")
    assert status == 201
    assert value["job_id"] == job_id
    assert len(client.calls) == 1

    relabeled = deepcopy(payload)
    relabeled["camera_id"] = "cam-02"
    with pytest.raises(workspace.WorkspaceError) as raised:
        adapter.create_summary_job(relabeled, "req-relabel")
    assert raised.value.code == "camera_not_found"

    shifted = deepcopy(payload)
    shifted["assets"][0]["start_time"] = "2026-07-31T08:00:01Z"
    with pytest.raises(workspace.WorkspaceError) as raised:
        adapter.create_summary_job(shifted, "req-shift")
    assert raised.value.code == "media_provenance_mismatch"
    assert len(client.calls) == 1


def test_workspace_cross_site_fetch_metadata_is_rejected() -> None:
    handler = object.__new__(service.Handler)
    handler.headers = {
        "Sec-Fetch-Site": "cross-site",
        "Origin": "https://attacker.invalid",
    }
    assert handler._same_origin_request() is False
    handler.headers = {
        "Sec-Fetch-Site": "same-origin",
        "Origin": "http://127.0.0.1:39510",
    }
    assert handler._same_origin_request() is True

    class NeverOpenedWorkspace:
        @staticmethod
        def open_live(*_args):
            raise AssertionError("cross-site request reached live upstream")

    handler.runtime = SimpleNamespace(
        requests=0,
        workspace=NeverOpenedWorkspace(),
    )
    handler.path = (
        f"{service.WORKSPACE_PREFIX}/cameras/cam-01/live.mjpeg"
    )
    handler.headers = {
        "Sec-Fetch-Site": "cross-site",
        "Origin": "https://attacker.invalid",
    }
    handler._request_id = lambda: "req-cross-site"
    responses: list[tuple[int, object]] = []
    handler._json = lambda status, value: responses.append((status, value))
    service.Handler.do_GET(handler)
    assert responses[0][0] == 403


def test_cross_origin_workspace_post_returns_rejection_without_handler_crash() -> None:
    handler = object.__new__(service.Handler)
    handler.runtime = SimpleNamespace(requests=0)
    handler.path = f"{service.WORKSPACE_PREFIX}/search"
    handler._request_id = lambda: "req-cross-site-post"
    handler._authorized = lambda _permission, _request_id: {
        "subject": "operator-1",
        "role": "operator",
    }

    def reject_body():
        raise ValueError("cross-origin mutation rejected")

    handler._read_json = reject_body
    responses: list[tuple[int, object]] = []
    handler._json = lambda status, value: responses.append((status, value))

    service.Handler.do_POST(handler)
    assert responses == [
        (
            400,
            {
                "status": "rejected",
                "request_id": "req-cross-site-post",
            },
        )
    ]


@pytest.mark.parametrize(
    ("error_status", "expected_outcome"),
    [(400, "rejected"), (503, "failed")],
)
def test_failed_workspace_mutation_is_audited(
    error_status: int, expected_outcome: str
) -> None:
    handler = object.__new__(service.Handler)
    audits: list[dict[str, object]] = []
    responses: list[tuple[int, object]] = []
    identity = {"subject": "operator-1", "role": "operator"}

    class RejectingWorkspace:
        @staticmethod
        def feedback(*_args):
            raise service.WorkspaceError(
                error_status,
                "invalid_feedback",
                "request",
                False,
                "Feedback is invalid.",
            )

    handler.runtime = SimpleNamespace(
        requests=0,
        workspace=RejectingWorkspace(),
    )
    handler.path = (
        f"{service.WORKSPACE_PREFIX}/alerts/hybrid/{'5' * 64}/feedback"
    )
    handler._request_id = lambda: "req-audit"
    handler._authorized = lambda _permission, _request_id: identity
    handler._read_json = lambda: {"feedback_label": "invalid"}
    handler._workspace_audit = lambda *args, **kwargs: audits.append(
        {"args": args, **kwargs}
    )
    handler._workspace_error = lambda error, request_id: responses.append(
        (error.status, request_id)
    )

    service.Handler.do_POST(handler)
    assert responses == [(error_status, "req-audit")]
    assert len(audits) == 1
    assert audits[0]["args"][1] == "workspace.alert.feedback"
    assert audits[0]["mutating"] is True
    assert audits[0]["outcome"] == expected_outcome


def test_analytics_update_wraps_and_validates_upstream_identity() -> None:
    current = yaml.safe_load(
        (ROOT / "config/analytics/cam-01.behavior.yaml").read_text(
            encoding="utf-8"
        )
    )
    proposed = deepcopy(current)
    proposed["config_version"] = 2
    proposed["queue"]["length_threshold"] = 2
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )
    adapter.analytics_config = lambda _request_id: current
    client = _RecordingJsonClient(
        lambda _call: (200, {"status": "updated", "config_version": 2})
    )
    adapter.client = client
    status, value = adapter.update_analytics_config(proposed, "req-config")
    assert status == 200
    assert value["schema_version"] == "1.0.0"
    assert value["store_id"] == "store-001"
    assert value["camera_id"] == "cam-01"
    assert value["config_version"] == 2

    adapter.client = _RecordingJsonClient(
        lambda _call: (200, {"status": "updated", "config_version": 99})
    )
    with pytest.raises(workspace.WorkspaceError) as raised:
        adapter.update_analytics_config(proposed, "req-config-mismatch")
    assert (raised.value.status, raised.value.code) == (
        502,
        "invalid_analytics_update",
    )


def test_structured_log_uses_a_process_lock() -> None:
    assert isinstance(service.LOG_LOCK, type(threading.Lock()))
    source = (API / "service.py").read_text(encoding="utf-8")
    assert "with LOG_LOCK:" in source


def test_service_security_headers_keep_media_same_origin_and_disable_objects() -> None:
    source = (API / "service.py").read_text(encoding="utf-8")
    assert "default-src 'self'" in source
    assert "script-src 'self'" in source
    assert "style-src 'self'" in source
    assert "img-src 'self' data:" in source
    assert "media-src 'self'" in source
    assert "connect-src 'self'" in source
    assert "object-src 'none'" in source
    assert "frame-ancestors 'none'" in source
    assert 'self.send_header("X-Frame-Options", "DENY")' in source
    assert "Access-Control-Allow-Origin" not in source


def test_gpu_profile_catalog_is_task_oriented_and_excludes_shell_details() -> None:
    profiles = gpu_control.public_profiles()
    identifiers = {profile["id"] for profile in profiles}
    assert identifiers == {
        "realtime",
        "alert_verification",
        "direct_alerts",
        "video_index",
        "object_index",
        "search_assistant",
        "search_critic",
        "summary_caption",
        "summary_reasoning",
    }
    assert all("start_script" not in profile for profile in profiles)
    assert all("stop_script" not in profile for profile in profiles)
    assert all("lease" not in profile for profile in profiles)


def test_model_power_controls_expose_only_safe_public_fields(tmp_path: Path) -> None:
    models = gpu_control.public_model_controls()
    assert {model["id"] for model in models} == {"llm", "vlm"}
    assert all("start_script" not in model for model in models)
    assert all("lease" not in model for model in models)

    admission = tmp_path / "admission"
    admission.mkdir()
    (admission / "phase13-llm.lease").write_text(
        '{"status":"granted","profile":"summarization_llm"}', encoding="utf-8"
    )
    snapshot = gpu_control.model_control_snapshot(tmp_path / "control", admission)
    states = {model["id"]: model for model in snapshot["models"]}
    assert states["llm"]["state"] == "online"
    assert states["llm"]["enabled"] is True
    assert states["vlm"]["state"] == "offline"
    assert snapshot["rtcv_policy"] == "upload_only"


def test_model_power_command_requires_confirmation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="confirmation"):
        gpu_control.enqueue_model_power(
            tmp_path / "control",
            model_id="llm",
            enabled=True,
            identity={"subject": "operator-1", "role": "operator"},
            request_id="request-model-power",
            confirmed=False,
        )
    command = gpu_control.enqueue_model_power(
        tmp_path / "control",
        model_id="llm",
        enabled=True,
        identity={"subject": "operator-1", "role": "operator"},
        request_id="request-model-power-ok",
        confirmed=True,
    )
    assert command["action"] == "set_model_power"
    assert command["model_id"] == "llm"
    assert command["enabled"] is True


def test_gpu_worker_model_power_does_not_restore_rtcv(tmp_path: Path) -> None:
    admission = tmp_path / "admission"
    admission.mkdir()
    calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []

    def runner(command, env=None, **_kwargs):
        script = Path(command[1]).name
        args = tuple(command[2:])
        calls.append((script, args, {key: env[key] for key in (env or {}) if key.startswith("START_")}))
        if script == "start-phase13-llm.sh":
            (admission / "phase13-llm.lease").write_text(
                '{"status":"granted","profile":"summarization_llm"}', encoding="utf-8"
            )
        return gpu_worker.subprocess.CompletedProcess(command, 0, "", "")

    message = gpu_worker.model_power_transition("llm", True, admission, runner=runner)
    assert "online" in message
    assert calls == [
        (
            "start-phase13-llm.sh",
            (),
            {"START_PHASE13_LLM_RESTORE_RTCV": "false"},
        )
    ]


def test_gpu_command_requires_confirmation_and_serializes_queue(tmp_path: Path) -> None:
    control_root = tmp_path / "control"
    identity = {"subject": "operator-1", "role": "operator"}
    with pytest.raises(ValueError, match="confirmation"):
        gpu_control.enqueue_switch(
            control_root,
            target_profile="video_index",
            identity=identity,
            request_id="request-1",
            confirmed=False,
        )

    command = gpu_control.enqueue_switch(
        control_root,
        target_profile="video_index",
        identity=identity,
        request_id="request-2",
        confirmed=True,
    )
    assert command["status"] == "queued"
    assert command["requested_by"] == "operator-1"
    assert (control_root / "requests" / f"{command['command_id']}.json").is_file()
    with pytest.raises(RuntimeError, match="already active"):
        gpu_control.enqueue_switch(
            control_root,
            target_profile="summary_caption",
            identity=identity,
            request_id="request-3",
            confirmed=True,
        )


def test_vlm_test_command_queues_serialized_host_workflow(tmp_path: Path) -> None:
    control_root = tmp_path / "control"
    command = gpu_control.enqueue_vlm_test(
        control_root,
        job_id="c" * 64,
        identity={"subject": "operator-1", "role": "operator"},
        request_id="request-vlm-test",
    )
    assert command["action"] == "run_vlm_test"
    assert command["target_profile"] == "vlm_test"
    assert command["workflow"] == "upload_rtcv_vlm"
    assert command["status"] == "queued"
    assert (control_root / "requests" / f"{command['command_id']}.json").is_file()


def test_managed_gpu_command_is_scoped_to_summary_job_and_auto_restore(tmp_path: Path) -> None:
    control_root = tmp_path / "control"
    identity = {"subject": "operator-1", "role": "operator"}
    job_id = "a" * 64
    command = gpu_control.enqueue_switch(
        control_root,
        target_profile="summary_caption",
        identity=identity,
        request_id="request-managed",
        confirmed=True,
        managed_job_id=job_id,
        auto_restore=True,
    )
    assert command["managed_job_id"] == job_id
    assert command["auto_restore"] is True
    with pytest.raises(ValueError, match="summary profiles"):
        gpu_control.enqueue_switch(
            tmp_path / "bad-control",
            target_profile="video_index",
            identity=identity,
            request_id="request-bad-profile",
            confirmed=True,
            managed_job_id=job_id,
            auto_restore=True,
        )


def test_gpu_worker_waits_for_caption_checkpoint(tmp_path: Path) -> None:
    job_root = tmp_path / "jobs"
    job_root.mkdir()
    job_id = "b" * 64
    (job_root / f"{job_id}.json").write_text(
        json.dumps({"job_id": job_id, "status": "queued_summary"}),
        encoding="utf-8",
    )
    assert gpu_worker.wait_for_managed_job(
        job_root,
        job_id,
        "summary_caption",
        poll_seconds=0.01,
        timeout_seconds=0.2,
    ) == "queued_summary"


def test_gpu_worker_uses_allowlisted_scripts_and_stops_active_profile(tmp_path: Path) -> None:
    admission = tmp_path / "admission"
    admission.mkdir()
    lease = admission / "phase13-vlm.lease"
    lease.write_text('{"status":"granted","profile":"summarization_vlm"}', encoding="utf-8")
    calls: list[str] = []

    def runner(command, **_kwargs):
        script = Path(command[1]).name
        calls.append(script)
        if script == "stop-phase13-vlm.sh":
            lease.unlink()
        return gpu_worker.subprocess.CompletedProcess(command, 0, "", "")

    message = gpu_worker.transition("video_index", admission, runner=runner)
    assert calls == ["stop-phase13-vlm.sh", "start-phase12-rt-embedding.sh"]
    assert "Lập chỉ mục video" in message


def test_gpu_worker_fails_closed_for_unknown_active_lease(tmp_path: Path) -> None:
    admission = tmp_path / "admission"
    admission.mkdir()
    (admission / "unknown.lease").write_text(
        '{"status":"granted","profile":"unknown"}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="no safe stop mapping"):
        gpu_worker.transition("realtime", admission)


def test_compose_is_loopback_only_and_has_no_raw_or_docker_socket() -> None:
    text = (ROOT / "deploy/compose/phase15.compose.yml").read_text(encoding="utf-8")
    assert "network_mode: host" in text
    assert 'HTTP_HOST: "127.0.0.1"' in text
    assert 'HTTP_PORT: "39510"' in text
    assert "\n    ports:" not in text
    assert "http://127.0.0.1:39510/health/ready" in text
    assert "runtime/gpu-admission:/runtime/admission:ro" in text
    assert "runtime/raw-video" not in text
    assert "/var/run/docker.sock" not in text
    assert "/dev/nvidia" not in text
    assert "model-cache" not in text
    assert "model_cache" not in text
    assert ".secrets/phase15:/run/secrets/phase15:ro" in text


def test_openapi_and_rbac_contracts_are_versioned() -> None:
    openapi = json.loads(
        (ROOT / "schemas/openapi/phase15.openapi.json").read_text(encoding="utf-8")
    )
    rbac = json.loads(
        (ROOT / "config/security/phase15-rbac.json").read_text(encoding="utf-8")
    )
    assert openapi["openapi"] == "3.1.0"
    assert openapi["info"]["version"] == "1.5.0"
    assert openapi["servers"] == [
        {
            "url": "http://127.0.0.1:39510",
            "description": "Loopback-only unified workspace",
        }
    ]
    assert rbac["schema_version"] == "1.0.0"
    assert rbac["mutating_runtime_tools"] == "gpu_profile_switch_only"
    assert "/api/v1/session" in openapi["paths"]
    assert "/api/v1/gpu-control" in openapi["paths"]
    assert "/api/v1/gpu-control/models" in openapi["paths"]
    assert "/api/v1/gpu-control/models/{model_id}" in openapi["paths"]
    assert "/api/v1/gpu-control/commands" in openapi["paths"]
    assert "/api/chat" in openapi["paths"]
    assert "/compat/agent/api/v1/search" in openapi["paths"]
    assert "/compat/mdx/incidents" in openapi["paths"]
    assert "/compat/vst/api/v1/storage/file/{stream_id}/url" in openapi["paths"]


def test_openapi_covers_every_unified_workspace_handler() -> None:
    openapi = json.loads(
        (ROOT / "schemas/openapi/phase15.openapi.json").read_text(encoding="utf-8")
    )
    expected = {
        "/api/v1/workspace": {"get"},
            "/api/v1/workspace/cameras": {"get"},
            "/api/v1/workspace/stream-sources": {"get", "post"},
            "/api/v1/workspace/stream-sources/{source_id}": {"delete"},
        "/api/v1/workspace/cameras/{camera_id}/state": {"get"},
        "/api/v1/workspace/cameras/{camera_id}/live.mjpeg": {"get"},
        "/api/v1/workspace/cameras/{camera_id}/thumbnail.jpg": {"get"},
        "/api/v1/workspace/analytics/state": {"get"},
        "/api/v1/workspace/analytics/events": {"get"},
        "/api/v1/workspace/analytics/config": {"get", "put"},
        "/api/v1/workspace/incidents/state": {"get"},
        "/api/v1/workspace/alerts": {"get"},
        "/api/v1/workspace/alerts/{source}/{alert_id}": {"delete"},
        "/api/v1/workspace/alerts/{source}/{alert_id}/feedback": {"post"},
        "/api/v1/workspace/alerts/{source}/{alert_id}/restore": {"post"},
        "/api/v1/workspace/media/{media_id}.mp4": {"get"},
        "/api/v1/workspace/search/state": {"get"},
        "/api/v1/workspace/search": {"post"},
        "/api/v1/workspace/assistant/evidence": {"post"},
        "/api/v1/workspace/summaries/state": {"get"},
        "/api/v1/workspace/summaries/jobs": {"get", "post"},
        "/api/v1/workspace/summaries/jobs/{job_id}": {"get"},
        "/api/v1/workspace/summaries/jobs/{job_id}/actions/{action}": {"post"},
        "/api/v1/workspace/summaries/qa": {"post"},
        "/api/v1/workspace/reports": {"get"},
        "/api/v1/workspace/reports/{report_target}": {"get", "post"},
        "/api/v1/workspace/reports/{report_id}/media/{media_id}.mp4": {"get"},
        "/api/v1/workspace/uploads": {"get", "post"},
        "/api/v1/workspace/uploads/{asset_id}": {"delete"},
        "/api/v1/workspace/uploads/{asset_id}/restore": {"post"},
        "/api/v1/workspace/uploads/{asset_id}/media": {"get"},
        "/api/v1/workspace/vlm-tests/state": {"get"},
        "/api/v1/workspace/vlm-tests/jobs": {"get"},
        "/api/v1/workspace/vlm-tests/jobs/{job_id}": {"get"},
        "/api/v1/workspace/vlm-tests/jobs/{job_id}/media": {"get"},
        "/api/v1/workspace/vlm-tests/uploads": {"post"},
        "/api/v1/workspace/vlm-tests/jobs/{job_id}/candidate": {"post"},
        "/api/v1/workspace/vlm-tests/jobs/{job_id}/launch": {"post"},
        "/api/v1/workspace/vlm-tests/jobs/{job_id}/rtcv-start": {"post"},
        "/api/v1/workspace/vlm-tests/jobs/{job_id}/save": {"post"},
        "/api/v1/workspace/vlm-tests/realtime/candidates": {"get"},
        "/api/v1/workspace/vlm-tests/realtime/{incident_id}/launch": {"post"},
        "/api/v1/workspace/vlm-tests/store": {"get"},
        "/api/v1/workspace/vlm-tests/store/{asset_id}/media": {"get"},
        "/api/v1/workspace/vlm-tests/store/{asset_id}/launch": {"post"},
    }
    actual = {
        path: {
            method
            for method in item
            if method in {"get", "post", "put", "patch", "delete"}
        }
        for path, item in openapi["paths"].items()
        if path.startswith("/api/v1/workspace")
    }
    assert actual == expected
    media = openapi["paths"]["/api/v1/workspace/media/{media_id}.mp4"]["get"]
    assert {"200", "206", "416"}.issubset(media["responses"])
    assert "video/mp4" in media["responses"]["206"]["content"]
    search_schema = openapi["components"]["schemas"]["SearchRequest"]
    assert search_schema["additionalProperties"] is False
    assert search_schema["properties"]["route"]["enum"] == [
        "auto",
        "action",
        "attribute",
        "fusion",
        "image",
    ]
    assert (
        openapi["components"]["schemas"]["SummaryQaRequest"][
            "additionalProperties"
        ]
        is False
    )


def test_openapi_references_resolve_and_operation_ids_are_unique() -> None:
    openapi = json.loads(
        (ROOT / "schemas/openapi/phase15.openapi.json").read_text(encoding="utf-8")
    )
    operation_ids: list[str] = []

    def walk(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/"):
                target = openapi
                for component in reference[2:].split("/"):
                    target = target[component.replace("~1", "/").replace("~0", "~")]
                assert target is not None
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(openapi)
    for path in openapi["paths"].values():
        for method, operation in path.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                operation_ids.append(operation["operationId"])
    assert len(operation_ids) == len(set(operation_ids))


def test_alert_soft_delete_restore_is_persistent_idempotent_and_retains_evidence(
    tmp_path: Path,
) -> None:
    alert_id = "a" * 64
    asset_id = "b" * 64
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json",
        governance_root=tmp_path,
    )
    alert = {
        "id": alert_id,
        "source": "hybrid",
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "event_type": "restricted_zone.entry",
        "start_time": "2026-07-29T09:09:54.747Z",
        "asset_uri": f"selected-clip://{asset_id}.mp4",
    }
    adapter._find_alert = lambda source, identifier, request_id: alert
    adapter._alert_reference_summary = lambda value, request_id: {
        "counts": {"reports": 1, "summaries": 1, "alerts": 1},
        "types": ["reports", "summaries", "alerts"],
    }
    payload = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "idempotency_key": "delete-one",
    }
    status, deleted = adapter.delete_alert("hybrid", alert_id, payload, "request-1")
    assert status == 200
    assert deleted["status"] == "deleted"
    assert deleted["evidence_retained"] is True
    assert deleted["references"]["counts"]["reports"] == 1
    _, replay = adapter.delete_alert("hybrid", alert_id, payload, "request-2")
    assert replay["status"] == "already_deleted"
    assert replay["idempotent_replay"] is True
    assert (tmp_path / "alert-tombstones.json").is_file()
    _, restored = adapter.restore_alert(
        "hybrid",
        alert_id,
        {**payload, "idempotency_key": "restore-one"},
        "request-3",
    )
    assert restored["status"] == "restored"
    assert restored["evidence_retained"] is True
    assert adapter._alert_tombstones() == {}


def test_report_media_is_exact_report_scoped_and_cross_store_fails(
    tmp_path: Path,
) -> None:
    report_id = "c" * 64
    allowed_id = "d" * 64
    denied_id = "e" * 64
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json",
        governance_root=tmp_path,
    )
    adapter.reports = lambda request_id: {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "reports": [
            {
                "report_id": report_id,
                "store_id": "store-001",
                "evidence": [
                    {"asset_uri": f"selected-clip://{allowed_id}.mp4"}
                ],
            }
        ],
    }
    marker = object()
    adapter.open_media = lambda identifier, request_id: (
        marker if identifier == allowed_id else None
    )
    assert adapter.open_report_media(report_id, allowed_id, "request-1") is marker
    with pytest.raises(workspace.WorkspaceError) as denied:
        adapter.open_report_media(report_id, denied_id, "request-2")
    assert denied.value.status == 403
    assert denied.value.code == "report_media_scope_denied"
    adapter.reports = lambda request_id: {
        "schema_version": "1.0.0",
        "store_id": "store-002",
        "reports": [
            {
                "report_id": report_id,
                "store_id": "store-002",
                "evidence": [
                    {"asset_uri": f"selected-clip://{allowed_id}.mp4"}
                ],
            }
        ],
    }
    with pytest.raises(workspace.WorkspaceError) as cross_store:
        adapter.open_report_media(report_id, allowed_id, "request-3")
    assert cross_store.value.status == 404


def test_uploaded_asset_validation_quarantine_restore_and_path_traversal(
    tmp_path: Path,
) -> None:
    store = media_intake.Store(tmp_path)
    body = (
        b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isom"
        b"\x00\x00\x00\x08moovavc1\x00\x00\x00\x08mdat"
        + b"\x00" * 32
    )
    record, created = store.create(
        "operator-clip.mp4", "video/mp4", body, "upload-one"
    )
    assert created is True
    assert record["summary_ready"] is True
    assert record["asset_uri"] == f"uploaded-media://{record['asset_id']}.mp4"
    assert (tmp_path / "active" / f"{record['asset_id']}.mp4").is_file()
    assert (tmp_path / "prepared" / f"{record['asset_id']}.mp4").is_file()
    quarantined = store.mutate(record["asset_id"], False)
    assert quarantined["deleted"] is True
    assert not (tmp_path / "prepared" / f"{record['asset_id']}.mp4").exists()
    restored = store.mutate(record["asset_id"], True)
    assert restored["deleted"] is False
    assert (tmp_path / "prepared" / f"{record['asset_id']}.mp4").is_file()
    with pytest.raises(ValueError, match="invalid_filename"):
        store.create("../escape.mp4", "video/mp4", body, "upload-two")
    with pytest.raises(ValueError, match="unsupported_content_type"):
        store.create("clip.mp4", "application/octet-stream", body, "upload-three")


def test_uploaded_asset_delete_preserves_summary_references(tmp_path: Path) -> None:
    asset_id = "f" * 64
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json",
        governance_root=tmp_path,
    )
    adapter.summary_jobs = lambda request_id: {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "jobs": [
            {
                "job_id": "a" * 64,
                "chunks": [
                    {"asset_uri": f"uploaded-media://{asset_id}.mp4"}
                ],
            }
        ],
    }
    with pytest.raises(workspace.WorkspaceError) as conflict:
        adapter.mutate_upload(
            asset_id,
            {
                "schema_version": "1.0.0",
                "store_id": "store-001",
                "idempotency_key": "delete-referenced-upload",
            },
            "request-1",
            restore=False,
        )
    assert conflict.value.status == 409
    assert conflict.value.code == "asset_reference_conflict"


def test_search_standby_names_fixed_required_profile() -> None:
    adapter = workspace.WorkspaceAdapter(
        ROOT / "config/cameras/cameras.hybrid.json"
    )

    def standby(*args, **kwargs):
        raise workspace.WorkspaceError(
            503,
            "provider_standby",
            "search",
            True,
            "standby",
        )

    adapter.client.json = standby
    with pytest.raises(workspace.WorkspaceError) as error:
        adapter.search(
            {
                "schema_version": "1.0.0",
                "store_id": "store-001",
                "query": "person entering",
                "mode": "manual",
                "route": "fusion",
                "camera_ids": ["cam-01"],
                "top_k": 5,
                "source_type": "selected_clip",
                "critic_verification": False,
                "critic_top_k": 0,
            },
            "request-1",
        )
    public = error.value.public("request-1")
    assert public["required_profile"] == "video_index"
    assert public["capability"] == "fusion video search"
    assert public["queued"] is False
    assert public["operator_action"]["requires_confirmation"] is True
