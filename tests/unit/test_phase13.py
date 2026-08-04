from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SUMMARIZATION = ROOT / "services/summarization"
REPORTING = ROOT / "services/reporting"
sys.path.insert(0, str(SUMMARIZATION))
sys.path.insert(0, str(REPORTING))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contracts = load("phase13_contracts", SUMMARIZATION / "contracts.py")
reporting = load("phase13_reporting", REPORTING / "reporting.py")
admission = load(
    "phase13_admission", ROOT / "services/gpu-admission-controller/admission.py"
)


def load_summary_service(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "contracts", contracts)
    monkeypatch.setitem(sys.modules, "reporting", reporting)
    providers = load(
        "phase13_providers_for_service", SUMMARIZATION / "providers.py"
    )
    monkeypatch.setitem(sys.modules, "providers", providers)
    return load("phase13_service_for_test", SUMMARIZATION / "service.py")


def clip_root(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "selected"
    root.mkdir()
    name = "a" * 64 + ".mp4"
    (root / name).write_bytes(b"\x00\x00\x00\x18ftypmp42phase13")
    return root, f"selected-clip://{name}"


def payload(uri: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "camera_id": "cam-01",
        "source_type": "selected_video",
        "window_start": "2026-07-29T09:09:48.647Z",
        "window_end": "2026-07-29T09:09:58.480Z",
        "assets": [
            {
                "asset_uri": uri,
                "start_time": "2026-07-29T09:09:48.647Z",
                "end_time": "2026-07-29T09:09:58.480Z",
            }
        ],
    }


def caption(job: dict) -> dict:
    return contracts.normalize_caption(
        {
            "caption": "A person is visible near a desk.",
            "events": [
                {
                    "description": "A person walks near a desk.",
                    "start_seconds": 1,
                    "end_seconds": 4,
                    "importance": "normal",
                }
            ],
            "observed_entities": ["person", "desk"],
            "observed_actions": ["walking"],
        },
        job["chunks"][0],
        "cam-01",
    )


def test_selected_clip_job_has_stable_contract_and_versions(tmp_path: Path) -> None:
    root, uri = clip_root(tmp_path)
    first = contracts.build_job(payload(uri), root)
    second = contracts.build_job(payload(uri), root)
    assert first["job_id"] == second["job_id"]
    assert first["store_id"] == "store-001"
    assert first["camera_id"] == "cam-01"
    assert first["status"] == "queued_caption"
    assert first["caption_model_id"] == "nvidia/cosmos3-nano-reasoner"
    assert first["summary_model_id"] == "nvidia/nvidia-nemotron-nano-9b-v2"
    assert first["evidence_policy"]["raw_archive_scanned"] is False


def test_summary_request_rejects_unsupported_schema(tmp_path: Path) -> None:
    root, uri = clip_root(tmp_path)
    value = payload(uri)
    value["schema_version"] = "2.0.0"
    with pytest.raises(ValueError, match="schema_version"):
        contracts.build_job(value, root)


@pytest.mark.parametrize(
    "uri",
    [
        "file:///recordings/cam-01.mp4",
        "selected-clip://../escape.mp4",
        "selected-clip://clip.mp4",
    ],
)
def test_non_selected_or_unsafe_media_is_rejected(tmp_path: Path, uri: str) -> None:
    root, _ = clip_root(tmp_path)
    with pytest.raises((ValueError, FileNotFoundError)):
        contracts.build_job(payload(uri), root)


def test_caption_events_are_bounded_and_cite_selected_evidence(tmp_path: Path) -> None:
    root, uri = clip_root(tmp_path)
    job = contracts.build_job(payload(uri), root)
    value = caption(job)
    event = value["events"][0]
    assert event["start_time"] == "2026-07-29T09:09:49.647Z"
    assert event["end_time"] == "2026-07-29T09:09:52.647Z"
    assert event["asset_uri"] == uri
    assert value["model_version"] == "bf16-final"


def test_unselected_time_is_unobserved_not_no_event(tmp_path: Path) -> None:
    root, uri = clip_root(tmp_path)
    value = payload(uri)
    value["source_type"] = "time_window"
    value["window_start"] = "2026-07-29T09:00:00.000Z"
    value["window_end"] = "2026-07-29T10:00:00.000Z"
    job = contracts.build_job(value, root)
    gaps = contracts.coverage_gaps(job)
    assert len(gaps) == 2
    assert {gap["status"] for gap in gaps} == {"unobserved"}
    assert all("no selected media evidence" in gap["reason"] for gap in gaps)


def test_summary_filters_unknown_event_ids_and_keeps_evidence(tmp_path: Path) -> None:
    root, uri = clip_root(tmp_path)
    job = contracts.build_job(payload(uri), root)
    job["chunks"][0]["caption"] = caption(job)
    events = contracts.all_events(job)
    value = contracts.normalize_summary(
        {
            "executive_summary": "Unsupported text",
            "event_ids": ["invented"],
            "incident_event_ids": ["invented"],
        },
        events,
        job=job,
        level=1,
    )
    assert value["synthesis_source"] == "deterministic_grounded_fallback"
    assert value["event_ids"] == [events[0]["event_id"]]
    assert value["evidence"][0]["asset_uri"] == uri
    assert value["incident_event_ids"] == []


def test_qa_refuses_without_matching_or_cited_evidence(tmp_path: Path) -> None:
    root, uri = clip_root(tmp_path)
    job = contracts.build_job(payload(uri), root)
    job["chunks"][0]["caption"] = caption(job)
    events = contracts.all_events(job)
    assert contracts.select_question_evidence("What color was the delivery truck?", events) == []
    value = contracts.grounded_answer(
        "What happened?",
        {"answer": "A truck arrived", "event_ids": ["invented"]},
        events,
    )
    assert value["answer"] == "không đủ dữ liệu"
    assert value["status"] == "insufficient_evidence"
    assert value["grounded"] is False
    assert value["refused"] is True
    assert value["evidence"] == []


def test_qa_filters_camera_and_utc_time_before_lexical_selection(
    tmp_path: Path,
) -> None:
    root, uri = clip_root(tmp_path)
    job = contracts.build_job(payload(uri), root)
    job["chunks"][0]["caption"] = caption(job)
    events = contracts.all_events(job)
    question = (
        "Trong khoảng thời gian 10:30 đến 10:40 UTC tại camera cam-01 có xảy ra "
        "sự kiện đáng chú ý nào không? Nếu có, mô tả người/vật/hành động và "
        "timestamp; nếu không đủ bằng chứng, phải trả lời không quan sát được."
    )
    assert (
        contracts.select_question_evidence(
            question,
            events,
            default_window_start=job["window_start"],
            default_window_end=job["window_end"],
        )
        == []
    )
    scoped_refusal = contracts.refusal(
        question,
        "no selected-media evidence matches the requested camera and UTC time",
        answer=contracts.UNOBSERVED_TEXT,
    )
    assert scoped_refusal["answer"] == "không quan sát được"
    assert scoped_refusal["grounded"] is False
    assert scoped_refusal["refused"] is True

    matching_question = (
        "Từ 09:09 đến 09:10 UTC tại camera cam-01 có sự kiện nào đáng chú ý?"
    )
    assert contracts.select_question_evidence(
        matching_question,
        events,
        default_window_start=job["window_start"],
        default_window_end=job["window_end"],
    ) == events

    wrong_camera = (
        "Từ 09:09 đến 09:10 UTC tại camera cam-02 có sự kiện nào đáng chú ý?"
    )
    assert (
        contracts.select_question_evidence(
            wrong_camera,
            events,
            default_window_start=job["window_start"],
            default_window_end=job["window_end"],
        )
        == []
    )

    ambiguous_time = "What happened at 09:09 UTC at camera cam-01?"
    assert (
        contracts.select_question_evidence(
            ambiguous_time,
            events,
            default_window_start=job["window_start"],
            default_window_end=job["window_end"],
        )
        == []
    )


def test_grounded_qa_returns_camera_timestamp_and_asset(tmp_path: Path) -> None:
    root, uri = clip_root(tmp_path)
    job = contracts.build_job(payload(uri), root)
    job["chunks"][0]["caption"] = caption(job)
    event = contracts.all_events(job)[0]
    value = contracts.grounded_answer(
        "What visible activity appears?",
        {
            "answer": "A person walks near a desk.",
            "event_ids": [event["event_id"]],
            "insufficient_evidence": False,
        },
        [event],
    )
    assert value["status"] == "answered"
    assert value["grounded"] is True
    assert value["refused"] is False
    assert value["evidence"][0]["camera_id"] == "cam-01"
    assert value["evidence"][0]["start_time"].endswith("Z")
    assert value["evidence"][0]["asset_uri"] == uri


def test_interrupted_jobs_resume_from_safe_queue() -> None:
    captioning = {"status": "captioning", "restart_count": 0}
    summarizing = {"status": "summarizing", "restart_count": 2}
    assert contracts.recover_interrupted_job(captioning)["status"] == "queued_caption"
    assert contracts.recover_interrupted_job(summarizing)["status"] == "queued_summary"
    assert captioning["restart_count"] == 1
    assert summarizing["restart_count"] == 3


def test_incident_shift_daily_reports_require_and_preserve_evidence(tmp_path: Path) -> None:
    root, uri = clip_root(tmp_path)
    job = contracts.build_job(payload(uri), root)
    job["chunks"][0]["caption"] = caption(job)
    events = contracts.all_events(job)
    summary = contracts.normalize_summary(
        {
            "executive_summary": "A person walks near a desk.",
            "event_ids": [events[0]["event_id"]],
            "incident_event_ids": [events[0]["event_id"]],
        },
        events,
        job=job,
        level=1,
    )
    for report_type in ("incident", "shift", "daily"):
        report = reporting.build_report(
            report_type, [summary], incident_id="inc-1"
        )
        assert report["store_id"] == "store-001"
        assert report["camera_ids"] == ["cam-01"]
        assert report["evidence"][0]["asset_uri"] == uri
        assert report["model_version"] == "1.0.0"
        markdown = reporting.render_markdown(report)
        assert "Evidence timeline" in markdown
        assert uri in markdown
    with pytest.raises(ValueError):
        reporting.build_report("daily", [])


def test_admission_supports_both_phase13_serialized_profiles() -> None:
    assert admission.decision(set(), 48935, 40000)[0]
    assert not admission.decision({"ntc-vss-phase07-rtcv"}, 48935, 40000)[0]
    assert not admission.decision(
        set(), 48935, 37000, profile="summarization_vlm"
    )[0], "the VLM budget must preserve the 5 GiB cross-project reserve"
    assert admission.decision(
        set(), 48935, 38000, profile="summarization_vlm"
    )[0]
    source = (
        ROOT / "services/gpu-admission-controller/admission.py"
    ).read_text(encoding="utf-8")
    assert '"summarization_vlm"' in source
    assert '"summarization_llm"' in source
    assert "DEFAULT_RESERVED_MEMORY_MIB = 5 * 1024" in source


def test_compose_mounts_only_selected_media_read_only() -> None:
    text = (ROOT / "deploy/compose/phase13.compose.yml").read_text(encoding="utf-8")
    assert "runtime/incidents/clips:/selected-clips:ro" in text
    assert "runtime/raw-video" not in text
    assert "poc-cosmos3:8000/v1" in text
    assert "poc-nemotron:8000/v1" in text


def test_prompts_and_report_policy_are_versioned() -> None:
    for path in (
        ROOT / "config/prompts/summarization/caption.json",
        ROOT / "config/prompts/summarization/summary.json",
        ROOT / "config/prompts/summarization/qa.json",
        ROOT / "config/prompts/reporting/report-policy.json",
    ):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["schema_version"] == "1.0.0"


def test_report_listing_is_safe_and_newest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = load_summary_service(monkeypatch)
    store = service.JobStore(tmp_path)
    old_id = "a" * 64
    new_id = "b" * 64
    old_report = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "report_id": old_id,
        "report_type": "shift",
        "created_at": "2026-07-30T01:00:00.000Z",
    }
    new_report = {
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "report_id": new_id,
        "report_type": "daily",
        "created_at": "2026-07-30T02:00:00.000Z",
    }
    (store.reports_dir / f"{old_id}.json").write_text(
        json.dumps(old_report), encoding="utf-8"
    )
    (store.reports_dir / f"{new_id}.json").write_text(
        json.dumps(new_report), encoding="utf-8"
    )
    (store.reports_dir / f"{new_id}.md").write_text(
        "# Daily report\n", encoding="utf-8"
    )
    (store.reports_dir / "not-a-report.json").write_text(
        json.dumps(new_report), encoding="utf-8"
    )
    mismatch_id = "c" * 64
    (store.reports_dir / f"{mismatch_id}.json").write_text(
        json.dumps(new_report), encoding="utf-8"
    )
    malformed_id = "d" * 64
    (store.reports_dir / f"{malformed_id}.json").write_text(
        "{invalid", encoding="utf-8"
    )
    escaped_id = "e" * 64
    escaped_report = {
        **new_report,
        "report_id": escaped_id,
    }
    escaped_target = tmp_path / "outside-report.json"
    escaped_target.write_text(json.dumps(escaped_report), encoding="utf-8")
    (store.reports_dir / f"{escaped_id}.json").symlink_to(escaped_target)

    reports = store.list_reports()

    assert [value["report_id"] for value in reports] == [new_id, old_id]
    assert reports[0]["downloads"]["json"]["href"] == (
        f"/api/v1/reports/{new_id}.json"
    )
    assert reports[0]["downloads"]["markdown"]["href"] == (
        f"/api/v1/reports/{new_id}.md"
    )
    assert reports[1]["downloads"]["markdown"] is None


@pytest.mark.parametrize(
    "name",
    (
        "../report.json",
        "a" * 64,
        "A" * 64 + ".json",
        "a" * 64 + ".txt",
        "a" * 63 + ".json",
    ),
)
def test_report_download_name_rejects_non_allowlisted_targets(
    tmp_path: Path, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = load_summary_service(monkeypatch)
    store = service.JobStore(tmp_path)
    with pytest.raises(ValueError, match="invalid report name"):
        store.report_path(name)
