from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_phase10_hybrid_is_the_default_alerting_mode() -> None:
    config = yaml.safe_load(
        (ROOT / "config/runtime/single-gpu-poc.yaml").read_text(encoding="utf-8")
    )
    alerting = config["alerting"]
    assert alerting["default_mode"] == "hybrid_candidate_verification"
    assert alerting["hybrid_candidate_verification"]["phase"] == "PHASE-10"
    assert alerting["hybrid_candidate_verification"]["trigger"] == "behavior_candidate"
    assert (
        alerting["hybrid_candidate_verification"]["local_vlm"]
        == "admitted_event_driven_window"
    )


def test_direct_rt_vlm_is_explicit_and_bounded_to_cam_01() -> None:
    config = yaml.safe_load(
        (ROOT / "config/runtime/single-gpu-poc.yaml").read_text(encoding="utf-8")
    )
    direct = config["alerting"]["direct_rt_vlm"]
    assert direct["phase"] == "PHASE-11"
    assert direct["startup"] == "explicit_only"
    assert direct["enabled_by_default"] is False
    assert direct["selected_cameras"] == ["cam-01"]
    assert direct["max_concurrent_cameras"] == 1
    assert "gpu_admission_lease" in direct["requires"]
    assert "rtcv_serialization" in direct["requires"]


def test_default_start_restores_rt_cv_and_never_starts_direct_rt_vlm() -> None:
    script = (ROOT / "scripts/start-default-alerting.sh").read_text(encoding="utf-8")
    assert "phase11_stop_gpu_services" in script
    assert "start-rtcv.sh" in script
    assert "start-behavior-analytics.sh" in script
    assert "start-phase10.sh" in script
    assert "start-phase11-direct.sh" not in script
    assert "runtime/raw-video" not in script


def test_default_health_rejects_direct_gpu_services_and_stale_leases() -> None:
    script = (ROOT / "scripts/healthcheck-default-alerting.sh").read_text(
        encoding="utf-8"
    )
    assert "ntc-vss-phase11-rt-vlm" in script
    assert "ntc-vss-retail-poc-gpu-poc-cosmos3-1" in script
    assert "direct-rt-vlm.lease" in script
    assert "local-vlm.lease" in script
