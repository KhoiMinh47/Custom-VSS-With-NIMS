from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contracts = load(
    "phase11_contracts", ROOT / "services/rt-vlm-alert/contracts.py"
)
admission = load(
    "phase11_admission", ROOT / "services/gpu-admission-controller/admission.py"
)


def test_direct_verdict_contract_parses_json_and_fallbacks() -> None:
    assert contracts.parse_verdict(
        '{"verdict":"confirmed","confidence":0.92,"reason":"person visible"}'
    ) == ("confirmed", 0.92, "person visible")
    assert contracts.parse_verdict("<answer>NO</answer>")[0] == "rejected"
    assert contracts.parse_verdict("ambiguous")[0] == "uncertain"


def test_direct_alert_keeps_stable_versions_and_utc() -> None:
    alert = contracts.build_direct_alert(
        request_id="request-1",
        chunk_index=3,
        camera_id="cam-01",
        start_time="2026-07-29T07:00:00.000Z",
        end_time="2026-07-29T07:00:08.000Z",
        response='{"verdict":"rejected","confidence":0.8,"reason":"empty"}',
        model_version="bf16-final",
        info={
            "chunkLatencyMs": "1250.4",
            "decodeLatencyMs": "200",
            "vlmLatencyMs": "900",
            "frameCount": "8",
            "inputTokens": "1200",
            "outputTokens": "20",
        },
    )
    assert alert["schema_version"] == "1.0.0"
    assert alert["store_id"] == "store-001"
    assert alert["camera_id"] == "cam-01"
    assert alert["model_id"] == "nvidia/cosmos3-nano-reasoner"
    assert alert["model_version"] == "bf16-final"
    assert alert["prompt_version"] == "1.0.0"
    assert alert["verdict"] == "rejected"
    assert alert["latency_ms"] == 1250
    assert alert["frame_count"] == 8
    assert alert["@timestamp"].endswith("Z")
    assert len(alert["direct_alert_id"]) == 64


def test_direct_alert_rejects_more_than_selected_camera() -> None:
    try:
        contracts.build_direct_alert(
            request_id="request-1",
            chunk_index=0,
            camera_id="cam-02",
            start_time="2026-07-29T07:00:00.000Z",
            end_time="2026-07-29T07:00:08.000Z",
            response="no",
            model_version="bf16-final",
            info={},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Phase 11 accepted an unapproved second camera")


def test_direct_confusion_matrix_excludes_unlabeled() -> None:
    matrix = contracts.confusion_matrix(
        [
            {"verdict": "confirmed", "feedback_label": "rejected"},
            {"verdict": "rejected", "feedback_label": "rejected"},
            {"verdict": "uncertain"},
        ]
    )
    assert matrix["confirmed"]["rejected"] == 1
    assert matrix["rejected"]["rejected"] == 1
    assert sum(sum(row.values()) for row in matrix.values()) == 2


def test_prompt_has_bounded_chunk_and_fixed_sampling() -> None:
    value = json.loads(
        (ROOT / "config/prompts/rt-vlm-alert/person-presence.json").read_text(
            encoding="utf-8"
        )
    )
    assert value["camera_id"] == "cam-01"
    assert value["chunk_duration_seconds"] == 8
    assert value["chunk_overlap_seconds"] == 0
    assert value["frame_sampling"] == {
        "mode": "fixed_frames_per_chunk",
        "frames": 5,
    }
    assert value["schema_version"] == value["prompt_version"] == "1.0.0"


def test_compose_is_one_camera_external_nim_and_plane_isolated() -> None:
    text = (ROOT / "deploy/compose/phase11.compose.yml").read_text(encoding="utf-8")
    assert "sha256:5403e0c8fa8b149e7ad15ab1b063b78d610e7a50297dba6ca550ac5cc5ef9504" in text
    assert "VLM_MODEL_TO_USE: openai-compat" in text
    assert "NUM_VLM_PROCS: \"1\"" in text
    assert "runtime/raw-video" not in text
    assert "vss.rt-cv.frames" not in text
    assert "vss.behavior.events" not in text
    assert "NGC_API_KEY" not in text
    assert "camera_password" not in text.lower()
    rtcv_gate = (ROOT / "scripts/rtcv-lib.sh").read_text(encoding="utf-8")
    assert "ntc-vss-phase11-rt-vlm-results" in rtcv_gate


def test_registration_uses_only_credential_free_internal_stream() -> None:
    text = (ROOT / "scripts/register-phase11-stream.py").read_text(encoding="utf-8")
    assert "rtsp://rtsp-relay:39554/Streaming/Channels/102" in text
    assert "camera_id\": \"cam-01\"" in text
    assert "cam-02" not in text
    assert "username" not in text.lower()
    assert "password" not in text.lower()


def test_admission_supports_direct_profile_without_weakening_gate() -> None:
    allowed, reason = admission.decision({"ntc-vss-phase07-rtcv"}, 48935, 38000)
    assert not allowed and "conflicting" in reason
    assert admission.decision(set(), 48935, 38000)[0]
    source = (
        ROOT / "services/gpu-admission-controller/admission.py"
    ).read_text(encoding="utf-8")
    assert "direct_rt_vlm" in source
    assert "0.15" in source


def test_stop_path_preserves_cache_images_and_data() -> None:
    text = (ROOT / "scripts/stop-phase11-direct.sh").read_text(encoding="utf-8")
    forbidden = ("down -v", "volume rm", "docker rmi", "prune", "rm -rf")
    assert not any(item in text for item in forbidden)
    assert "start-rtcv.sh" in text


def test_resource_metrics_api_remains_read_only_but_dashboard_is_operator_focused() -> None:
    collector = (
        ROOT / "services/rt-vlm-alert/collector.py"
    ).read_text(encoding="utf-8")
    compose = (
        ROOT / "deploy/compose/phase11.compose.yml"
    ).read_text(encoding="utf-8")
    assert 'path == "/api/v1/resources"' in collector
    dashboard = collector.split('DASHBOARD_HTML = """', 1)[1].split('"""', 1)[0]
    assert "Runtime resources" not in dashboard
    assert "Host CPU" not in dashboard
    assert "Latency/frames" not in dashboard
    assert "Feedback" not in dashboard
    assert "Asia/Ho_Chi_Minh" in dashboard
    assert "<th>Verdict</th><th>Reason</th>" in dashboard
    assert "../../runtime/phase11-monitor:/opt/ntc/runtime:ro" in compose
    assert "/var/run/docker.sock" not in compose
