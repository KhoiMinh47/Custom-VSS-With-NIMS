from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "services/video-management/ai_overlay.py"
SPEC = importlib.util.spec_from_file_location("ai_overlay", MODULE_PATH)
assert SPEC and SPEC.loader
ai_overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai_overlay)


def metrics(frame_number: int = 100) -> dict:
    return {
        "metrics-info": {
            "stream-stats": [
                {
                    "sensor_id": "cam-01",
                    "fps": 9.75,
                    "frame_number": frame_number,
                }
            ]
        }
    }


def metadata(
    *,
    age: float = 0.1,
    objects: list[dict] | None = None,
    frame: bool = True,
) -> dict:
    return {
        "ready": True,
        "last_message_age_seconds": age,
        "line_crossings": 2,
        "last_frame": (
            {
                "frame_id": "42",
                "timestamp": "2026-07-29T01:02:03.000Z",
                "objects": objects or [],
            }
            if frame
            else {}
        ),
    }


def test_normalized_bbox_mapping_tracks_responsive_video_size() -> None:
    bbox = {"left": 0.25, "top": 0.1, "right": 0.75, "bottom": 0.9}
    assert ai_overlay.normalized_bbox_pixels(bbox, 1280, 720) == (
        320,
        72,
        640,
        576,
    )
    assert ai_overlay.normalized_bbox_pixels(bbox, 640, 360) == (
        160,
        36,
        320,
        288,
    )


def test_metadata_with_no_objects_renders_connected_empty_overlay() -> None:
    state = ai_overlay.public_ai_state(metadata(objects=[]), metrics())
    assert state["ai_connected"] is True
    assert state["metadata_fresh"] is True
    assert state["objects"] == []
    assert state["frame_counter"] == 100


def test_missing_or_stale_metadata_waits_without_drawing_stale_boxes() -> None:
    waiting = ai_overlay.public_ai_state(metadata(frame=False), None)
    assert waiting["ai_status"] == "waiting_for_metadata"
    assert waiting["status_message"] == "waiting for AI metadata"
    live_empty = ai_overlay.public_ai_state(metadata(frame=False), metrics())
    assert live_empty["ai_status"] == "connected"
    assert live_empty["frame_counter"] == 100
    detected = {
        "type": "Person",
        "confidence": 0.9,
        "track_id": "7",
        "bbox": {"left": 0.1, "top": 0.2, "right": 0.4, "bottom": 0.8},
    }
    stale = ai_overlay.public_ai_state(metadata(age=11, objects=[detected]), None)
    assert stale["ai_connected"] is True
    assert stale["ai_status"] == "metadata_delayed"
    assert stale["status_message"] == "AI metadata delayed"
    assert stale["metadata_fresh"] is False
    assert stale["objects"] == []


def test_object_silent_metadata_stays_connected_when_stream_metrics_are_live() -> None:
    state = ai_overlay.public_ai_state(
        metadata(age=30, objects=[], frame=True), metrics(frame_number=250)
    )
    assert state["ai_status"] == "connected"
    assert state["metadata_fresh"] is False
    assert state["frame_counter"] == 250
    assert state["objects"] == []


def resolver(fetch_json, clock=lambda: 100.0):
    return ai_overlay.AIStateResolver(
        "http://metadata.invalid/debug/state",
        "http://metrics.invalid/metrics",
        fetch_json=fetch_json,
        monotonic=clock,
        sleep=lambda _seconds: None,
    )


def test_metadata_request_retries_twice_before_succeeding() -> None:
    attempts = 0

    def fetch(url: str, _timeout: float) -> dict[str, Any]:
        nonlocal attempts
        if "metadata" in url:
            attempts += 1
            if attempts < 3:
                raise TimeoutError
            return metadata()
        return metrics()

    state = resolver(fetch).resolve()
    assert attempts == 3
    assert state["ai_status"] == "connected"
    assert state["consecutive_failures"] == 0


def test_metrics_failure_does_not_override_healthy_metadata() -> None:
    calls = 0

    def fetch(url: str, _timeout: float) -> dict[str, Any]:
        nonlocal calls
        if "metadata" in url:
            return metadata()
        calls += 1
        if calls > 1:
            raise TimeoutError
        return metrics(frame_number=321)

    state_resolver = resolver(fetch)
    first = state_resolver.resolve()
    second = state_resolver.resolve()
    assert first["frame_counter"] == 321
    assert second["ai_status"] == "connected"
    assert second["ai_connected"] is True
    assert second["metrics_degraded"] is True
    assert second["frame_counter"] == 321


def test_three_consecutive_failed_polls_are_required_for_unavailable() -> None:
    failed = False

    def fetch(url: str, _timeout: float) -> dict[str, Any]:
        if "metadata" in url:
            if failed:
                raise TimeoutError
            return metadata()
        return metrics(frame_number=444)

    state_resolver = resolver(fetch)
    healthy = state_resolver.resolve()
    assert healthy["ai_status"] == "connected"
    failed = True
    first = state_resolver.resolve()
    second = state_resolver.resolve()
    third = state_resolver.resolve()
    assert first["ai_status"] == second["ai_status"] == "reconnecting"
    assert first["ai_connected"] is second["ai_connected"] is True
    assert first["frame_counter"] == second["frame_counter"] == 444
    assert third["ai_status"] == "unavailable"
    assert third["ai_connected"] is False
    assert third["consecutive_failures"] == 3


def test_last_boxes_are_cached_only_during_five_second_grace() -> None:
    now = 100.0
    failed = False
    detected = {
        "type": "Person",
        "confidence": 0.9,
        "track_id": "7",
        "bbox": {"left": 0.1, "top": 0.2, "right": 0.4, "bottom": 0.8},
    }

    def clock() -> float:
        return now

    def fetch(url: str, _timeout: float) -> dict[str, Any]:
        if "metadata" in url:
            if failed:
                raise TimeoutError
            return metadata(age=0.5, objects=[detected])
        return metrics()

    state_resolver = resolver(fetch, clock)
    assert state_resolver.resolve()["objects"][0]["track_id"] == "7"
    failed = True
    now = 104.0
    reconnecting = state_resolver.resolve()
    assert reconnecting["objects"][0]["track_id"] == "7"
    assert reconnecting["frame_counter"] == 100
    now = 106.0
    expired = state_resolver.resolve()
    assert expired["objects"] == []


def test_disconnected_response_and_html_never_expose_credentials() -> None:
    credential_url = "rtsp://" + "operator:" + "secret@example.invalid"
    state_resolver = ai_overlay.AIStateResolver(
        credential_url + "/state",
        credential_url + "/metrics",
        request_retries=1,
        fetch_json=lambda _url, _timeout: (_ for _ in ()).throw(TimeoutError()),
    )
    state = state_resolver.resolve()
    content = json.dumps(state) + ai_overlay.AI_OVERLAY_HTML
    assert state["ai_connected"] is True
    assert state["ai_status"] == "reconnecting"
    assert "operator" not in content
    assert "secret" not in content
    assert "rtsp://" not in content
    assert 'src="/mjpeg"' in ai_overlay.AI_OVERLAY_HTML
    assert 'id="aiOverlay"' in ai_overlay.AI_OVERLAY_HTML
    assert 'fetch("/api/ai-state"' in ai_overlay.AI_OVERLAY_HTML
    assert "const POLL_MS=400" in ai_overlay.AI_OVERLAY_HTML
    assert "frontendFailures<3" in ai_overlay.AI_OVERLAY_HTML
    assert "BBOX_GRACE_MS=5000" in ai_overlay.AI_OVERLAY_HTML
