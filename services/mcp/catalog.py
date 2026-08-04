from __future__ import annotations

from typing import Any, Callable


TOOL_CATALOG = [
    {
        "name": "dashboard.list",
        "description": "List allowlisted project dashboards and their live health.",
        "permission": "tools:execute",
        "mutating": False,
    },
    {
        "name": "service.health",
        "description": "Read one allowlisted service health record by service_id.",
        "permission": "tools:execute",
        "mutating": False,
    },
    {
        "name": "port.map",
        "description": "Read the canonical project port registry.",
        "permission": "tools:execute",
        "mutating": False,
    },
    {
        "name": "admission.state",
        "description": "Read GPU admission leases without creating or revoking them.",
        "permission": "admission:read",
        "mutating": False,
    },
]


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    snapshot: Callable[[], dict[str, Any]],
    admission: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    allowed = {tool["name"] for tool in TOOL_CATALOG}
    if name not in allowed:
        raise ValueError("tool is not allowlisted")
    current = snapshot()
    if name == "dashboard.list":
        return {
            "services": [
                service
                for service in current["services"]
                if service.get("public_url") and service.get("launchable", False)
            ]
        }
    if name == "service.health":
        service_id = str(arguments.get("service_id", ""))
        service = next(
            (item for item in current["services"] if item["id"] == service_id), None
        )
        if service is None:
            raise ValueError("unknown service_id")
        return {"service": service}
    if name == "port.map":
        return {
            "ports": [
                {
                    "service_id": service["id"],
                    "port": service.get("port"),
                    "exposure": service.get("exposure"),
                    "expected_state": service["expected_state"],
                }
                for service in current["services"]
                if service.get("port") is not None
            ]
        }
    return admission()
