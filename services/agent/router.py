from __future__ import annotations


def route_query(question: str) -> str:
    """Deterministic safe fallback; Phase 15 does not start Nemotron implicitly."""
    text = question.lower()
    if any(term in text for term in ("gpu", "lease", "admission")):
        return "admission.state"
    if any(term in text for term in ("port", "cổng")):
        return "port.map"
    if any(term in text for term in ("service", "health", "status", "trạng thái")):
        return "dashboard.list"
    return "dashboard.list"
