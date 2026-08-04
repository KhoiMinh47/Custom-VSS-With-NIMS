from __future__ import annotations

import concurrent.futures
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
EXPECTED_STATES = {"always_on", "on_demand", "locked", "deferred"}
CATEGORIES = {"live", "analytics", "alerts", "search", "summary", "platform", "gpu"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_registry(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported service registry schema_version")
    if value.get("store_id") != STORE_ID:
        raise ValueError("service registry store_id must be store-001")
    services = value.get("services")
    if not isinstance(services, list) or not services:
        raise ValueError("service registry requires services")

    identifiers: set[str] = set()
    ports: set[int] = set()
    for service in services:
        if not isinstance(service, dict):
            raise ValueError("registry service must be an object")
        identifier = str(service.get("id", ""))
        if not identifier or identifier in identifiers:
            raise ValueError("service IDs must be non-empty and unique")
        identifiers.add(identifier)
        if service.get("expected_state") not in EXPECTED_STATES:
            raise ValueError(f"{identifier} has invalid expected_state")
        if service.get("category") not in CATEGORIES:
            raise ValueError(f"{identifier} has invalid category")
        port = service.get("port")
        if port is not None:
            if not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError(f"{identifier} has invalid port")
            if port in ports:
                raise ValueError(f"duplicate managed port: {port}")
            ports.add(port)
        for field in ("health_url", "public_url"):
            url = service.get(field)
            if url is not None and not str(url).startswith(("http://", "https://")):
                raise ValueError(f"{identifier} {field} must use http(s)")
    return value


def _probe(service: dict[str, Any], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    state = service["expected_state"]
    if state in {"locked", "deferred"}:
        return {
            **service,
            "status": state,
            "http_status": None,
            "latency_ms": None,
            "checked_at": utc_now(),
        }
    if service.get("probe_mode") == "browser_only":
        return {
            **service,
            "status": "browser_only",
            "http_status": None,
            "latency_ms": None,
            "checked_at": utc_now(),
        }
    url = service.get("health_url")
    if not url:
        return {
            **service,
            "status": "unknown",
            "http_status": None,
            "latency_ms": None,
            "checked_at": utc_now(),
        }
    request = Request(str(url), headers={"User-Agent": "ntc-phase15-health/1.0"})
    http_status: int | None = None
    try:
        with urlopen(request, timeout=timeout) as response:
            http_status = response.status
            response.read(256)
        status = "healthy" if 200 <= http_status < 400 else "degraded"
    except HTTPError as error:
        http_status = error.code
        status = "degraded" if state == "always_on" else "standby"
    except (URLError, TimeoutError, OSError):
        status = "unavailable" if state == "always_on" else "standby"
    return {
        **service,
        "status": status,
        "http_status": http_status,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "checked_at": utc_now(),
    }


def build_snapshot(registry: dict[str, Any], timeout: float = 1.5) -> dict[str, Any]:
    services = registry["services"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, len(services))) as pool:
        probed = list(pool.map(lambda service: _probe(service, timeout), services))
    counts = {
        status: sum(service["status"] == status for service in probed)
        for status in (
            "healthy",
            "degraded",
            "unavailable",
            "standby",
            "locked",
            "deferred",
            "unknown",
            "browser_only",
        )
    }
    always_on = [
        service
        for service in probed
        if service["expected_state"] == "always_on"
        and service.get("probe_mode") != "browser_only"
    ]
    ready = all(service["status"] == "healthy" for service in always_on)
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "generated_at": utc_now(),
        "ready": ready,
        "phase": "PHASE-15",
        "phase_status": "PARTIAL",
        "phase14_status": "LOCKED_BY_USER",
        "services": probed,
        "counts": counts,
        "managed_ports": sum(service.get("port") is not None for service in probed),
        "architecture": {
            "raw_video_plane_independent": True,
            "gpu_actions_require_operator_and_host_worker": True,
            "docker_socket_mounted_by_app": False,
            "topology": "experimental-rtx-pro-5000-blackwell",
        },
    }


def read_admission_state(root: Path) -> dict[str, Any]:
    leases: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.lease")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                leases.append({"lease": path.name, "status": "invalid"})
                continue
            leases.append(
                {
                    "lease": path.name,
                    "status": str(value.get("status", "unknown"))[:32],
                    "profile": str(value.get("profile", "unknown"))[:80],
                    "granted_at": value.get("granted_at") or value.get("issued_at"),
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "read_only": True,
        "leases": leases,
        "active_count": sum(lease.get("status") == "granted" for lease in leases),
        "generated_at": utc_now(),
    }
