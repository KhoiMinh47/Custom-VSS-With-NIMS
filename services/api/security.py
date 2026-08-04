from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


ROLE_ORDER = ("viewer", "analyst", "operator", "model_engineer", "admin")
DEFAULT_PERMISSIONS = {
    "viewer": {"overview:read", "services:read", "ports:read", "tools:list"},
    "analyst": {"overview:read", "services:read", "ports:read", "tools:list", "tools:execute"},
    "operator": {
        "overview:read",
        "services:read",
        "ports:read",
        "admission:read",
        "audit:read",
        "tools:list",
        "tools:execute",
        "gpu:control",
        "stream:control",
    },
    "model_engineer": {
        "overview:read",
        "services:read",
        "ports:read",
        "admission:read",
        "audit:read",
        "tools:list",
        "tools:execute",
        "gpu:control",
        "stream:control",
    },
    "admin": {"*"},
}
_AUDIT_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_tokens(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("principals"), list):
        raise ValueError("token store must contain principals")
    return [item for item in value["principals"] if isinstance(item, dict)]


def principal(
    headers: Mapping[str, str],
    token_store: Path,
    *,
    trusted_full_access: bool = False,
) -> dict[str, Any]:
    if trusted_full_access:
        return {
            "subject": "trusted-loopback",
            "role": "admin",
            "authenticated": True,
        }
    authorization = headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return {"subject": "anonymous", "role": "viewer", "authenticated": False}
    token = authorization[7:].strip()
    if not token or len(token) > 512:
        return {"subject": "anonymous", "role": "viewer", "authenticated": False}
    digest = hashlib.sha256(token.encode()).hexdigest()
    for item in _load_tokens(token_store):
        expected = str(item.get("token_sha256", ""))
        role = str(item.get("role", ""))
        if role in ROLE_ORDER and len(expected) == 64 and hmac.compare_digest(digest, expected):
            return {
                "subject": str(item.get("subject", "operator"))[:120],
                "role": role,
                "authenticated": True,
            }
    return {"subject": "anonymous", "role": "viewer", "authenticated": False}


def permitted(identity: dict[str, Any], permission: str) -> bool:
    permissions = DEFAULT_PERMISSIONS.get(str(identity.get("role")), set())
    return "*" in permissions or permission in permissions


def audit(
    path: Path,
    *,
    identity: dict[str, Any],
    action: str,
    outcome: str,
    request_id: str,
    resource: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "@timestamp": utc_now(),
        "schema_version": "1.0.0",
        "store_id": "store-001",
        "service": "phase15-unified-api",
        "request_id": request_id,
        "subject": identity.get("subject", "anonymous"),
        "role": identity.get("role", "viewer"),
        "action": action,
        "resource": resource[:200],
        "outcome": outcome,
        "detail": detail or {},
    }
    with _AUDIT_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_audit(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)) :]
    records: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records
