from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_vlm_modules():
    contracts_spec = importlib.util.spec_from_file_location(
        "vlm_test_contracts_unit", ROOT / "services/vlm-test/contracts.py"
    )
    assert contracts_spec and contracts_spec.loader
    contracts = importlib.util.module_from_spec(contracts_spec)
    sys.modules["contracts"] = contracts
    contracts_spec.loader.exec_module(contracts)
    service_spec = importlib.util.spec_from_file_location(
        "vlm_test_service_unit", ROOT / "services/vlm-test/service.py"
    )
    assert service_spec and service_spec.loader
    service = importlib.util.module_from_spec(service_spec)
    service_spec.loader.exec_module(service)
    return contracts, service


def valid_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + b"moov" + b"mdat" + b"avc1" + b"x" * 40


def candidate() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "event_id": "b" * 64,
        "event_type": "queue.threshold",
        "model_id": "ntc-retail-traffic-rules",
        "model_version": "1.0.0",
        "start_time": "2026-08-04T01:00:00.000Z",
        "end_time": "2026-08-04T01:00:05.000Z",
        "candidate": True,
        "evaluation": False,
        "evidence": {"kind": "rt_cv_metadata"},
    }


def test_upload_stays_out_of_store_until_explicit_save(tmp_path: Path) -> None:
    contracts, service = load_vlm_modules()
    store = service.TestStore(tmp_path / "vlm-test")
    body = valid_mp4()

    status, job = store.create_upload("clip.mp4", "video/mp4", body, "upload-1")
    assert status == 201
    assert job["storage_state"] == "staging_only"
    assert job["status"] == "queued_for_rtcv"
    assert store.assets()["assets"] == []
    assert (tmp_path / "vlm-test" / "staging" / f'{job["job_id"]}.mp4').is_file()
    _, running = store.update_rtcv_status(job["job_id"], "running", "RT-CV started")
    assert running["status"] == "running_rtcv"
    status_retry, same_job = store.create_upload("clip.mp4", "video/mp4", body, "upload-1")
    assert status_retry == 200
    assert same_job["job_id"] == job["job_id"]

    with pytest.raises(contracts.VlmTestError, match="rtcv_file_batch_unavailable"):
        store.launch(job["job_id"], "http://127.0.0.1:39120")

    _, ready = store.add_candidate(job["job_id"], candidate())
    assert ready["rtcv_status"] == "candidate_created"
    _, completed_rtcv = store.update_rtcv_status(job["job_id"], "completed", "RT-CV candidate created")
    assert completed_rtcv["status"] == "ready_to_launch"
    with store.lock:
        value = store._load()
        persisted = value["jobs"][job["job_id"]]
        persisted.update(
            {
                "status": "completed",
                "vlm_status": "completed",
                "verdict": "confirmed",
                "confidence": 0.9,
                "reason": "visible queue",
                "vlm_result": {
                    "schema_version": "1.0.0",
                    "store_id": "store-001",
                    "status": "completed",
                    "verdict": "confirmed",
                },
            }
        )
        store._save(value)

    save_status, asset = store.save_after_vlm(job["job_id"])
    assert save_status == 201
    assert asset["storage_state"] == "stored_after_vlm"
    assert asset["asset_uri"].startswith("vlm-store://")
    assert len(store.assets()["assets"]) == 1
    assert list((tmp_path / "vlm-test" / "store").glob("*.mp4"))


def test_store_retest_creates_a_new_vlm_job_without_a_new_store_copy(tmp_path: Path) -> None:
    _contracts, service = load_vlm_modules()
    store = service.TestStore(tmp_path / "vlm-test")
    _, job = store.create_upload("clip.mp4", "video/mp4", valid_mp4(), "upload-2")
    with store.lock:
        value = store._load()
        persisted = value["jobs"][job["job_id"]]
        persisted.update(
            {
                "status": "completed",
                "vlm_status": "completed",
                "verdict": "rejected",
                "confidence": 0.8,
                "reason": "not visible",
                "vlm_result": {"status": "completed", "verdict": "rejected"},
                "candidate_event": candidate(),
            }
        )
        store._save(value)
    _, asset = store.save_after_vlm(job["job_id"])
    _, retest = store.create_store_retest(asset["asset_id"])
    assert retest["source_type"] == "store_retest"
    assert retest["asset_uri"].startswith("vlm-store://")
    assert len(store.assets()["assets"]) == 1
