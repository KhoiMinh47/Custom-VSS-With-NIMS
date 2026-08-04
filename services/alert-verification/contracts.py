from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Callable


SCHEMA_VERSION = "1.0.0"
VERIFIER_MODEL_ID = "nvidia/cosmos3-nano-reasoner"
VERIFIER_MODEL_VERSION = "bf16-final"
PROMPT_VERSION = "1.0.0"
VERDICTS = {"confirmed", "rejected", "uncertain"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_incident(incident: dict[str, Any]) -> None:
    required = (
        "schema_version",
        "store_id",
        "camera_id",
        "incident_id",
        "event_id",
        "event_type",
        "clip_start_time",
        "clip_end_time",
        "asset_uri",
        "clip_sha256",
    )
    missing = [key for key in required if key not in incident]
    if missing:
        raise ValueError(f"incident missing fields: {','.join(missing)}")
    if incident["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported incident schema_version")
    if not str(incident["asset_uri"]).startswith("selected-clip://"):
        raise ValueError("incident must reference a selected clip")


def parse_verdict(text: str) -> tuple[str, float, str]:
    cleaned = text.strip()
    candidates = re.findall(r"\{(?:[^{}]|\"[^\"]*\")+\}", cleaned, flags=re.DOTALL)
    for candidate in reversed(candidates):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        verdict = str(value.get("verdict", "")).strip().lower()
        if verdict not in VERDICTS:
            continue
        try:
            confidence = min(1.0, max(0.0, float(value.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(value.get("reason", "")).strip()[:2000]
        return verdict, confidence, reason
    answer = re.search(r"<answer>\s*(yes|no|uncertain)\s*</answer>", cleaned, re.I)
    if answer:
        mapped = {"yes": "confirmed", "no": "rejected", "uncertain": "uncertain"}
        return mapped[answer.group(1).lower()], 0.5, cleaned[:2000]
    bare = cleaned.lower()
    if bare in {"yes", "confirmed"}:
        return "confirmed", 0.5, cleaned
    if bare in {"no", "rejected"}:
        return "rejected", 0.5, cleaned
    if bare == "uncertain":
        return "uncertain", 0.0, cleaned
    return "uncertain", 0.0, "VLM response did not satisfy the structured verdict contract"


def build_verified(
    incident: dict[str, Any],
    *,
    verdict: str,
    confidence: float,
    reason: str,
    retry_count: int,
    latency_ms: int,
    raw_response: str = "",
) -> dict[str, Any]:
    validate_incident(incident)
    if verdict not in VERDICTS:
        raise ValueError("invalid verdict")
    now = utc_now()
    return {
        **incident,
        "@timestamp": now,
        "status": "verified" if verdict != "uncertain" else "needs_review",
        "verdict": verdict,
        "confidence": min(1.0, max(0.0, float(confidence))),
        "reason": reason[:2000],
        "retry_count": int(retry_count),
        "verifier_model_id": VERIFIER_MODEL_ID,
        "verifier_model_version": VERIFIER_MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "latency_ms": int(latency_ms),
        "updated_at": now,
        "raw_response_excerpt": raw_response[:1000],
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


def retry_operation(
    operation: Callable[[], str],
    *,
    attempts: int,
    pause: Callable[[int], None],
) -> tuple[str | None, int, str]:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            return operation(), attempt - 1, ""
        except Exception as error:
            last_error = type(error).__name__
            if attempt < attempts:
                pause(attempt)
    return None, attempts, last_error
