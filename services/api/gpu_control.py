from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"

GPU_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "id": "realtime",
        "title": "Camera realtime",
        "short_title": "Realtime",
        "group": "camera",
        "description": "RT-CV, tracking và behavior analytics chạy ở chế độ mặc định.",
        "impact": "AI overlay hoạt động; các model theo nhu cầu được dừng.",
        "model": "RT-DETR + NvDCF",
        "recommended": True,
        "start_script": "scripts/start-default-alerting.sh",
        "lease": None,
        "stop_script": None,
    },
    {
        "id": "alert_verification",
        "title": "Xác minh cảnh báo đang chờ",
        "short_title": "Alert verification",
        "group": "alerts",
        "description": "Nạp Cosmos3 để xử lý hàng đợi cảnh báo hybrid Phase 10.",
        "impact": "Tạm dừng RT-CV; candidate và selected clip tiếp tục được lưu bền vững.",
        "model": "Cosmos3",
        "recommended": False,
        "start_script": "scripts/start-phase10-vlm.sh",
        "lease": "local-vlm.lease",
        "stop_script": "scripts/stop-phase10-vlm.sh",
    },
    {
        "id": "direct_alerts",
        "title": "Cảnh báo ngữ nghĩa",
        "short_title": "Direct RT-VLM",
        "group": "alerts",
        "description": "Phân tích semantic trực tiếp cho cam-01 theo cấu hình opt-in.",
        "impact": "Tạm dừng RT-CV và AI overlay trong lúc profile hoạt động.",
        "model": "Cosmos3 + VSS RT-VLM",
        "recommended": False,
        "start_script": "scripts/start-phase11-direct.sh",
        "lease": "direct-rt-vlm.lease",
        "stop_script": "scripts/stop-phase11-direct.sh",
    },
    {
        "id": "video_index",
        "title": "Lập chỉ mục video",
        "short_title": "Video embedding",
        "group": "search",
        "description": "Tạo action/video embedding cho các clip đã được chọn.",
        "impact": "Tạm dừng RT-CV; video live và dữ liệu đã index vẫn truy cập được.",
        "model": "Cosmos-Embed1",
        "recommended": False,
        "start_script": "scripts/start-phase12-rt-embedding.sh",
        "lease": "phase12-rt-embedding.lease",
        "stop_script": "scripts/stop-phase12-rt-embedding.sh",
    },
    {
        "id": "object_index",
        "title": "Lập chỉ mục đối tượng",
        "short_title": "Object embedding",
        "group": "search",
        "description": "Tạo embedding cho crop đối tượng và tìm kiếm bằng hình ảnh.",
        "impact": "Tạm dừng RT-CV trong cửa sổ xử lý.",
        "model": "SigLIP2",
        "recommended": False,
        "start_script": "scripts/start-phase12-siglip.sh",
        "lease": "phase12-siglip.lease",
        "stop_script": "scripts/stop-phase12-siglip.sh",
    },
    {
        "id": "search_assistant",
        "title": "Hiểu câu truy vấn",
        "short_title": "Search LLM",
        "group": "search",
        "description": "Phân rã truy vấn tìm kiếm phức tạp theo cửa sổ có kiểm soát.",
        "impact": "Tạm dừng RT-CV; tìm kiếm fallback vẫn hoạt động.",
        "model": "Nemotron",
        "recommended": False,
        "start_script": "scripts/start-phase12-llm.sh",
        "lease": "phase12-llm.lease",
        "stop_script": "scripts/stop-phase12-llm.sh",
    },
    {
        "id": "search_critic",
        "title": "Kiểm tra kết quả tìm kiếm",
        "short_title": "Search critic",
        "group": "search",
        "description": "VLM kiểm tra top-K kết quả đã xếp hạng.",
        "impact": "Tạm dừng RT-CV; kết quả gốc vẫn được giữ nếu critic dừng.",
        "model": "Cosmos3",
        "recommended": False,
        "start_script": "scripts/start-phase12-critic.sh",
        "lease": "phase12-critic.lease",
        "stop_script": "scripts/stop-phase12-critic.sh",
    },
    {
        "id": "summary_caption",
        "title": "Caption clip đã chọn",
        "short_title": "Caption",
        "group": "summary",
        "description": "Đọc các clip đã chọn và tạo sự kiện có timestamp.",
        "impact": "Tạm dừng RT-CV; checkpoint và video live vẫn được giữ.",
        "model": "Cosmos3",
        "recommended": False,
        "start_script": "scripts/start-phase13-vlm.sh",
        "lease": "phase13-vlm.lease",
        "stop_script": "scripts/stop-phase13-vlm.sh",
    },
    {
        "id": "summary_reasoning",
        "title": "Tạo tóm tắt & Q&A",
        "short_title": "Summary",
        "group": "summary",
        "description": "Tổng hợp caption thành summary, Q&A và báo cáo có evidence.",
        "impact": "Tạm dừng RT-CV trong lúc Nemotron được nạp.",
        "model": "Nemotron",
        "recommended": False,
        "start_script": "scripts/start-phase13-llm.sh",
        "lease": "phase13-llm.lease",
        "stop_script": "scripts/stop-phase13-llm.sh",
    },
)

