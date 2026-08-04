from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from contracts import (
    CAMERA_ID_PATTERN,
    HEX_ID_PATTERN,
    JOB_URI_PATTERN,
    MAX_UPLOAD_BYTES,
    SCHEMA_VERSION,
    STORE_ID,
    STORE_URI_PATTERN,
    VLM_MODEL_ID,
    VLM_MODEL_VERSION,
    PROMPT_VERSION,
    VlmTestError,
    digest,
    parse_utc,
    stage_id,
    store_id,
    utc_now,
    validate_candidate,
    validate_identity,
    validate_video,
)


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_CANDIDATES = 100
DEFAULT_CAMERA_ID = "cam-01"


def log(level: str, event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": utc_now(),
                "level": level,
                "service": "phase15-vlm-test",
                "event": event,
                **fields,
            },
            separators=(",", ":"),
            allow_nan=False,
        ),
        flush=True,
    )


def _safe_id(value: str, field: str) -> str:
    if HEX_ID_PATTERN.fullmatch(value) is None:
        raise VlmTestError(404, "not_found", f"{field} is invalid")
    return value


def _now_epoch() -> int:
    return time.time_ns()


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 15,
    max_bytes: int = MAX_JSON_BYTES,
) -> tuple[int, Any]:
    if not base_url.startswith("http://127.0.0.1:"):
        raise RuntimeError("VLM-test upstream must be fixed loopback HTTP")
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json" if body is not None else "application/json",
            "X-Request-ID": uuid.uuid4().hex,
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read(max_bytes + 1)
            status = int(response.status)
    except HTTPError as error:
        content = error.read(max_bytes + 1)
        status = int(error.code)
        error.close()
    except (TimeoutError, URLError, OSError) as error:
        raise VlmTestError(503, "upstream_unavailable", "fixed VLM-test upstream is unavailable", retryable=True) from error
    if len(content) > max_bytes:
        raise VlmTestError(502, "upstream_response_too_large", "fixed upstream response is too large")
    try:
        value = json.loads(content) if content else {}
    except json.JSONDecodeError as error:
        raise VlmTestError(502, "invalid_upstream_json", "fixed upstream returned invalid JSON", retryable=True) from error
    return status, value


