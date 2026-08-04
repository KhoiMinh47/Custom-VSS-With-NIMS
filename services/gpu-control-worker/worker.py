from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api"))

from gpu_control import (  # noqa: E402
    BUSY_STATUSES,
    LEGACY_STOP_SCRIPTS,
    MODEL_CONTROL_BY_ID,
    MODEL_CONTROLS,
    PROFILE_BY_ID,
    PROFILE_BY_LEASE,
    atomic_write,
    utc_now,
)


ALLOWED_ROLES = {"operator", "model_engineer", "admin"}
stop_requested = False
log_path: Path | None = None
JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GPU_RESERVED_MEMORY_MIB = int(os.environ.get("VSS_GPU_RESERVED_MEMORY_MIB", str(5 * 1024)))


def structured_log(event: str, **fields: Any) -> None:
    line = json.dumps(
        {
            "@timestamp": utc_now(),
            "level": "INFO",
            "service": "phase15-gpu-control-worker",
            "event": event,
            **fields,
        },
        separators=(",", ":"),
    )
    print(line, flush=True)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def gpu_telemetry() -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.used,memory.free,utilization.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        total, used, free, utilization, power = [
            value.strip() for value in result.stdout.splitlines()[0].split(",")
        ]
        return {
            "memory_total_mib": int(total),
            "memory_used_mib": int(used),
            "memory_free_mib": int(free),
            "reserved_memory_mib": GPU_RESERVED_MEMORY_MIB,
            "reserve_satisfied": int(free) >= GPU_RESERVED_MEMORY_MIB,
            "utilization_percent": int(utilization),
            "power_watts": float(power),
        }
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def granted_leases(admission_root: Path) -> list[Path]:
    leases: list[Path] = []
    for path in sorted(admission_root.glob("*.lease")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("status") == "granted":
            leases.append(path)
    return leases


def run_script(
    relative: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    args: tuple[str, ...] = (),
    env_updates: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = (ROOT / relative).resolve()
    scripts_root = (ROOT / "scripts").resolve()
    if script.parent != scripts_root or not script.is_file():
        raise ValueError("control script is not allowlisted")
    structured_log("script_started", script=script.name)
    environment = os.environ.copy()
    if env_updates:
        environment.update(env_updates)
    result = runner(
        ["/bin/bash", str(script), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=1200,
        env=environment,
    )
    structured_log(
        "script_finished",
        script=script.name,
        returncode=result.returncode,
    )
    return result


def stop_active_profiles(
    admission_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    for lease in granted_leases(admission_root):
        profile = PROFILE_BY_LEASE.get(lease.name)
        stop_script = profile.get("stop_script") if profile else LEGACY_STOP_SCRIPTS.get(lease.name)
        if not stop_script:
            raise RuntimeError(f"active lease {lease.name} has no safe stop mapping")
        result = run_script(str(stop_script), runner=runner)
        if result.returncode != 0:
            raise RuntimeError(f"failed to stop active profile for {lease.name}")


GPU_WORKFLOW_CONTAINERS = (
    "ntc-vss-phase07-rtcv",
    "ntc-vss-phase15-rtcv-file-batch",
    "ntc-vss-retail-poc-gpu-poc-nemotron-1",
    "ntc-vss-retail-poc-gpu-poc-cosmos3-1",
    "ntc-vss-phase11-rt-vlm",
    "ntc-vss-phase12-rt-embedding",
    "ntc-vss-phase12-siglip-object",
    "ntc-vss-rt-embed",
    "ntc-vss-retail-model",
)


def stop_active_gpu_workloads_no_restore(
    admission_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Release GPU workloads without trying to restart physical RT-CV.

    The VLM-test workflow is a bounded file job. Calling the normal profile
    stop scripts here would attempt to restore a physical camera and can
    leave the upload workflow half-transitioned, so this path only stops the
    exact known containers and revokes their leases.
    """
    running_result = runner(
        ["docker", "ps", "--format", "{{.Names}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if running_result.returncode != 0:
        raise RuntimeError("could not inspect running GPU containers")
    running = {line.strip() for line in running_result.stdout.splitlines() if line.strip()}
    for name in GPU_WORKFLOW_CONTAINERS:
        if name not in running:
            continue
        result = runner(
            ["docker", "stop", name],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to stop GPU workload {name}")

    admission_script = ROOT / "services/gpu-admission-controller/admission.py"
    for lease in granted_leases(admission_root):
        if lease.name not in PROFILE_BY_LEASE and lease.name != "vlm-test-rtcv.lease":
            raise RuntimeError(f"active lease {lease.name} has no VLM-test stop mapping")
        result = runner(
            [sys.executable, str(admission_script), "revoke", "--lease", str(lease)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to revoke active lease {lease.name}")


def stop_model_control(
    model_id: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    model = MODEL_CONTROL_BY_ID.get(model_id)
    if model is None:
        raise ValueError("unsupported model control")
    result = run_script(
        str(model["stop_script"]),
        runner=runner,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail[-300:] or f"failed to stop {model_id}")


def model_power_transition(
    model_id: str,
    enabled: bool,
    admission_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    model = MODEL_CONTROL_BY_ID.get(model_id)
    if model is None:
        raise ValueError("unsupported model control")
    model_leases = {str(item["lease"]) for item in MODEL_CONTROLS}
    active = granted_leases(admission_root)
    active_names = {path.name for path in active}
    target_lease = str(model["lease"])

    if not enabled:
        stop_model_control(model_id, runner=runner)
        return f"{model['short_title']} đã offline; RT-CV không được tự bật."

    if target_lease in active_names:
        return f"{model['short_title']} đã online; không cần bật lại."

    unrelated = sorted(active_names.difference(model_leases))
    if unrelated:
        raise RuntimeError(
            "Không thể bật model khi GPU profile khác đang hoạt động: "
            + ", ".join(unrelated)
        )

    for other in MODEL_CONTROLS:
        other_id = str(other["id"])
        if other_id != model_id and str(other["lease"]) in active_names:
            stop_model_control(other_id, runner=runner)

    result = run_script(
        str(model["start_script"]),
        runner=runner,
        env_updates={
            str(key): str(value)
            for key, value in dict(model.get("start_env") or {}).items()
        },
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail[-300:] or f"failed to start {model_id}")
    if str(model["lease"]) not in {path.name for path in granted_leases(admission_root)}:
        raise RuntimeError(f"{model_id} started without an admission lease")
    return f"{model['short_title']} đã online; RT-CV chỉ dành cho upload VLM Test."


def transition(
    target_profile: str,
    admission_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    profile = PROFILE_BY_ID.get(target_profile)
    if profile is None:
        raise ValueError("unsupported GPU profile")

    active = granted_leases(admission_root)
    if len(active) == 1 and profile.get("lease") == active[0].name:
        return "Profile đã hoạt động; không cần chuyển."

    stop_active_profiles(admission_root, runner=runner)
    if granted_leases(admission_root):
        raise RuntimeError("GPU lease vẫn còn sau bước dừng an toàn")

    result = run_script(str(profile["start_script"]), runner=runner)
    if result.returncode != 0:
        recovery = run_script("scripts/start-default-alerting.sh", runner=runner)
        if recovery.returncode == 0:
            raise RuntimeError("Không thể bật profile; đã khôi phục Camera realtime.")
        raise RuntimeError("Không thể bật profile và khôi phục realtime cũng thất bại.")
    return f"Đã chuyển sang {profile['title']}."


def managed_job_status(job_root: Path, job_id: str) -> str | None:
    """Read only the allowlisted persisted Phase 13 job state."""
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("managed job ID is invalid")
    path = (job_root / f"{job_id}.json").resolve()
    if path.parent != job_root.resolve() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return str(value.get("status") or "") if isinstance(value, dict) else None


def wait_for_managed_job(
    job_root: Path,
    job_id: str,
    target_profile: str,
    *,
    poll_seconds: float = 2.0,
    timeout_seconds: float = 21600.0,
) -> str:
    """Wait for the selected Phase 13 stage before restoring realtime."""
    if target_profile not in {"summary_caption", "summary_reasoning"}:
        raise ValueError("managed lifecycle requires a summary profile")
    deadline = time.monotonic() + timeout_seconds
    seen = False
    while time.monotonic() < deadline:
        status = managed_job_status(job_root, job_id)
        if status is not None:
            seen = True
            if status == "failed":
                raise RuntimeError(f"summary job {job_id} failed")
            if target_profile == "summary_caption" and status in {"queued_summary", "completed"}:
                return status
            if target_profile == "summary_reasoning" and status == "completed":
                return status
        elif seen:
            raise RuntimeError(f"summary job {job_id} disappeared")
        time.sleep(max(0.25, poll_seconds))
    raise RuntimeError(f"summary job {job_id} lifecycle timed out")


def validate_command(command: dict[str, Any], expected_id: str) -> None:
    if command.get("command_id") != expected_id:
        raise ValueError("command ID mismatch")
    if command.get("action") != "switch_profile":
        raise ValueError("unsupported command action")
    if command.get("target_profile") not in PROFILE_BY_ID:
        raise ValueError("unsupported target profile")
    if command.get("requested_role") not in ALLOWED_ROLES:
        raise ValueError("request role cannot control GPU")
    if command.get("status") not in BUSY_STATUSES:
        raise ValueError("request is not executable")
    managed_job_id = command.get("managed_job_id")
    auto_restore = command.get("auto_restore")
    if managed_job_id is not None:
        if not isinstance(managed_job_id, str) or not JOB_ID_PATTERN.fullmatch(managed_job_id):
            raise ValueError("managed job ID is invalid")
        if command.get("target_profile") not in {"summary_caption", "summary_reasoning"}:
            raise ValueError("managed lifecycle requires a summary profile")
        if auto_restore is not True:
            raise ValueError("managed lifecycle requires auto_restore")
    elif auto_restore is True:
        raise ValueError("auto_restore requires a managed job ID")


def validate_model_power_command(command: dict[str, Any], expected_id: str) -> None:
    if command.get("command_id") != expected_id:
        raise ValueError("command ID mismatch")
    if command.get("action") != "set_model_power":
        raise ValueError("unsupported command action")
    if command.get("model_id") not in MODEL_CONTROL_BY_ID:
        raise ValueError("unsupported model control")
    if not isinstance(command.get("enabled"), bool):
        raise ValueError("model power enabled must be boolean")
    if command.get("requested_role") not in ALLOWED_ROLES:
        raise ValueError("request role cannot control GPU")
    if command.get("status") not in BUSY_STATUSES:
        raise ValueError("request is not executable")


def validate_vlm_test_command(command: dict[str, Any], expected_id: str) -> None:
    if command.get("command_id") != expected_id:
        raise ValueError("command ID mismatch")
    if command.get("action") != "run_vlm_test":
        raise ValueError("unsupported command action")
    if command.get("target_profile") != "vlm_test":
        raise ValueError("unsupported VLM-test target")
    if command.get("requested_role") not in ALLOWED_ROLES:
        raise ValueError("request role cannot control GPU")
    if command.get("status") not in BUSY_STATUSES:
        raise ValueError("request is not executable")
    job_id = command.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("VLM-test job ID is invalid")
    if command.get("workflow") not in {"upload_rtcv_vlm", "vlm_only"}:
        raise ValueError("unsupported VLM-test workflow")


def audit_transition(control_root: Path, command: dict[str, Any], outcome: str) -> None:
    audit_path = control_root.parent / "audit" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "@timestamp": utc_now(),
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "service": "phase15-gpu-control-worker",
        "request_id": str(command.get("request_id", ""))[:100],
        "subject": str(command.get("requested_by", "operator"))[:120],
        "role": str(command.get("requested_role", "operator"))[:32],
        "action": (
            "gpu.vlm_test.workflow"
            if command.get("action") == "run_vlm_test"
            else "gpu.model.power"
            if command.get("action") == "set_model_power"
            else "gpu.profile.switch"
        ),
        "resource": str(command.get("target_profile", ""))[:80],
        "outcome": outcome,
        "detail": {
            "command_id": str(command.get("command_id", ""))[:64],
            "mutating": True,
        },
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)


def process_request(
    path: Path,
    control_root: Path,
    admission_root: Path,
    job_root: Path | None = None,
) -> None:
    processing = control_root / "processing" / path.name
    processing.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, processing)
    try:
        command = json.loads(processing.read_text(encoding="utf-8"))
        if not isinstance(command, dict):
            raise ValueError("command must be an object")
        if command.get("action") == "run_vlm_test":
            validate_vlm_test_command(command, processing.stem)
            command.update(
                status="running",
                started_at=utc_now(),
                message="Đang chạy upload → RT-CV → VLM. Không đóng trang này.",
            )
            atomic_write(control_root / "state.json", command)
            stop_active_gpu_workloads_no_restore(admission_root)
            script = (
                "scripts/run-vlm-test-job.sh"
                if command.get("workflow") == "upload_rtcv_vlm"
                else "scripts/run-vlm-test-existing-job.sh"
            )
            result = run_script(
                script,
                env_updates={"VLM_TEST_JOB_ID": str(command["job_id"])},
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(detail[-300:] or "VLM-test workflow failed")
            message = "Upload → RT-CV → VLM đã hoàn tất theo thứ tự serialized."
        elif command.get("action") == "set_model_power":
            validate_model_power_command(command, processing.stem)
            command.update(
                status="running",
                started_at=utc_now(),
                message="Đang thay đổi trạng thái model GPU. RT-CV chỉ chạy trong upload VLM Test.",
            )
            atomic_write(control_root / "state.json", command)
            message = model_power_transition(
                str(command["model_id"]),
                bool(command["enabled"]),
                admission_root,
            )
        else:
            validate_command(command, processing.stem)
            command.update(
                status="running",
                started_at=utc_now(),
                message="Đang chuyển GPU profile. Không đóng trang này.",
            )
            atomic_write(control_root / "state.json", command)
            message = transition(str(command["target_profile"]), admission_root)
            managed_job_id = command.get("managed_job_id")
            if command.get("auto_restore") is True and managed_job_id:
                if job_root is None:
                    raise RuntimeError("managed job root is unavailable")
                stage_status = wait_for_managed_job(
                    job_root,
                    str(managed_job_id),
                    str(command["target_profile"]),
                )
                # The profile stop script revokes the fixed lease and restores
                # RT-CV. This runs only for an operator-confirmed managed job.
                stop_active_profiles(admission_root)
                if granted_leases(admission_root):
                    raise RuntimeError("GPU lease vẫn còn sau bước dừng an toàn")
                command["auto_restored"] = True
                command["managed_job_status"] = stage_status
                message = f"{message} Job {stage_status}; đã tự động khôi phục Camera realtime."
        command.update(
            status="completed",
            completed_at=utc_now(),
            message=message,
        )
        structured_log(
            "transition_completed",
            command_id=command["command_id"],
            target_profile=command["target_profile"],
        )
        audit_transition(control_root, command, "success")
    except Exception as error:  # the state must survive every command failure
        command = command if isinstance(locals().get("command"), dict) else {
            "command_id": processing.stem,
            "target_profile": None,
        }
        command.update(
            status="failed",
            completed_at=utc_now(),
            message=str(error)[:300],
        )
        structured_log(
            "transition_failed",
            command_id=processing.stem,
            error_type=type(error).__name__,
        )
        audit_transition(control_root, command, "failed")
    atomic_write(control_root / "state.json", command)
    atomic_write(processing, command)
    completed = control_root / "completed" / processing.name
    completed.parent.mkdir(parents=True, exist_ok=True)
    os.replace(processing, completed)


def heartbeat(control_root: Path) -> None:
    atomic_write(
        control_root / "worker.json",
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "status": "online",
            "pid": os.getpid(),
            "last_seen_at": utc_now(),
            "gpu": gpu_telemetry(),
        },
    )


def handle_stop(_signum: int, _frame: object) -> None:
    global stop_requested
    stop_requested = True


def serve(
    control_root: Path,
    admission_root: Path,
    poll_seconds: float,
    job_root: Path,
) -> int:
    control_root.mkdir(parents=True, exist_ok=True)
    for directory in ("requests", "processing", "completed"):
        (control_root / directory).mkdir(exist_ok=True)
    lock_path = control_root / "worker.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            structured_log("worker_already_running")
            return 2
        signal.signal(signal.SIGTERM, handle_stop)
        signal.signal(signal.SIGINT, handle_stop)
        structured_log("worker_started", project_root=str(ROOT))
        heartbeat_stop = threading.Event()

        def publish_heartbeat() -> None:
            heartbeat(control_root)
            while not heartbeat_stop.wait(poll_seconds):
                heartbeat(control_root)

        heartbeat_thread = threading.Thread(
            target=publish_heartbeat,
            name="gpu-control-heartbeat",
            daemon=True,
        )
        heartbeat_thread.start()
        while not stop_requested:
            requests = sorted((control_root / "requests").glob("*.json"))
            if requests:
                process_request(requests[0], control_root, admission_root, job_root)
            time.sleep(poll_seconds)
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=max(2.0, poll_seconds * 2))
    atomic_write(
        control_root / "worker.json",
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "status": "offline",
            "pid": os.getpid(),
            "last_seen_at": utc_now(),
            "gpu": gpu_telemetry(),
        },
    )
    structured_log("worker_stopped")
    return 0


def main() -> int:
    global log_path
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--control-root",
        type=Path,
        default=ROOT / "runtime/phase15/gpu-control",
    )
    parser.add_argument(
        "--admission-root",
        type=Path,
        default=ROOT / "runtime/gpu-admission",
    )
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument(
        "--job-root",
        type=Path,
        default=ROOT / "runtime/summarization/jobs",
    )
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args()
    log_path = args.log_file
    return serve(
        args.control_root,
        args.admission_root,
        max(0.25, args.poll_seconds),
        args.job_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