# Model power controls are separate from generic profile switching. Turning a
# model off must not implicitly start RT-CV; RT-CV is upload-workflow-only.
MODEL_CONTROLS: tuple[dict[str, Any], ...] = (
    {
        "id": "llm",
        "title": "Nemotron LLM",
        "short_title": "LLM",
        "model": "NVIDIA Nemotron Nano 9B v2",
        "profile_id": "summary_reasoning",
        "lease": "phase13-llm.lease",
        "start_script": "scripts/start-phase13-llm.sh",
        "start_env": {"START_PHASE13_LLM_RESTORE_RTCV": "false"},
        "stop_script": "scripts/stop-model-llm.sh",
    },
    {
        "id": "vlm",
        "title": "Cosmos3 VLM",
        "short_title": "VLM",
        "model": "NVIDIA Cosmos3 Nano Reasoner",
        "profile_id": "alert_verification",
        "lease": "local-vlm.lease",
        "start_script": "scripts/start-phase10-vlm.sh",
        "start_env": {"START_PHASE10_VLM_RESTORE_RTCV": "false"},
        "stop_script": "scripts/stop-model-vlm.sh",
    },
)

PROFILE_BY_ID = {profile["id"]: profile for profile in GPU_PROFILES}
PROFILE_BY_LEASE = {
    profile["lease"]: profile
    for profile in GPU_PROFILES
    if profile["lease"] is not None
}
MODEL_CONTROL_BY_ID = {model["id"]: model for model in MODEL_CONTROLS}
JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LEGACY_STOP_SCRIPTS: dict[str, str] = {}
BUSY_STATUSES = {"queued", "running", "recovering"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def public_profiles() -> list[dict[str, Any]]:
    private_fields = {"start_script", "stop_script", "lease"}
    return [
        {key: value for key, value in profile.items() if key not in private_fields}
        for profile in GPU_PROFILES
    ]


def public_model_controls() -> list[dict[str, Any]]:
    private_fields = {"lease", "start_script", "start_env", "stop_script"}
    return [
        {key: value for key, value in model.items() if key not in private_fields}
        for model in MODEL_CONTROLS
    ]


def _read_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def active_profile_ids(admission_root: Path) -> list[str]:
    active: list[str] = []
    if not admission_root.is_dir():
        return active
    for path in sorted(admission_root.glob("*.lease")):
        value = _read_object(path)
        if not value or value.get("status") != "granted":
            continue
        profile = PROFILE_BY_LEASE.get(path.name)
        active.append(profile["id"] if profile else f"external:{value.get('profile', path.stem)}")
    return active


def control_snapshot(control_root: Path, admission_root: Path) -> dict[str, Any]:
    command = _read_object(control_root / "state.json") or {
        "status": "idle",
        "target_profile": None,
        "message": "Sẵn sàng nhận thao tác.",
    }
    worker = _read_object(control_root / "worker.json") or {
        "status": "offline",
        "last_seen_at": None,
        "gpu": None,
    }
    last_seen = worker.get("last_seen_at")
    if worker.get("status") == "online" and isinstance(last_seen, str):
        try:
            heartbeat_age = (
                datetime.now(UTC) - datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            ).total_seconds()
            if heartbeat_age > 10:
                worker["status"] = "offline"
                worker["stale"] = True
        except ValueError:
            worker["status"] = "offline"
            worker["stale"] = True
    active = active_profile_ids(admission_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "profiles": public_profiles(),
        "active_profiles": active,
        "effective_profile": active[0] if len(active) == 1 else ("realtime" if not active else "multiple"),
        "command": command,
        "worker": worker,
        "generated_at": utc_now(),
    }


def model_control_snapshot(control_root: Path, admission_root: Path) -> dict[str, Any]:
    snapshot = control_snapshot(control_root, admission_root)
    command = snapshot.get("command") or {}
    models: list[dict[str, Any]] = []
    for model in MODEL_CONTROLS:
        model_id = str(model["id"])
        online = model["profile_id"] in snapshot["active_profiles"]
        state = "online" if online else "offline"
        message = (
            f"{model['short_title']} đang online và sẵn sàng."
            if online
            else f"{model['short_title']} đang offline."
        )
        if (
            command.get("action") == "set_model_power"
            and command.get("model_id") == model_id
            and command.get("status") in BUSY_STATUSES
        ):
            state = "starting" if command.get("enabled") is True else "stopping"
            message = str(command.get("message") or "Đang xử lý lệnh GPU.")
        elif (
            command.get("action") == "set_model_power"
            and command.get("model_id") == model_id
            and command.get("status") == "failed"
        ):
            state = "error"
            message = str(command.get("message") or "Không thể thay đổi trạng thái model.")
        models.append(
            {
                "id": model_id,
                "title": model["title"],
                "short_title": model["short_title"],
                "model": model["model"],
                "profile_id": model["profile_id"],
                "enabled": online,
                "state": state,
                "message": message,
            }
        )
    snapshot["models"] = models
    snapshot["rtcv_policy"] = "upload_only"
    return snapshot


def enqueue_switch(
    control_root: Path,
    *,
    target_profile: str,
    identity: dict[str, Any],
    request_id: str,
    confirmed: bool,
    managed_job_id: str | None = None,
    auto_restore: bool = False,
) -> dict[str, Any]:
    if target_profile not in PROFILE_BY_ID:
        raise ValueError("unsupported GPU profile")
    if confirmed is not True:
        raise ValueError("explicit confirmation is required")
    if managed_job_id is not None:
        if not JOB_ID_PATTERN.fullmatch(managed_job_id):
            raise ValueError("managed job ID is invalid")
        if target_profile not in {"summary_caption", "summary_reasoning"}:
            raise ValueError("managed job lifecycle is supported only for summary profiles")
        if auto_restore is not True:
            raise ValueError("managed job lifecycle requires auto_restore")
    elif auto_restore:
        raise ValueError("auto_restore requires a managed job ID")

    current = _read_object(control_root / "state.json") or {}
    if current.get("status") in BUSY_STATUSES:
        raise RuntimeError("another GPU transition is already active")

    command_id = uuid.uuid4().hex
    command = {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "command_id": command_id,
        "request_id": request_id,
        "action": "switch_profile",
        "target_profile": target_profile,
        "status": "queued",
        "requested_at": utc_now(),
        "requested_by": str(identity.get("subject", "operator"))[:120],
        "requested_role": str(identity.get("role", "operator"))[:32],
        "message": "Đã xếp hàng, chờ host worker thực thi.",
    }
    if managed_job_id is not None:
        command["managed_job_id"] = managed_job_id
        command["auto_restore"] = True
    request_path = control_root / "requests" / f"{command_id}.json"
    atomic_write(request_path, command)
    atomic_write(control_root / "state.json", command)
    return command


def enqueue_model_power(
    control_root: Path,
    *,
    model_id: str,
    enabled: bool,
    identity: dict[str, Any],
    request_id: str,
    confirmed: bool,
) -> dict[str, Any]:
    model = MODEL_CONTROL_BY_ID.get(model_id)
    if model is None:
        raise ValueError("unsupported model control")
    if confirmed is not True:
        raise ValueError("explicit confirmation is required")
    if str(identity.get("role", "")) not in {"operator", "model_engineer", "admin"}:
        raise ValueError("request role cannot control GPU")
    current = _read_object(control_root / "state.json") or {}
    if current.get("status") in BUSY_STATUSES:
        raise RuntimeError("another GPU transition is already active")
    command_id = uuid.uuid4().hex
    command = {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "command_id": command_id,
        "request_id": request_id,
        "action": "set_model_power",
        "model_id": model_id,
        "target_profile": model["profile_id"],
        "enabled": bool(enabled),
        "status": "queued",
        "requested_at": utc_now(),
        "requested_by": str(identity.get("subject", "operator"))[:120],
        "requested_role": str(identity.get("role", "operator"))[:32],
        "message": "Đã xếp hàng, chờ host worker thực thi.",
    }
    request_path = control_root / "requests" / f"{command_id}.json"
    atomic_write(request_path, command)
    atomic_write(control_root / "state.json", command)
    return command


def enqueue_vlm_test(
    control_root: Path,
    *,
    job_id: str,
    identity: dict[str, Any],
    request_id: str,
    workflow: str = "upload_rtcv_vlm",
) -> dict[str, Any]:
    """Queue the upload -> RT-CV -> VLM workflow on the host worker.

    This is intentionally a separate command from the public profile switch
    API: the worker owns the exact stop/start ordering and never restores the
    physical-camera RT-CV profile in the middle of a file-batch test.
    """
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("VLM-test job ID is invalid")
    if workflow not in {"upload_rtcv_vlm", "vlm_only"}:
        raise ValueError("unsupported VLM-test workflow")
    if str(identity.get("role", "")) not in {"operator", "model_engineer", "admin"}:
        raise ValueError("request role cannot control GPU")

    current = _read_object(control_root / "state.json") or {}
    if current.get("status") in BUSY_STATUSES:
        raise RuntimeError("another GPU transition is already active")

    command_id = uuid.uuid4().hex
    command = {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "command_id": command_id,
        "request_id": request_id,
        "action": "run_vlm_test",
        "target_profile": "vlm_test",
        "job_id": job_id,
        "workflow": workflow,
        "status": "queued",
        "requested_at": utc_now(),
        "requested_by": str(identity.get("subject", "operator"))[:120],
        "requested_role": str(identity.get("role", "operator"))[:32],
        "message": "Đã xếp hàng upload → RT-CV → VLM.",
    }
    request_path = control_root / "requests" / f"{command_id}.json"
    atomic_write(request_path, command)
    atomic_write(control_root / "state.json", command)
    return command
