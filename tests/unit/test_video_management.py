from __future__ import annotations

import importlib.util
import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_PATH = ROOT / "services/video-management/contracts.py"
SPEC = importlib.util.spec_from_file_location("video_contracts", CONTRACTS_PATH)
assert SPEC and SPEC.loader
contracts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contracts)
secure_probe = runpy.run_path(
    str(ROOT / "services/video-management/secure_rtsp_probe.py"),
    run_name="secure_rtsp_probe",
)


def registry() -> dict:
    return json.loads(
        (ROOT / "config/cameras/cameras.simulated.json").read_text(encoding="utf-8")
    )


def test_ten_stable_cameras_and_utc_contract() -> None:
    data = registry()
    contracts.validate_registry(data)
    assert [camera["camera_id"] for camera in data["cameras"]] == [
        f"cam-{index:02d}" for index in range(1, 11)
    ]
    assert data["store"]["backend_timestamps"] == "UTC"


def test_committed_registry_contains_secret_refs_not_rtsp_credentials() -> None:
    text = (ROOT / "config/cameras/cameras.simulated.json").read_text(encoding="utf-8")
    assert "rtsp://" not in text
    assert "password" not in text.lower()
    for camera in registry()["cameras"]:
        assert camera["main_stream"]["uri_secret_ref"].startswith("camera://")
        assert camera["ai_substream"]["uri_secret_ref"].startswith("camera://")


def test_plaintext_connection_fields_are_rejected() -> None:
    data = registry()
    data["cameras"][0]["main_stream"]["url"] = "rtsp://user:pass@example.invalid/main"
    with pytest.raises(contracts.ContractError, match="plaintext connection data"):
        contracts.validate_registry(data)


def test_reconnect_backoff_is_bounded() -> None:
    assert contracts.reconnect_delays(1, 30, 2, 8) == [1, 2, 4, 8, 16, 30, 30, 30]


def test_video_compose_has_no_ai_service_or_destructive_volume() -> None:
    text = (ROOT / "deploy/compose/video-management.compose.yml").read_text(encoding="utf-8")
    forbidden = ("vss-rt-cv", "vss-rt-vlm", "vss-rt-embed", "nemotron", "cosmos3")
    assert all(value not in text for value in forbidden)
    assert "runtime/raw-video" in text
    assert "down -v" not in text


def test_secure_probe_removes_userinfo_from_rtsp_request_uri() -> None:
    assert (
        secure_probe["_public_uri"](
            "rtsp://operator:p%40ss@camera.example:8554/Streaming/Channels/102"
        )
        == "rtsp://camera.example:8554/Streaming/Channels/102"
    )


def test_secure_probe_parses_digest_challenge_without_exposing_nonce() -> None:
    scheme, parameters = secure_probe["_challenge_parameters"](
        'Digest realm="camera", nonce="opaque-value", algorithm=MD5'
    )
    assert scheme == "digest"
    assert parameters["realm"] == "camera"
    assert parameters["algorithm"] == "MD5"


def test_active_registry_contains_only_physical_camera_without_credentials() -> None:
    path = ROOT / "config/cameras/cameras.hybrid.json"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    contracts.validate_registry(data)
    cam01 = data["cameras"][0]
    assert data["source_mode"] == "physical_camera_only"
    assert len(data["cameras"]) == 1
    assert cam01["camera_id"] == "cam-01"
    assert cam01["main_stream"]["uri_secret_ref"].startswith("camera://keyring/")
    assert cam01["main_stream"]["codec"] == "h265"
    assert cam01["main_stream"]["width"] == 2560
    assert cam01["main_stream"]["height"] == 1440
    assert cam01["main_stream"]["fps"] == 25
    assert cam01["ai_substream"]["codec"] == "h264"
    assert cam01["ai_substream"]["width"] == 1280
    assert cam01["ai_substream"]["height"] == 720
    assert "rtsp://" not in text
