from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
CAPTION_MODEL_ID = "nvidia/cosmos3-nano-reasoner"
CAPTION_MODEL_VERSION = "bf16-final"
SUMMARY_MODEL_ID = "nvidia/nvidia-nemotron-nano-9b-v2"
SUMMARY_MODEL_VERSION = "1"
CAPTION_PROMPT_VERSION = "1.0.0"
SUMMARY_PROMPT_VERSION = "1.0.0"
REFUSAL_TEXT = "không đủ dữ liệu"
UNOBSERVED_TEXT = "không quan sát được"
SOURCE_TYPES = {"selected_video", "time_window"}
GENERIC_QUESTION_TERMS = {
    "activity",
    "event",
    "events",
    "video",
    "visible",
    "kiện",
    "hành",
    "động",
    "người",
    "vật",
}
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "did",
    "do",
    "does",
    "happen",
    "happened",
    "in",
    "is",
    "of",
    "on",
    "the",
    "there",
    "to",
    "was",
    "what",
    "when",
    "where",
    "who",
    "with",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{field} is not a valid UTC timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include UTC")
    return parsed.astimezone(UTC)


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def selected_clip_path(
    root: Path, uri: Any, uploaded_root: Path | None = None
) -> Path:
    selected_prefix = "selected-clip://"
    uploaded_prefix = "uploaded-media://"
    if isinstance(uri, str) and uri.startswith(selected_prefix):
        selected_root = root
        filename = uri[len(selected_prefix) :]
    elif (
        isinstance(uri, str)
        and uri.startswith(uploaded_prefix)
        and uploaded_root is not None
    ):
        selected_root = uploaded_root
        filename = uri[len(uploaded_prefix) :]
    else:
        raise ValueError("only prepared selected-clip:// or uploaded-media:// media is accepted")
    if (
        len(filename) != 68
        or not filename.endswith(".mp4")
        or any(character not in "0123456789abcdef" for character in filename[:-4])
    ):
        raise ValueError("selected clip URI must contain a sha256-style MP4 filename")
    path = selected_root / filename
    if path.resolve().parent != selected_root.resolve():
        raise ValueError("selected clip escaped the selected-media directory")
    if not path.is_file():
        raise FileNotFoundError("selected clip is missing")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _job_id(payload: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    stable = {
        "store_id": payload["store_id"],
        "camera_id": payload["camera_id"],
        "source_type": payload["source_type"],
        "window_start": payload["window_start"],
        "window_end": payload["window_end"],
        "chunks": [
            (item["asset_uri"], item["start_time"], item["end_time"], item["asset_sha256"])
            for item in chunks
        ],
        "caption_model": (CAPTION_MODEL_ID, CAPTION_MODEL_VERSION),
        "summary_model": (SUMMARY_MODEL_ID, SUMMARY_MODEL_VERSION),
        "prompt_versions": (CAPTION_PROMPT_VERSION, SUMMARY_PROMPT_VERSION),
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def build_job(
    payload: dict[str, Any],
    selected_root: Path,
    uploaded_root: Path | None = None,
) -> dict[str, Any]:
    required = (
        "store_id",
        "camera_id",
        "source_type",
        "window_start",
        "window_end",
        "assets",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"summary request missing fields: {','.join(missing)}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported summary request schema_version")
    if payload["store_id"] != STORE_ID:
        raise ValueError("unsupported store_id")
    if not re.fullmatch(r"cam-[0-9]{2}", str(payload["camera_id"])):
        raise ValueError("camera_id must be stable cam-NN form")
    if payload["source_type"] not in SOURCE_TYPES:
        raise ValueError("source_type must be selected_video or time_window")
    window_start = parse_utc(payload["window_start"], "window_start")
    window_end = parse_utc(payload["window_end"], "window_end")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    assets = payload["assets"]
    if not isinstance(assets, list) or not assets:
        raise ValueError("assets must contain at least one selected clip")
    if payload["source_type"] == "selected_video" and len(assets) != 1:
        raise ValueError("selected_video jobs require exactly one selected clip")

    chunks: list[dict[str, Any]] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise ValueError("each asset must be an object")
        path = selected_clip_path(
            selected_root, asset.get("asset_uri"), uploaded_root
        )
        start = parse_utc(asset.get("start_time"), f"assets[{index}].start_time")
        end = parse_utc(asset.get("end_time"), f"assets[{index}].end_time")
        if end <= start or start < window_start or end > window_end:
            raise ValueError("selected clip timestamps must be within the requested window")
        digest = _sha256(path)
        expected_digest = asset.get("asset_sha256")
        if expected_digest and expected_digest != digest:
            raise ValueError("selected clip sha256 does not match the request")
        chunk_material = f"{asset['asset_uri']}\n{format_utc(start)}\n{format_utc(end)}"
        chunks.append(
            {
                "chunk_id": hashlib.sha256(chunk_material.encode()).hexdigest(),
                "chunk_index": index,
                "asset_uri": asset["asset_uri"],
                "asset_sha256": digest,
                "start_time": format_utc(start),
                "end_time": format_utc(end),
                "duration_seconds": round((end - start).total_seconds(), 3),
                "frame_sampling": "5-uniform-frames",
                "caption_status": "pending",
                "caption_attempts": 0,
            }
        )
    chunks.sort(key=lambda item: (item["start_time"], item["asset_uri"]))
    for index, chunk in enumerate(chunks):
        chunk["chunk_index"] = index

    canonical_payload = {
        **payload,
        "window_start": format_utc(window_start),
        "window_end": format_utc(window_end),
    }
    job_id = _job_id(canonical_payload, chunks)
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "idempotency_key": str(payload.get("idempotency_key") or job_id),
        "store_id": STORE_ID,
        "camera_id": payload["camera_id"],
        "source_type": payload["source_type"],
        "window_start": canonical_payload["window_start"],
        "window_end": canonical_payload["window_end"],
        "title": str(payload.get("title") or "Selected video summary")[:200],
        "status": "queued_caption",
        "priority": int(payload.get("priority", 50)),
        "created_at": now,
        "updated_at": now,
        "caption_model_id": CAPTION_MODEL_ID,
        "caption_model_version": CAPTION_MODEL_VERSION,
        "caption_prompt_version": CAPTION_PROMPT_VERSION,
        "summary_model_id": SUMMARY_MODEL_ID,
        "summary_model_version": SUMMARY_MODEL_VERSION,
        "summary_prompt_version": SUMMARY_PROMPT_VERSION,
        "chunks": chunks,
        "partial_summaries": [],
        "summary": None,
        "retry_count": 0,
        "restart_count": 0,
        "last_error": "",
        "evidence_policy": {
            "selected_media_only": True,
            "raw_archive_scanned": False,
            "unobserved_gaps_are_not_no_event_claims": True,
        },
    }


def recover_interrupted_job(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("status") == "captioning":
        job["status"] = "queued_caption"
        job["restart_count"] = int(job.get("restart_count", 0)) + 1
    elif job.get("status") == "summarizing":
        job["status"] = "queued_summary"
        job["restart_count"] = int(job.get("restart_count", 0)) + 1
    job["updated_at"] = utc_now()
    return job


def parse_json_object(content: Any) -> dict[str, Any]:
    if not isinstance(content, str):
        raise ValueError("provider response content is not text")
    text = content.strip()
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1].strip()
    decoder = json.JSONDecoder()
    for offset, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("provider response does not contain a JSON object")


def normalize_caption(
    provider_value: dict[str, Any], chunk: dict[str, Any], camera_id: str
) -> dict[str, Any]:
    caption = str(provider_value.get("caption") or provider_value.get("summary") or "").strip()
    raw_events = provider_value.get("events")
    if not isinstance(raw_events, list):
        raw_events = []
    duration = float(chunk["duration_seconds"])
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description") or raw.get("event") or "").strip()
        if not description:
            continue
        try:
            relative_start = max(0.0, min(duration, float(raw.get("start_seconds", 0))))
            relative_end = max(
                relative_start,
                min(duration, float(raw.get("end_seconds", duration))),
            )
        except (TypeError, ValueError):
            relative_start, relative_end = 0.0, duration
        absolute_start = parse_utc(chunk["start_time"], "chunk.start_time") + timedelta(
            seconds=relative_start
        )
        absolute_end = parse_utc(chunk["start_time"], "chunk.start_time") + timedelta(
            seconds=relative_end
        )
        event_id = hashlib.sha256(
            f"{chunk['chunk_id']}\n{index}\n{description}".encode()
        ).hexdigest()
        events.append(
            {
                "event_id": event_id,
                "description": description[:2000],
                "start_time": format_utc(absolute_start),
                "end_time": format_utc(absolute_end),
                "importance": str(raw.get("importance", "normal"))[:40],
                "camera_id": camera_id,
                "asset_uri": chunk["asset_uri"],
                "chunk_id": chunk["chunk_id"],
            }
        )
    if not events and caption:
        event_id = hashlib.sha256(f"{chunk['chunk_id']}\n{caption}".encode()).hexdigest()
        events.append(
            {
                "event_id": event_id,
                "description": caption[:2000],
                "start_time": chunk["start_time"],
                "end_time": chunk["end_time"],
                "importance": "normal",
                "camera_id": camera_id,
                "asset_uri": chunk["asset_uri"],
                "chunk_id": chunk["chunk_id"],
            }
        )
    if not caption and not events:
        raise ValueError("caption response contains no observable description")
    return {
        "@timestamp": utc_now(),
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "chunk_id": chunk["chunk_id"],
        "chunk_index": chunk["chunk_index"],
        "start_time": chunk["start_time"],
        "end_time": chunk["end_time"],
        "asset_uri": chunk["asset_uri"],
        "asset_sha256": chunk["asset_sha256"],
        "caption": caption[:4000],
        "events": events,
        "observed_entities": [
            str(item)[:200]
            for item in provider_value.get("observed_entities", [])
            if isinstance(item, str)
        ][:50],
        "observed_actions": [
            str(item)[:200]
            for item in provider_value.get("observed_actions", [])
            if isinstance(item, str)
        ][:50],
        "model_id": CAPTION_MODEL_ID,
        "model_version": CAPTION_MODEL_VERSION,
        "prompt_version": CAPTION_PROMPT_VERSION,
        "frame_sampling": chunk["frame_sampling"],
        "evidence": {
            "asset_uri": chunk["asset_uri"],
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
            "selected_media": True,
        },
    }


def all_events(job: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for chunk in job.get("chunks", []):
        caption = chunk.get("caption")
        if isinstance(caption, dict):
            events.extend(caption.get("events", []))
    return sorted(events, key=lambda item: (item["start_time"], item["event_id"]))


def coverage_gaps(job: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = sorted(job.get("chunks", []), key=lambda item: item["start_time"])
    cursor = parse_utc(job["window_start"], "window_start")
    window_end = parse_utc(job["window_end"], "window_end")
    gaps: list[dict[str, Any]] = []
    for chunk in chunks:
        start = parse_utc(chunk["start_time"], "chunk.start_time")
        end = parse_utc(chunk["end_time"], "chunk.end_time")
        if start > cursor:
            gaps.append(
                {
                    "start_time": format_utc(cursor),
                    "end_time": format_utc(start),
                    "status": "unobserved",
                    "reason": "no selected media evidence covers this interval",
                }
            )
        cursor = max(cursor, end)
    if cursor < window_end:
        gaps.append(
            {
                "start_time": format_utc(cursor),
                "end_time": format_utc(window_end),
                "status": "unobserved",
                "reason": "no selected media evidence covers this interval",
            }
        )
    return gaps


def normalize_summary(
    provider_value: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    job: dict[str, Any],
    level: int,
) -> dict[str, Any]:
    by_id = {event["event_id"]: event for event in events}
    requested_ids = provider_value.get("event_ids", [])
    valid_ids = [str(value) for value in requested_ids if str(value) in by_id]
    if not valid_ids and events:
        valid_ids = [event["event_id"] for event in events]
        executive = "; ".join(event["description"] for event in events[:5])
        synthesis_source = "deterministic_grounded_fallback"
    else:
        executive = str(provider_value.get("executive_summary") or "").strip()
        if not executive:
            executive = "; ".join(by_id[event_id]["description"] for event_id in valid_ids[:5])
        synthesis_source = "nemotron"
    evidence = [
        {
            "event_id": event_id,
            "camera_id": by_id[event_id]["camera_id"],
            "start_time": by_id[event_id]["start_time"],
            "end_time": by_id[event_id]["end_time"],
            "asset_uri": by_id[event_id]["asset_uri"],
            "description": by_id[event_id]["description"],
        }
        for event_id in valid_ids
    ]
    incident_ids = [
        str(value)
        for value in provider_value.get("incident_event_ids", [])
        if str(value) in by_id
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": job["store_id"],
        "camera_id": job["camera_id"],
        "job_id": job["job_id"],
        "window_start": job["window_start"],
        "window_end": job["window_end"],
        "hierarchy_level": level,
        "executive_summary": executive[:6000],
        "event_ids": valid_ids,
        "incident_event_ids": incident_ids,
        "notable_entities": [
            str(value)[:200]
            for value in provider_value.get("notable_entities", [])
            if isinstance(value, str)
        ][:50],
        "notable_actions": [
            str(value)[:200]
            for value in provider_value.get("notable_actions", [])
            if isinstance(value, str)
        ][:50],
        "evidence": evidence,
        "coverage_gaps": coverage_gaps(job) if level >= 1 else [],
        "model_id": SUMMARY_MODEL_ID,
        "model_version": SUMMARY_MODEL_VERSION,
        "prompt_version": SUMMARY_PROMPT_VERSION,
        "synthesis_source": synthesis_source,
        "created_at": utc_now(),
    }


def question_terms(question: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9À-ỹ_-]+", question.lower())
        if len(word) > 2 and word not in STOP_WORDS
    }


def question_scope(
    question: str,
    *,
    default_window_start: str | None = None,
    default_window_end: str | None = None,
) -> dict[str, Any]:
    cameras = sorted(set(re.findall(r"\bcam-[0-9]{2}\b", question.lower())))
    scope: dict[str, Any] = {"camera_ids": cameras}
    if len(cameras) > 1:
        scope["camera_ambiguous"] = True
        return scope
    if "utc" not in question.lower():
        return scope

    clock_values = re.findall(
        r"(?<![0-9])([01]?[0-9]|2[0-3]):([0-5][0-9])(?::([0-5][0-9]))?",
        question,
    )
    if len(clock_values) < 2:
        scope["time_ambiguous"] = True
        return scope

    date_match = re.search(r"\b(20[0-9]{2}-[01][0-9]-[0-3][0-9])\b", question)
    if date_match:
        try:
            date_value = datetime.fromisoformat(date_match.group(1)).date()
        except ValueError:
            scope["time_ambiguous"] = True
            return scope
    elif default_window_start and default_window_end:
        default_start = parse_utc(default_window_start, "default_window_start")
        default_end = parse_utc(default_window_end, "default_window_end")
        if default_start.date() != default_end.date():
            scope["time_ambiguous"] = True
            return scope
        date_value = default_start.date()
    else:
        scope["time_ambiguous"] = True
        return scope

    def combine(clock: tuple[str, str, str]) -> datetime:
        hour, minute, second = (int(value or 0) for value in clock)
        return datetime(
            date_value.year,
            date_value.month,
            date_value.day,
            hour,
            minute,
            second,
            tzinfo=UTC,
        )

    start = combine(clock_values[0])
    end = combine(clock_values[1])
    if end <= start:
        end += timedelta(days=1)
    scope["window_start"] = format_utc(start)
    scope["window_end"] = format_utc(end)
    return scope


def select_question_evidence(
    question: str,
    events: list[dict[str, Any]],
    *,
    default_window_start: str | None = None,
    default_window_end: str | None = None,
) -> list[dict[str, Any]]:
    scope = question_scope(
        question,
        default_window_start=default_window_start,
        default_window_end=default_window_end,
    )
    if scope.get("camera_ambiguous") or scope.get("time_ambiguous"):
        return []

    scoped_events = events
    camera_ids = set(scope["camera_ids"])
    if camera_ids:
        scoped_events = [
            event for event in scoped_events if event.get("camera_id") in camera_ids
        ]

    if scope.get("window_start") and scope.get("window_end"):
        query_start = parse_utc(scope["window_start"], "question.window_start")
        query_end = parse_utc(scope["window_end"], "question.window_end")
        scoped_events = [
            event
            for event in scoped_events
            if parse_utc(event["start_time"], "event.start_time") < query_end
            and parse_utc(event["end_time"], "event.end_time") >= query_start
        ]

    terms = question_terms(question)
    if not terms or terms.intersection(GENERIC_QUESTION_TERMS):
        return scoped_events
    selected = []
    for event in scoped_events:
        words = set(re.findall(r"[a-z0-9À-ỹ_-]+", event["description"].lower()))
        if words.intersection(terms):
            selected.append(event)
    return selected


def refusal(
    question: str,
    reason: str = "no matching evidence",
    *,
    answer: str = REFUSAL_TEXT,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "question": question,
        "answer": answer,
        "status": "insufficient_evidence",
        "grounded": False,
        "refused": True,
        "reason": reason,
        "evidence": [],
        "model_id": SUMMARY_MODEL_ID,
        "model_version": SUMMARY_MODEL_VERSION,
        "created_at": utc_now(),
    }


def grounded_answer(
    question: str,
    provider_value: dict[str, Any],
    candidate_events: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {event["event_id"]: event for event in candidate_events}
    if provider_value.get("insufficient_evidence") is True:
        return refusal(question, "provider reported insufficient evidence")
    referenced = [
        str(value)
        for value in provider_value.get("event_ids", [])
        if str(value) in by_id
    ]
    answer = str(provider_value.get("answer") or "").strip()
    if not answer or not referenced:
        return refusal(question, "answer did not cite selected evidence")
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "question": question,
        "answer": answer[:4000],
        "status": "answered",
        "grounded": True,
        "refused": False,
        "evidence": [
            {
                "event_id": event_id,
                "camera_id": by_id[event_id]["camera_id"],
                "start_time": by_id[event_id]["start_time"],
                "end_time": by_id[event_id]["end_time"],
                "asset_uri": by_id[event_id]["asset_uri"],
            }
            for event_id in referenced
        ],
        "model_id": SUMMARY_MODEL_ID,
        "model_version": SUMMARY_MODEL_VERSION,
        "created_at": utc_now(),
    }
