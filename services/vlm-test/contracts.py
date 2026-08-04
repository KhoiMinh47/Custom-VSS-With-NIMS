from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
CAMERA_ID_PATTERN = re.compile(r"cam-[0-9]{2}")
HEX_ID_PATTERN = re.compile(r"[0-9a-f]{64}")
JOB_URI_PATTERN = re.compile(r"vlm-stage://([0-9a-f]{64})\.(mp4|mkv)")
STORE_URI_PATTERN = re.compile(r"vlm-store://([0-9a-f]{64})\.(mp4|mkv)")
VERDICTS = {"confirmed", "rejected", "uncertain"}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
VLM_MODEL_ID = "nvidia/cosmos3-nano-reasoner"
VLM_MODEL_VERSION = "bf16-final"
PROMPT_VERSION = "1.0.0"


class VlmTestError(Exception):
    """An error safe to expose from the VLM-test control plane."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message[:240]
        self.retryable = retryable
        self.details = details or {}

    def public(self, request_id: str = "") -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "status": "error",
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "request_id": request_id,
            **self.details,
        }


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 64:
        raise VlmTestError(400, "invalid_utc", f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise VlmTestError(400, "invalid_utc", f"{field} must be a UTC timestamp") from error
    return parsed.astimezone(UTC)


def validate_identity(value: dict[str, Any], operation: str) -> None:
    if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise VlmTestError(400, "identity_mismatch", f"{operation} schema version is unsupported")
    if value.get("store_id", STORE_ID) != STORE_ID:
        raise VlmTestError(400, "identity_mismatch", f"{operation} must target store-001")


def validate_filename(filename: str) -> str:
    if (
        not isinstance(filename, str)
        or not filename
        or len(filename) > 200
        or filename != filename.rsplit("/", 1)[-1]
        or filename != filename.rsplit("\\", 1)[-1]
        or filename.startswith(".")
        or any(ord(character) < 32 for character in filename)
    ):
        raise VlmTestError(400, "invalid_filename", "video filename is invalid")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in {"mp4", "mkv"}:
        raise VlmTestError(400, "unsupported_container", "only MP4 or Matroska videos are supported")
    return f".{extension}"


def validate_video(filename: str, content_type: str, body: bytes) -> str:
    extension = validate_filename(filename)
    if len(body) < 32 or len(body) > MAX_UPLOAD_BYTES:
        raise VlmTestError(400, "invalid_upload_size", "video size is outside the configured limit")
    expected_type = "video/mp4" if extension == ".mp4" else "video/x-matroska"
    if content_type.split(";", 1)[0].lower() != expected_type:
        raise VlmTestError(400, "unsupported_content_type", "content type does not match the video container")
    if extension == ".mp4":
        if body[4:8] != b"ftyp" or b"moov" not in body or b"mdat" not in body:
            raise VlmTestError(400, "invalid_mp4", "the uploaded MP4 is not structurally valid")
        if b"avc1" not in body and b"avc3" not in body:
            raise VlmTestError(400, "unsupported_codec", "VLM test requires H.264 video")
    elif not body.startswith(b"\x1aE\xdf\xa3") or b"V_MPEG4/ISO/AVC" not in body:
        raise VlmTestError(400, "unsupported_codec", "VLM test requires H.264 video")
    return extension


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def validate_candidate(event: dict[str, Any]) -> dict[str, Any]:
    required = (
        "schema_version",
        "store_id",
        "camera_id",
        "event_id",
        "event_type",
        "model_id",
        "model_version",
        "start_time",
        "end_time",
    )
    missing = [name for name in required if name not in event]
    if missing:
        raise VlmTestError(400, "candidate_contract_invalid", f"candidate is missing: {','.join(missing)}")
    validate_identity(event, "candidate")
    camera_id = str(event.get("camera_id", ""))
    if CAMERA_ID_PATTERN.fullmatch(camera_id) is None:
        raise VlmTestError(400, "candidate_contract_invalid", "candidate camera_id is not stable")
    event_id = str(event.get("event_id", ""))
    if HEX_ID_PATTERN.fullmatch(event_id) is None:
        raise VlmTestError(400, "candidate_contract_invalid", "candidate event_id is invalid")
    if event.get("candidate") is not True or event.get("evaluation") is True:
        raise VlmTestError(400, "candidate_not_eligible", "only non-evaluation candidate events can enter VLM test")
    start = parse_utc(event.get("start_time"), "candidate.start_time")
    end = parse_utc(event.get("end_time"), "candidate.end_time")
    if end <= start:
        raise VlmTestError(400, "candidate_contract_invalid", "candidate end_time must be after start_time")
    event_type = str(event.get("event_type", "")).strip()
    if not 1 <= len(event_type) <= 160:
        raise VlmTestError(400, "candidate_contract_invalid", "candidate event_type is invalid")
    return event


def stage_id(uri: str) -> str | None:
    match = JOB_URI_PATTERN.fullmatch(uri)
    return match.group(1) if match else None


def store_id(uri: str) -> str | None:
    match = STORE_URI_PATTERN.fullmatch(uri)
    return match.group(1) if match else None