def _request_binary(base_url: str, path: str, *, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    if not base_url.startswith("http://127.0.0.1:"):
        raise RuntimeError("media upstream must be fixed loopback HTTP")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Accept": "video/mp4", "X-Request-ID": uuid.uuid4().hex},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            content = response.read(max_bytes + 1)
            status = int(response.status)
    except HTTPError as error:
        status = int(error.code)
        error.close()
        if status == 404:
            raise VlmTestError(404, "selected_clip_not_found", "selected realtime clip was not found") from error
        raise VlmTestError(503, "selected_clip_unavailable", "selected realtime clip is unavailable", retryable=True) from error
    except (TimeoutError, URLError, OSError) as error:
        raise VlmTestError(503, "selected_clip_unavailable", "selected realtime clip is unavailable", retryable=True) from error
    if status != 200 or len(content) > max_bytes:
        raise VlmTestError(502, "invalid_selected_clip", "selected realtime clip is invalid")
    if len(content) < 32 or content[4:8] != b"ftyp" or b"moov" not in content or b"mdat" not in content:
        raise VlmTestError(502, "invalid_selected_clip", "selected realtime clip is not a valid MP4")
    return content


class TestStore:
    """Durable VLM-test registry with staging and post-VLM Store planes."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.staging = self.root / "staging"
        self.store = self.root / "store"
        self.trash = self.root / "trash"
        self.registry = self.root / "registry.json"
        self.lock = threading.RLock()
        for path in (self.staging, self.store, self.trash):
            path.mkdir(parents=True, exist_ok=True)
        self._recover_incomplete()

    def _recover_incomplete(self) -> None:
        with self.lock:
            value = self._load()
            changed = False
            for job in value["jobs"].values():
                if job.get("vlm_status") == "completed" and (
                    job.get("error_code") is not None or job.get("error_message") is not None
                ):
                    job.pop("error_code", None)
                    job.pop("error_message", None)
                    changed = True
                if job.get("vlm_status") in {"queued", "running"}:
                    job["vlm_status"] = "waiting_for_admission"
                    job["status"] = "waiting_for_gpu"
                    job["updated_at"] = utc_now()
                    job["blocked_gate"] = "local_vlm_lease"
                    changed = True
            if changed:
                self._save(value)

    def _load(self) -> dict[str, Any]:
        if not self.registry.exists():
            return {"jobs": {}, "assets": {}, "idempotency": {}}
        try:
            value = json.loads(self.registry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise VlmTestError(500, "registry_invalid", "VLM-test registry cannot be read safely") from error
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != SCHEMA_VERSION
            or value.get("store_id") != STORE_ID
            or not isinstance(value.get("jobs"), dict)
            or not isinstance(value.get("assets"), dict)
            or not isinstance(value.get("idempotency"), dict)
        ):
            raise VlmTestError(500, "registry_invalid", "VLM-test registry has an invalid contract")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        temporary = self.registry.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": STORE_ID,
                    "updated_at": utc_now(),
                    "jobs": value["jobs"],
                    "assets": value["assets"],
                    "idempotency": value["idempotency"],
                },
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.registry)

    def _path(self, root: Path, identifier: str, extension: str) -> Path:
        path = (root / f"{identifier}{extension}").resolve()
        if path.parent != root.resolve() or path.name != f"{identifier}{extension}":
            raise VlmTestError(400, "invalid_media_reference", "media reference is invalid")
        return path

    def _job(self, value: dict[str, Any], job_id: str) -> dict[str, Any]:
        job = value["jobs"].get(job_id)
        if not isinstance(job, dict):
            raise VlmTestError(404, "job_not_found", "VLM-test job was not found")
        return job

    def _asset(self, value: dict[str, Any], asset_id: str) -> dict[str, Any]:
        asset = value["assets"].get(asset_id)
        if not isinstance(asset, dict):
            raise VlmTestError(404, "store_asset_not_found", "post-VLM Store asset was not found")
        return asset

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(job))

    @staticmethod
    def _public_asset(asset: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(asset))

    def _new_id(self, seed: str) -> str:
        return hashlib.sha256(f"{seed}|{_now_epoch()}|{uuid.uuid4().hex}".encode()).hexdigest()

    def create_upload(
        self,
        filename: str,
        content_type: str,
        body: bytes,
        idempotency_key: str,
    ) -> tuple[int, dict[str, Any]]:
        extension = validate_video(filename, content_type, body)
        if not idempotency_key or len(idempotency_key) > 160 or any(
            not (character.isalnum() or character in "-_.:") for character in idempotency_key
        ):
            raise VlmTestError(400, "invalid_idempotency_key", "upload requires a valid idempotency key")
        content_sha = digest(body)
        with self.lock:
            value = self._load()
            existing_id = value["idempotency"].get(idempotency_key)
            if isinstance(existing_id, str) and existing_id in value["jobs"]:
                return 200, self._public_job(value["jobs"][existing_id])
            job_id = self._new_id(f"upload|{content_sha}|{idempotency_key}")
            target = self._path(self.staging, job_id, extension)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(body)
            os.replace(temporary, target)
            now = utc_now()
            job = {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "job_id": job_id,
                "camera_id": DEFAULT_CAMERA_ID,
                "source_type": "upload",
                "filename": filename,
                "extension": extension,
                "content_sha256": content_sha,
                "bytes": len(body),
                "asset_uri": f"vlm-stage://{job_id}{extension}",
                "storage_state": "staging_only",
                "rtcv_status": "queued",
                "vlm_status": "awaiting_rtcv_candidate",
                "status": "queued_for_rtcv",
                "required_capability": "rtcv_file_batch",
                "candidate_event": None,
                "created_at": now,
                "updated_at": now,
                "saved_at": None,
                "stored_asset_id": None,
                "vlm_result": None,
                "idempotency_key": idempotency_key,
                "provenance": {
                    "plane": "vlm-test-staging",
                    "raw_archive_scanned": False,
                    "store_before_vlm": False,
                },
            }
            value["jobs"][job_id] = job
            value["idempotency"][idempotency_key] = job_id
            self._save(value)
        log("info", "upload_staged", job_id=job_id, bytes=len(body), extension=extension)
        return 201, self._public_job(job)

    def add_candidate(self, job_id: str, candidate: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        _safe_id(job_id, "job_id")
        validate_candidate(candidate)
        with self.lock:
            value = self._load()
            job = self._job(value, job_id)
            if job.get("source_type") != "upload":
                raise VlmTestError(409, "candidate_not_allowed", "only upload jobs accept a file RT-CV candidate")
            existing_candidate = job.get("candidate_event") or {}
            if existing_candidate.get("event_id") == candidate.get("event_id"):
                # A retry can legitimately rediscover the same RT-CV frame.
                # Reconcile the idempotent candidate with the current
                # workflow state instead of leaving a previous failed/running
                # status in place.
                job.update(
                    {
                        "camera_id": candidate["camera_id"],
                        "candidate_event": candidate,
                        "candidate_event_id": candidate["event_id"],
                        "rtcv_status": "candidate_created",
                        "vlm_status": "ready_to_launch",
                        "status": "ready_to_launch",
                        "required_capability": None,
                        "start_time": candidate["start_time"],
                        "end_time": candidate["end_time"],
                        "updated_at": utc_now(),
                    }
                )
                job.pop("error_code", None)
                job.pop("error_message", None)
                job.pop("blocked_gate", None)
                self._save(value)
                return 200, self._public_job(job)
            job.update(
                {
                    "camera_id": candidate["camera_id"],
                    "candidate_event": candidate,
                    "candidate_event_id": candidate["event_id"],
                    "rtcv_status": "candidate_created",
                    "vlm_status": "ready_to_launch",
                    "status": "ready_to_launch",
                    "required_capability": None,
                    "start_time": candidate["start_time"],
                    "end_time": candidate["end_time"],
                    "updated_at": utc_now(),
                }
            )
            self._save(value)
            return 200, self._public_job(job)

    def update_rtcv_status(self, job_id: str, status: str, detail: str = "") -> tuple[int, dict[str, Any]]:
        _safe_id(job_id, "job_id")
        if status not in {"running", "completed", "no_candidate", "failed"}:
            raise VlmTestError(400, "invalid_rtcv_status", "RT-CV workflow status is invalid")
        with self.lock:
            value = self._load()
            job = self._job(value, job_id)
            if job.get("source_type") != "upload":
                raise VlmTestError(409, "rtcv_status_not_allowed", "only upload jobs use file RT-CV")
            if status == "running":
                job.update(
                    {
                        "rtcv_status": "running",
                        "vlm_status": "awaiting_rtcv_candidate",
                        "status": "running_rtcv",
                        "required_capability": "rtcv_file_batch",
                    }
                )
            elif status == "completed":
                # add_candidate() has already moved the job to
                # ready_to_launch. Keep that state while recording that the
                # RT-CV half of the serialized workflow is finished.
                if not isinstance(job.get("candidate_event"), dict):
                    raise VlmTestError(409, "rtcv_candidate_missing", "RT-CV completed without a candidate")
                job["rtcv_status"] = "candidate_created"
            elif status == "no_candidate":
                job.update(
                    {
                        "rtcv_status": "completed_no_candidate",
                        "vlm_status": "awaiting_rtcv_candidate",
                        "status": "no_rtcv_candidate",
                        "required_capability": "rtcv_candidate_event",
                    }
                )
            else:
                job.update(
                    {
                        "rtcv_status": "failed",
                        "vlm_status": "failed",
                        "status": "failed",
                        "required_capability": "rtcv_file_batch",
                    }
                )
            if detail:
                job["rtcv_message"] = detail[:240]
            job["updated_at"] = utc_now()
            self._save(value)
            return 200, self._public_job(job)

    def create_realtime(self, incident_id: str, incidents_url: str, media_url: str) -> tuple[int, dict[str, Any]]:
        _safe_id(incident_id, "incident_id")
        _, payload = _request_json(incidents_url, "GET", f"/api/v1/candidates/{incident_id}")
        incident = payload.get("incident") if isinstance(payload, dict) else None
        if not isinstance(incident, dict):
            raise VlmTestError(502, "invalid_candidate", "incident queue returned an invalid candidate", retryable=True)
        validate_identity(incident, "realtime candidate")
        camera_id = str(incident.get("camera_id", ""))
        if CAMERA_ID_PATTERN.fullmatch(camera_id) is None:
            raise VlmTestError(502, "candidate_contract_invalid", "realtime candidate camera_id is invalid")
        if incident.get("candidate") is not True or incident.get("evaluation") is True:
            raise VlmTestError(409, "candidate_not_eligible", "candidate is not eligible for VLM test")
        if str(incident.get("asset_uri", "")) != f"selected-clip://{incident_id}.mp4":
            raise VlmTestError(409, "selected_clip_not_ready", "candidate does not have a selected clip")
        start = parse_utc(incident.get("start_time"), "candidate.start_time")
        end = parse_utc(incident.get("end_time"), "candidate.end_time")
        if end <= start:
            raise VlmTestError(502, "candidate_contract_invalid", "candidate time window is invalid")
        body = _request_binary(media_url, f"/media/{incident_id}.mp4")
        content_sha = digest(body)
        job_id = self._new_id(f"realtime|{incident_id}|{content_sha}")
        with self.lock:
            value = self._load()
            for existing in value["jobs"].values():
                if (
                    isinstance(existing, dict)
                    and existing.get("source_type") == "realtime"
                    and existing.get("incident_id") == incident_id
                    and existing.get("content_sha256") == content_sha
                    and existing.get("status") not in {"failed", "cancelled"}
                ):
                    return 200, self._public_job(existing)
            target = self._path(self.staging, job_id, ".mp4")
            temporary = target.with_suffix(".mp4.tmp")
            temporary.write_bytes(body)
            os.replace(temporary, target)
            candidate = {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "camera_id": camera_id,
                "event_id": str(incident["event_id"]),
                "event_type": str(incident["event_type"]),
                "model_id": str(incident.get("source_model_id") or incident.get("model_id") or "unknown"),
                "model_version": str(incident.get("source_model_version") or incident.get("model_version") or "unknown"),
                "start_time": incident["start_time"],
                "end_time": incident["end_time"],
                "candidate": True,
                "evaluation": False,
                "evidence": incident.get("evidence", {}),
            }
            now = utc_now()
            job = {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "job_id": job_id,
                "camera_id": camera_id,
                "source_type": "realtime",
                "incident_id": incident_id,
                "filename": f"{incident_id}.mp4",
                "extension": ".mp4",
                "content_sha256": content_sha,
                "bytes": len(body),
                "asset_uri": f"vlm-stage://{job_id}.mp4",
                "storage_state": "staging_only",
                "rtcv_status": "candidate_received",
                "vlm_status": "ready_to_launch",
                "status": "ready_to_launch",
                "required_capability": None,
                "candidate_event": candidate,
                "incident": incident,
                "created_at": now,
                "updated_at": now,
                "saved_at": None,
                "stored_asset_id": None,
                "vlm_result": None,
                "provenance": {
                    "plane": "selected-media-to-vlm-test-staging",
                    "selected_media_source": "phase10-incident-queue",
                    "raw_archive_scanned": False,
                    "store_before_vlm": False,
                },
            }
            value["jobs"][job_id] = job
            self._save(value)
        log("info", "realtime_candidate_staged", job_id=job_id, incident_id=incident_id)
        return 201, self._public_job(job)

    def create_store_retest(self, asset_id: str) -> tuple[int, dict[str, Any]]:
        _safe_id(asset_id, "asset_id")
        with self.lock:
            value = self._load()
            asset = self._asset(value, asset_id)
            extension = str(asset.get("extension", ".mp4"))
            if extension not in {".mp4", ".mkv"}:
                raise VlmTestError(500, "store_asset_invalid", "Store asset extension is invalid")
            media = self._path(self.store, asset_id, extension)
            if not media.is_file():
                raise VlmTestError(404, "store_media_not_found", "Store media file is missing")
            job_id = self._new_id(f"store-retest|{asset_id}")
            now = utc_now()
            job = {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "job_id": job_id,
                "camera_id": asset["camera_id"],
                "source_type": "store_retest",
                "parent_store_asset_id": asset_id,
                "filename": asset["filename"],
                "extension": extension,
                "content_sha256": asset["content_sha256"],
                "bytes": asset["bytes"],
                "asset_uri": f"vlm-store://{asset_id}{extension}",
                "storage_state": "stored",
                "rtcv_status": "not_required_store_retest",
                "vlm_status": "ready_to_launch",
                "status": "ready_to_launch",
                "required_capability": None,
                "candidate_event": asset.get("candidate_event"),
                "created_at": now,
                "updated_at": now,
                "saved_at": None,
                "stored_asset_id": asset_id,
                "vlm_result": None,
                "provenance": {
                    "plane": "post-vlm-store-to-vlm-test",
                    "raw_archive_scanned": False,
                    "store_before_vlm": True,
                },
            }
            value["jobs"][job_id] = job
            self._save(value)
        return 201, self._public_job(job)

    def launch(self, job_id: str, verifier_url: str) -> tuple[int, dict[str, Any]]:
        _safe_id(job_id, "job_id")
        with self.lock:
            value = self._load()
            job = self._job(value, job_id)
            if job.get("source_type") == "upload" and not job.get("candidate_event"):
                raise VlmTestError(
                    409,
                    "rtcv_file_batch_unavailable",
                    "RT-CV candidate is not ready; wait for the automatic RT-CV file workflow before launching VLM",
                    details={
                        "status": "WAITING",
                        "required_capability": "rtcv_file_batch",
                        "storage_state": job.get("storage_state"),
                    },
                )
            if job.get("vlm_status") in {"queued", "running"}:
                return 202, self._public_job(job)
            if job.get("vlm_status") == "completed":
                return 200, self._public_job(job)
            job.update(
                {
                    "status": "queued_for_vlm",
                    "vlm_status": "queued",
                    "updated_at": utc_now(),
                    "blocked_gate": None,
                    "error_code": None,
                    "error_message": None,
                }
            )
            self._save(value)
            snapshot = self._public_job(job)
        thread = threading.Thread(
            target=self._run_vlm,
            args=(job_id, verifier_url),
            name=f"vlm-test-{job_id[:12]}",
            daemon=True,
        )
        thread.start()
        log("info", "vlm_launch_queued", job_id=job_id, source_type=snapshot.get("source_type"))
        return 202, snapshot

    def _run_vlm(self, job_id: str, verifier_url: str) -> None:
        with self.lock:
            value = self._load()
            try:
                job = self._job(value, job_id)
            except VlmTestError:
                return
            job["vlm_status"] = "running"
            job["status"] = "running"
            job["started_at"] = utc_now()
            job["updated_at"] = job["started_at"]
            self._save(value)
            candidate = job.get("candidate_event")
            if not isinstance(candidate, dict):
                candidate = {}
            payload = {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "camera_id": job.get("camera_id"),
                "job_id": job_id,
                "source_type": job.get("source_type"),
                "candidate_id": job.get("incident_id") or candidate.get("event_id") or job_id,
                "event_type": candidate.get("event_type", "candidate event"),
                "start_time": candidate.get("start_time") or job.get("created_at"),
                "end_time": candidate.get("end_time") or job.get("updated_at"),
                "asset_uri": job.get("asset_uri"),
                "asset_sha256": job.get("content_sha256"),
                "model_id": candidate.get("model_id", "unknown"),
                "model_version": candidate.get("model_version", "unknown"),
            }
        try:
            status, result = _request_json(
                verifier_url,
                "POST",
                "/api/v1/vlm-tests/verify",
                payload=payload,
                timeout=360,
            )
            if status == 503:
                with self.lock:
                    value = self._load()
                    job = self._job(value, job_id)
                    job.update(
                        {
                            "vlm_status": "waiting_for_admission",
                            "status": "waiting_for_gpu",
                            "blocked_gate": "local_vlm_lease",
                            "updated_at": utc_now(),
                            "provider_response": result if isinstance(result, dict) else None,
                        }
                    )
                    self._save(value)
                log("warning", "vlm_waiting_for_admission", job_id=job_id)
                return
            if status != 200 or not isinstance(result, dict) or result.get("status") != "completed":
                raise VlmTestError(502, "vlm_provider_rejected", "VLM verifier did not complete the test", retryable=True)
            with self.lock:
                value = self._load()
                job = self._job(value, job_id)
                job.update(
                    {
                        "vlm_status": "completed",
                        "status": "completed",
                        "vlm_result": result,
                        "verdict": result.get("verdict"),
                        "confidence": result.get("confidence"),
                        "reason": result.get("reason"),
                        "completed_at": utc_now(),
                        "updated_at": utc_now(),
                        "blocked_gate": None,
                        "error_code": None,
                        "error_message": None,
                    }
                )
                self._save(value)
            log("info", "vlm_test_completed", job_id=job_id, verdict=result.get("verdict"))
        except VlmTestError as error:
            with self.lock:
                value = self._load()
                job = self._job(value, job_id)
                job.update(
                    {
                        "vlm_status": "failed",
                        "status": "failed",
                        "error_code": error.code,
                        "error_message": error.message,
                        "updated_at": utc_now(),
                    }
                )
                self._save(value)
            log("error", "vlm_test_failed", job_id=job_id, error_code=error.code)
        except Exception as error:
            with self.lock:
                value = self._load()
                job = self._job(value, job_id)
                job.update(
                    {
                        "vlm_status": "failed",
                        "status": "failed",
                        "error_code": "vlm_worker_error",
                        "error_message": type(error).__name__,
                        "updated_at": utc_now(),
                    }
                )
                self._save(value)
            log("error", "vlm_test_worker_failed", job_id=job_id, error_type=type(error).__name__)

    def save_after_vlm(self, job_id: str) -> tuple[int, dict[str, Any]]:
        _safe_id(job_id, "job_id")
        with self.lock:
            value = self._load()
            job = self._job(value, job_id)
            if job.get("vlm_status") != "completed" or not isinstance(job.get("vlm_result"), dict):
                raise VlmTestError(409, "vlm_result_required", "only a completed VLM test can be saved to Store")
            if job.get("stored_asset_id"):
                asset = self._asset(value, str(job["stored_asset_id"]))
                return 200, self._public_asset(asset)
            extension = str(job.get("extension", ".mp4"))
            source = self._path(
                self.store if job.get("source_type") == "store_retest" else self.staging,
                str(job.get("parent_store_asset_id") or job_id),
                extension,
            )
            if job.get("source_type") == "store_retest":
                source = self._path(self.store, str(job["parent_store_asset_id"]), extension)
            if not source.is_file():
                raise VlmTestError(404, "staging_media_not_found", "VLM-tested media is no longer available")
            content = source.read_bytes()
            content_sha = digest(content)
            if content_sha != job.get("content_sha256"):
                raise VlmTestError(409, "media_digest_mismatch", "VLM-tested media changed before Save")
            asset_id = content_sha
            target = self._path(self.store, asset_id, extension)
            if not target.exists():
                temporary = target.with_suffix(target.suffix + ".tmp")
                shutil.copy2(source, temporary)
                os.replace(temporary, target)
            now = utc_now()
            asset = value["assets"].get(asset_id)
            if not isinstance(asset, dict):
                asset = {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": STORE_ID,
                    "asset_id": asset_id,
                    "camera_id": job["camera_id"],
                    "filename": job["filename"],
                    "extension": extension,
                    "content_sha256": asset_id,
                    "bytes": len(content),
                    "asset_uri": f"vlm-store://{asset_id}{extension}",
                    "storage_state": "stored_after_vlm",
                    "created_at": now,
                    "updated_at": now,
                    "source_type": job["source_type"],
                    "source_job_ids": [],
                    "candidate_event": job.get("candidate_event"),
                    "vlm_result": job["vlm_result"],
                    "verdict": job.get("verdict"),
                    "confidence": job.get("confidence"),
                    "reason": job.get("reason"),
                    "model_id": VLM_MODEL_ID,
                    "model_version": VLM_MODEL_VERSION,
                    "prompt_version": PROMPT_VERSION,
                    "provenance": {
                        "plane": "vlm-test-store",
                        "raw_archive_scanned": False,
                        "saved_only_after_vlm": True,
                    },
                }
            source_jobs = asset.setdefault("source_job_ids", [])
            if job_id not in source_jobs:
                source_jobs.append(job_id)
                del source_jobs[:-50]
            asset["updated_at"] = now
            value["assets"][asset_id] = asset
            job.update(
                {
                    "storage_state": "stored_after_vlm",
                    "stored_asset_id": asset_id,
                    "saved_at": now,
                    "updated_at": now,
                }
            )
            self._save(value)
        log("info", "vlm_result_saved", job_id=job_id, asset_id=asset_id)
        return 201, self._public_asset(asset)

    def jobs(self) -> dict[str, Any]:
        with self.lock:
            value = self._load()
            jobs = [self._public_job(item) for item in value["jobs"].values() if isinstance(item, dict)]
        jobs.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("job_id", ""))), reverse=True)
        return {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "jobs": jobs[:200]}

    def job(self, job_id: str) -> dict[str, Any]:
        _safe_id(job_id, "job_id")
        with self.lock:
            return self._public_job(self._job(self._load(), job_id))

    def assets(self) -> dict[str, Any]:
        with self.lock:
            value = self._load()
            assets = [self._public_asset(item) for item in value["assets"].values() if isinstance(item, dict)]
        assets.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("asset_id", ""))), reverse=True)
        return {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "assets": assets[:200]}

    def open_media(self, asset_id: str, *, job: bool = False) -> tuple[Path, str]:
        _safe_id(asset_id, "media_id")
        with self.lock:
            value = self._load()
            if job:
                record = self._job(value, asset_id)
                root = self.store if record.get("source_type") == "store_retest" else self.staging
                identifier = str(record.get("parent_store_asset_id") or asset_id) if record.get("source_type") == "store_retest" else asset_id
                extension = str(record.get("extension", ".mp4"))
            else:
                record = self._asset(value, asset_id)
                root = self.store
                identifier = asset_id
                extension = str(record.get("extension", ".mp4"))
            path = self._path(root, identifier, extension)
            if not path.is_file():
                raise VlmTestError(404, "media_not_found", "media file was not found")
            return path, "video/mp4" if extension == ".mp4" else "video/x-matroska"

    def realtime_candidates(self, incidents_url: str) -> dict[str, Any]:
        status, value = _request_json(incidents_url, "GET", "/api/v1/candidates?limit=50")
        if status != 200 or not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
            raise VlmTestError(502, "invalid_candidates", "incident queue returned invalid candidates", retryable=True)
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "candidates": [item for item in value["candidates"] if isinstance(item, dict)][:MAX_CANDIDATES],
        }

    def state(self) -> dict[str, Any]:
        with self.lock:
            value = self._load()
            jobs = list(value["jobs"].values())
            assets = list(value["assets"].values())
            return {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "camera_id": DEFAULT_CAMERA_ID,
                "status": "ready",
                "upload_store_policy": "staging_until_explicit_save_after_vlm",
                "raw_video_plane_independent": True,
                "rtcv_file_batch": "deployed_auto_sequence",
                "vlm_model_id": VLM_MODEL_ID,
                "vlm_model_version": VLM_MODEL_VERSION,
                "prompt_version": PROMPT_VERSION,
                "jobs": len(jobs),
                "stored_assets": len(assets),
                "running_jobs": sum(item.get("vlm_status") in {"queued", "running"} for item in jobs if isinstance(item, dict)),
            }


class Handler(BaseHTTPRequestHandler):
    store: TestStore
    incidents_url: str
    media_url: str
    verifier_url: str

    def _json(self, status: int, value: Any) -> None:
        content = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _request_id(self) -> str:
        value = self.headers.get("X-Request-ID", "")
        return value[:100] if value else uuid.uuid4().hex

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > 256 * 1024:
            raise VlmTestError(400, "invalid_request_size", "JSON request size is invalid")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise VlmTestError(400, "invalid_request", "request body must be an object")
        return value

    def _read_upload(self) -> tuple[str, str, bytes, str]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_UPLOAD_BYTES:
            raise VlmTestError(400, "invalid_upload_size", "video size is outside the configured limit")
        filename = self.headers.get("X-File-Name", "")
        content_type = self.headers.get("Content-Type", "video/mp4").split(";", 1)[0].lower()
        idempotency_key = self.headers.get("Idempotency-Key", "")
        return filename, content_type, self.rfile.read(length), idempotency_key

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        request_id = self._request_id()
        try:
            if path == "/health/live":
                self._json(200, {"status": "live", "schema_version": SCHEMA_VERSION, "store_id": STORE_ID})
            elif path == "/health/ready":
                self._json(200, self.store.state())
            elif path == "/metrics":
                state = self.store.state()
                content = (
                    f"phase15_vlm_test_jobs {state['jobs']}\n"
                    f"phase15_vlm_test_stored_assets {state['stored_assets']}\n"
                    f"phase15_vlm_test_running_jobs {state['running_jobs']}\n"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif path == "/api/v1/state":
                self._json(200, self.store.state())
            elif path == "/api/v1/jobs":
                self._json(200, self.store.jobs())
            elif path == "/api/v1/store":
                self._json(200, self.store.assets())
            elif path == "/api/v1/realtime/candidates":
                self._json(200, self.store.realtime_candidates(self.incidents_url))
            else:
                match = __import__("re").fullmatch(r"/api/v1/jobs/([0-9a-f]{64})", path)
                if match:
                    self._json(200, self.store.job(match.group(1)))
                    return
                match = __import__("re").fullmatch(r"/api/v1/jobs/([0-9a-f]{64})/media", path)
                if match:
                    media, content_type = self.store.open_media(match.group(1), job=True)
                    self._send_media(media, content_type)
                    return
                match = __import__("re").fullmatch(r"/api/v1/store/([0-9a-f]{64})/media", path)
                if match:
                    media, content_type = self.store.open_media(match.group(1))
                    self._send_media(media, content_type)
                    return
                self._json(404, {"status": "not_found", "request_id": request_id})
        except VlmTestError as error:
            self._json(error.status, error.public(request_id))
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"status": "rejected", "request_id": request_id})

    def _send_media(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        request_id = self._request_id()
        try:
            if path == "/api/v1/uploads":
                filename, content_type, body, key = self._read_upload()
                self._json(*self.store.create_upload(filename, content_type, body, key))
                return
            if path == "/api/v1/realtime/candidates":
                payload = self._read_json()
                incident_id = str(payload.get("incident_id", ""))
                status, job = self.store.create_realtime(incident_id, self.incidents_url, self.media_url)
                status, launched = self.store.launch(str(job["job_id"]), self.verifier_url)
                self._json(status, launched)
                return
            if path == "/api/v1/realtime/candidates/stage":
                payload = self._read_json()
                incident_id = str(payload.get("incident_id", ""))
                self._json(*self.store.create_realtime(incident_id, self.incidents_url, self.media_url))
                return
            match = __import__("re").fullmatch(r"/api/v1/jobs/([0-9a-f]{64})/candidate", path)
            if match:
                candidate = self._read_json()
                self._json(*self.store.add_candidate(match.group(1), candidate))
                return
            match = __import__("re").fullmatch(r"/api/v1/jobs/([0-9a-f]{64})/rtcv-status", path)
            if match:
                payload = self._read_json()
                self._json(
                    *self.store.update_rtcv_status(
                        match.group(1),
                        str(payload.get("status", "")),
                        str(payload.get("message", "")),
                    )
                )
                return
            match = __import__("re").fullmatch(r"/api/v1/jobs/([0-9a-f]{64})/launch", path)
            if match:
                payload = self._read_json()
                if payload:
                    raise VlmTestError(400, "unexpected_payload", "launch accepts an empty JSON object")
                self._json(*self.store.launch(match.group(1), self.verifier_url))
                return
            match = __import__("re").fullmatch(r"/api/v1/jobs/([0-9a-f]{64})/save", path)
            if match:
                payload = self._read_json()
                if payload:
                    raise VlmTestError(400, "unexpected_payload", "save accepts an empty JSON object")
                self._json(*self.store.save_after_vlm(match.group(1)))
                return
            match = __import__("re").fullmatch(r"/api/v1/store/([0-9a-f]{64})/launch", path)
            if match:
                payload = self._read_json()
                if payload:
                    raise VlmTestError(400, "unexpected_payload", "launch accepts an empty JSON object")
                status, job = self.store.create_store_retest(match.group(1))
                status, launched = self.store.launch(str(job["job_id"]), self.verifier_url)
                self._json(status, launched)
                return
            match = __import__("re").fullmatch(r"/api/v1/store/([0-9a-f]{64})/stage", path)
            if match:
                self._read_json()
                self._json(*self.store.create_store_retest(match.group(1)))
                return
            self._json(404, {"status": "not_found", "request_id": request_id})
        except VlmTestError as error:
            self._json(error.status, error.public(request_id))
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"status": "rejected", "message": str(error)[:200], "request_id": request_id})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    root = Path(os.environ.get("VLM_TEST_RUNTIME_DIR", "runtime/phase15/vlm-test"))
    Handler.store = TestStore(root)
    Handler.incidents_url = os.environ.get("INCIDENTS_URL", "http://127.0.0.1:39121")
    Handler.media_url = os.environ.get("SELECTED_MEDIA_URL", "http://127.0.0.1:39120")
    Handler.verifier_url = os.environ.get("ALERT_VERIFICATION_URL", "http://127.0.0.1:39120")
    host = os.environ.get("HTTP_HOST", "127.0.0.1")
    if host != "127.0.0.1":
        raise RuntimeError("VLM-test must bind to loopback")
    port = int(os.environ.get("HTTP_PORT", "39520"))
    server = ThreadingHTTPServer((host, port), Handler)
    log("info", "service_started", port=port, root=str(root))
    try:
        server.serve_forever()
    finally:
        server.server_close()
        log("info", "service_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
