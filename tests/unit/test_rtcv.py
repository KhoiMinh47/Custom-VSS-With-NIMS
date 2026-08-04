from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_PATH = ROOT / "services/rt-cv/contracts.py"
SPEC = importlib.util.spec_from_file_location("rtcv_contracts", CONTRACTS_PATH)
assert SPEC and SPEC.loader
contracts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contracts)


def test_phase07_is_one_camera_and_720p_ai_substream_only() -> None:
    analytics = yaml.safe_load(
        (ROOT / "config/analytics/cam-01.yaml").read_text(encoding="utf-8")
    )
    assert analytics["store_id"] == "store-001"
    assert analytics["camera_id"] == "cam-01"
    assert analytics["source"]["role"] == "ai_substream"
    assert analytics["source"]["secret_ref"].startswith("camera://")
    assert analytics["source"]["codec"] == "h264"
    assert analytics["source"]["width"] == 1280
    assert analytics["source"]["height"] == 720


def test_compose_uses_exact_pinned_rt_cv_image_and_no_other_model() -> None:
    text = (ROOT / "deploy/compose/rtcv.compose.yml").read_text(encoding="utf-8")
    assert "vss-rt-cv:3.2.1@sha256:1a8b987" in text
    assert "device_ids: [\"0\"]" in text
    assert "vss-rt-vlm" not in text
    assert "vss-rt-embed" not in text
    assert "nemotron" not in text
    assert "cosmos3" not in text
    assert "runtime/raw-video" not in text


def test_rt_cv_registration_uses_logical_channel_102() -> None:
    start_script = (ROOT / "scripts/start-rtcv.sh").read_text(encoding="utf-8")
    relay = (ROOT / "services/rt-cv/secure_rtsp_relay.py").read_text(
        encoding="utf-8"
    )
    assert "rtsp://rtsp-relay:39554/Streaming/Channels/102" in start_script
    assert 'relay_path = "/Streaming/Channels/102"' in relay


def test_committed_phase07_files_have_no_rtsp_credential() -> None:
    paths = [
        ROOT / "config/deepstream",
        ROOT / "config/analytics",
        ROOT / "services/rt-cv",
        ROOT / "deploy/compose/rtcv.compose.yml",
    ]
    for path in paths:
        files = path.rglob("*") if path.is_dir() else [path]
        for file in files:
            if file.is_file() and file.suffix in {".py", ".md", ".yaml", ".yml", ".txt"}:
                text = file.read_text(encoding="utf-8")
                assert "rtsp://user:" not in text
                assert "password@" not in text


def test_ai_input_uses_physical_channel_102_and_preserves_userinfo_only_in_memory() -> None:
    source = "rtsp://operator:p%40ss@camera.invalid/Streaming/Channels/102"
    assert (
        contracts.derive_ai_input_uri(source)
        == "rtsp://operator:p%40ss@camera.invalid/Streaming/Channels/102"
    )


def test_relay_prefers_physical_h264_and_keeps_mainstream_fallback() -> None:
    relay = (ROOT / "services/rt-cv/secure_rtsp_relay.py").read_text(
        encoding="utf-8"
    )
    assert 'source_kind = "physical_ai_substream"' in relay
    assert 'input_codec = "h264"' in relay
    assert 'source_kind = "vios_mainstream_fallback"' in relay
    assert '"rtph264depay" if self.input_codec == "h264"' in relay


def test_line_crossing_sign_change_and_roi() -> None:
    polygon = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert contracts.point_in_polygon((0.25, 0.5), polygon)
    start = (0.5, 0.0)
    end = (0.5, 1.0)
    assert contracts.line_side((0.25, 0.5), start, end) > 0
    assert contracts.line_side((0.75, 0.5), start, end) < 0


def test_metadata_contract_has_stable_fields_track_id_and_utc() -> None:
    timestamp = contracts.utc_iso(1_700_000_000, 123_000_000)
    objects = [
        {
            "track_id": "42",
            "type": "Person",
            "confidence": 0.91,
            "bbox": {"left": 0.1, "top": 0.2, "right": 0.4, "bottom": 0.8},
        }
    ]
    document = contracts.frame_document(
        {"id": "frame-1", "version": "4.1", "sensorId": "cam-01"},
        timestamp,
        objects,
    )
    assert document["schema_version"] == "1.0.0"
    assert document["store_id"] == "store-001"
    assert document["camera_id"] == "cam-01"
    assert document["model_version"] == "1.0.2"
    assert document["@timestamp"].endswith("Z")
    assert document["payload"]["objects"][0]["track_id"] == "42"
    json.dumps(document)
