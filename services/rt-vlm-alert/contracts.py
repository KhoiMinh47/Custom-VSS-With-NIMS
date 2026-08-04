from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any


SCHEMA_VERSION = "1.0.0"
MODEL_ID = "nvidia/cosmos3-nano-reasoner"
MODEL_VERSION = "bf16-final"
PROMPT_VERSION = "1.0.0"
USE_CASE_ID = "person-presence-direct-v1"
VERDICTS = {"confirmed", "rejected", "uncertain"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_verdict(text: str) -> tuple[str, float, str]:
    cleaned = text.strip()
    candidates = re.findall(r"\{(?:[^{}]|\"[^\"]*\")+\}", cleaned, flags=re.DOTALL)
    for candidate in reversed(candidates):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        answer = str(value.get("verdict", value.get("answer", ""))).strip().lower()
        mapping = {
            "yes": "confirmed",
            "true": "confirmed",
            "confirmed": "confirmed",
            "no": "rejected",
            "false": "rejected",
            "rejected": "rejected",
            "uncertain": "uncertain",
        }
        verdict = mapping.get(answer)
        if verdict:
            try:
                confidence = min(1.0, max(0.0, float(value.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5
            reason = str(value.get("reason", cleaned)).strip()[:2000]
            return verdict, confidence, reason
    tag = re.search(
        r"<answer>\s*(yes|no|true|false|confirmed|rejected|uncertain)\s*</answer>",
        cleaned,
        re.I,
    )
    bare = tag.group(1).lower() if tag else cleaned.lower()
    if bare in {"yes", "true", "confirmed"}:
        return "confirmed", 0.5, cleaned[:2000]
    if bare in {"no", "false", "rejected"}:
        return "rejected", 0.5, cleaned[:2000]
    return "uncertain", 0.0, (
        cleaned[:2000] or "RT-VLM response did not satisfy the verdict contract"
    )


def build_direct_alert(
    *,
    request_id: str,
    chunk_index: int,
    camera_id: str,
    start_time: str,
    end_time: str,
    response: str,
    model_version: str,
    info: dict[str, str],
) -> dict[str, Any]:
    if not request_id or camera_id != "cam-01" or chunk_index < 0:
        raise ValueError("invalid direct RT-VLM correlation")
    verdict, confidence, reason = parse_verdict(response)
    direct_alert_id = hashlib.sha256(
        f"store-001|{camera_id}|{request_id}|{chunk_index}|{PROMPT_VERSION}".encode()
    ).hexdigest()

    def metric(name: str) -> float:
        try:
            return max(0.0, float(info.get(name, "0")))
        except (TypeError, ValueError):
            return 0.0

    def integer(name: str) -> int:
        try:
            return max(0, int(info.get(name, "0")))
        except (TypeError, ValueError):
            return 0

    now = utc_now()
    resolved_model_version = (
        MODEL_VERSION if not model_version or model_version == MODEL_ID else model_version
    )
    return {
        "@timestamp": now,
        "schema_version": SCHEMA_VERSION,
        "store_id": "store-001",
        "camera_id": camera_id,
        "correlation_id": request_id,
        "direct_alert_id": direct_alert_id,
        "request_id": request_id,
        "chunk_index": chunk_index,
        "start_time": start_time,
        "end_time": end_time,
        "event_type": "direct_vlm.person_presence",
        "use_case_id": USE_CASE_ID,
        "source": "vendor_rt_vlm_kafka",
        "model_id": MODEL_ID,
        "model_version": resolved_model_version,
        "prompt_version": PROMPT_VERSION,
        "verdict": verdict,
        "is_alert": verdict == "confirmed",
        "confidence": confidence,
        "reason": reason,
        "latency_ms": round(metric("chunkLatencyMs")),
        "decode_latency_ms": round(metric("decodeLatencyMs")),
        "vlm_latency_ms": round(metric("vlmLatencyMs")),
        "queue_time_seconds": metric("queueTimeS"),
        "processing_time_seconds": metric("processingLatencyS"),
        "frame_count": integer("frameCount"),
        "input_tokens": integer("inputTokens"),
        "output_tokens": integer("outputTokens"),
        "chunk_duration_seconds": 8,
        "frame_sampling": "5-fixed-frames-per-chunk",
        "evaluation": False,
        "created_at": now,
        "raw_response_excerpt": response[:1000],
    }


def confusion_matrix(alerts: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    labels = sorted(VERDICTS)
    matrix = {predicted: {actual: 0 for actual in labels} for predicted in labels}
    for alert in alerts:
        predicted = alert.get("verdict")
        actual = alert.get("feedback_label")
        if predicted in VERDICTS and actual in VERDICTS:
            matrix[str(predicted)][str(actual)] += 1
    return matrix
