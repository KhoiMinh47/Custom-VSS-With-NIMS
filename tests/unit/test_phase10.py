from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


incident_contracts = load(
    "phase10_incident_contracts", ROOT / "services/incidents/contracts.py"
)
alert_contracts = load(
    "phase10_alert_contracts", ROOT / "services/alert-verification/contracts.py"
)
admission = load(
    "phase10_admission", ROOT / "services/gpu-admission-controller/admission.py"
)
media_preparation = load(
    "phase10_media_preparation", ROOT / "services/incidents/media_preparation.py"
)


def behavior_event(*, candidate: bool = True, evaluation: bool = False) -> dict:
    return {
        "@timestamp": "2026-07-29T06:00:00.000Z",
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "correlation_id": "corr-1",
        "event_id": "event-1",
        "event_type": "restricted_zone.entry",
        "model_id": "ntc-retail-traffic-rules",
        "model_version": "1.0.0",
        "start_time": "2026-07-29T06:00:00.000Z",
        "end_time": "2026-07-29T06:00:02.000Z",
        "confidence": 0.9,
        "candidate": candidate,
        "evaluation": evaluation,
        "evidence": {"kind": "rt_cv_metadata", "frame_id": "123"},
        "payload": {"zone_id": "restricted"},
    }


def ready_incident() -> dict:
    incident = incident_contracts.build_incident(
        behavior_event(),
        pre_roll_seconds=4,
        post_roll_seconds=5,
        created_at=datetime(2026, 7, 29, 6, 0, tzinfo=UTC),
    )
    return incident_contracts.mark_clip_ready(
        incident,
        asset_uri=f'selected-clip://{incident["incident_id"]}.mp4',
        clip_sha256="a" * 64,
        clip_bytes=1024,
    )


def test_candidate_filter_excludes_evaluation_and_non_candidate() -> None:
    assert incident_contracts.is_candidate(behavior_event())
    assert not incident_contracts.is_candidate(behavior_event(candidate=False))
    assert not incident_contracts.is_candidate(behavior_event(evaluation=True))


def test_incident_clip_window_is_utc_with_pre_and_post_roll() -> None:
    incident = incident_contracts.build_incident(
        behavior_event(),
        pre_roll_seconds=4,
        post_roll_seconds=5,
        created_at=datetime(2026, 7, 29, 6, 0, tzinfo=UTC),
    )
    assert incident["clip_start_time"] == "2026-07-29T05:59:56.000Z"
    assert incident["clip_end_time"] == "2026-07-29T06:00:07.000Z"
    assert incident["store_id"] == "store-001"
    assert incident["camera_id"] == "cam-01"
    assert incident["status"] == "preparing_clip"


def test_selected_clip_contract_is_stable_and_deterministic() -> None:
    first = ready_incident()
    second = ready_incident()
    assert first["incident_id"] == second["incident_id"]
    assert first["asset_uri"].startswith("selected-clip://")
    assert first["evidence"]["kind"] == "vios_selected_clip"
    assert first["clip_sha256"] == "a" * 64


def test_structured_verdict_json_and_cosmos_answer_fallback() -> None:
    assert alert_contracts.parse_verdict(
        '<think>x</think>{"verdict":"confirmed","confidence":0.91,"reason":"visible"}'
    ) == ("confirmed", 0.91, "visible")
    verdict, confidence, _ = alert_contracts.parse_verdict("<answer>NO</answer>")
    assert verdict == "rejected"
    assert confidence == 0.5
    assert alert_contracts.parse_verdict("uncertain") == ("uncertain", 0.0, "uncertain")
    assert alert_contracts.parse_verdict("ambiguous")[0] == "uncertain"


def test_verified_alert_keeps_versions_and_utc_contract() -> None:
    alert = alert_contracts.build_verified(
        ready_incident(),
        verdict="uncertain",
        confidence=0.2,
        reason="clip ambiguous",
        retry_count=3,
        latency_ms=1200,
    )
    assert alert["status"] == "needs_review"
    assert alert["verifier_model_id"] == "nvidia/cosmos3-nano-reasoner"
    assert alert["verifier_model_version"] == "bf16-final"
    assert alert["prompt_version"] == "1.0.0"
    assert alert["@timestamp"].endswith("Z")


def test_feedback_confusion_matrix() -> None:
    matrix = alert_contracts.confusion_matrix(
        [
            {"verdict": "confirmed", "feedback_label": "confirmed"},
            {"verdict": "confirmed", "feedback_label": "rejected"},
            {"verdict": "uncertain"},
        ]
    )
    assert matrix["confirmed"]["confirmed"] == 1
    assert matrix["confirmed"]["rejected"] == 1
    assert sum(sum(row.values()) for row in matrix.values()) == 2


def test_admission_denies_rtcv_and_low_headroom() -> None:
    allowed, reason = admission.decision({"ntc-vss-phase07-rtcv"}, 48000, 38000)
    assert not allowed and "conflicting" in reason
    allowed, reason = admission.decision(set(), 48000, 1000)
    assert not allowed and "15 percent" in reason
    assert admission.decision(set(), 48000, 38000)[0]


def test_retry_runs_three_times_before_uncertain_dlq_path() -> None:
    calls: list[int] = []
    pauses: list[int] = []

    def fail() -> str:
        calls.append(1)
        raise RuntimeError("temporary VLM outage")

    response, retry_count, error = alert_contracts.retry_operation(
        fail, attempts=3, pause=pauses.append
    )
    assert response is None
    assert retry_count == 3
    assert error == "RuntimeError"
    assert len(calls) == 3
    assert pauses == [1, 2]


def test_compose_preserves_plane_isolation_and_no_continuous_vlm() -> None:
    text = (ROOT / "deploy/compose/phase10.compose.yml").read_text(encoding="utf-8")
    assert "runtime/raw-video" not in text
    assert "vss-rt-vlm" not in text
    assert "always_on" not in text
    assert "selected-clip" not in text
    assert "NGC_API_KEY" not in text


def test_ui_and_prompt_do_not_contain_credentials() -> None:
    service = (ROOT / "services/alert-verification/service.py").read_text(encoding="utf-8")
    prompt = json.loads(
        (ROOT / "config/prompts/alert-verification/verification.json").read_text(
            encoding="utf-8"
        )
    )
    combined = service + json.dumps(prompt)
    assert "rtsp://" not in combined.lower()
    assert "camera password" not in combined.lower()
    assert "ngc_api_key" not in combined.lower()
    assert "feedback_label" in service


def test_media_preparation_accepts_only_incident_mp4_names() -> None:
    valid = "a" * 64 + ".mp4"
    assert media_preparation.safe_clip(valid).name == valid
    for invalid in ("../camera.mp4", "camera.mp4", "a" * 64 + ".mkv"):
        try:
            media_preparation.safe_clip(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe clip name accepted: {invalid}")
    source = (
        ROOT / "services/incidents/media_preparation.py"
    ).read_text(encoding="utf-8")
    assert "width=1280,height=720" in source
    assert "runtime/raw-video" not in source
