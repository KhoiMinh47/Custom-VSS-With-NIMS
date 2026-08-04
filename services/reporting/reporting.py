from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0.0"
REPORT_MODEL_ID = "ntc-phase13-evidence-report-renderer"
REPORT_MODEL_VERSION = "1.0.0"
REPORT_TYPES = {"incident", "shift", "daily"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_report(
    report_type: str,
    summaries: list[dict[str, Any]],
    *,
    incident_id: str = "",
) -> dict[str, Any]:
    if report_type not in REPORT_TYPES:
        raise ValueError("report_type must be incident, shift or daily")
    if not summaries:
        raise ValueError("at least one completed summary is required")
    store_ids = {summary.get("store_id") for summary in summaries}
    if len(store_ids) != 1:
        raise ValueError("report summaries must belong to one store")
    ordered = sorted(summaries, key=lambda value: value["window_start"])
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for summary in ordered:
        for item in summary.get("evidence", []):
            event_id = str(item.get("event_id", ""))
            if event_id and event_id not in seen:
                evidence.append(item)
                seen.add(event_id)
    if not evidence:
        raise ValueError("reports require timestamped evidence")
    material = "\n".join(
        [report_type, incident_id, *(str(summary["job_id"]) for summary in ordered)]
    )
    report_id = hashlib.sha256(material.encode()).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "report_type": report_type,
        "incident_id": incident_id if report_type == "incident" else "",
        "store_id": ordered[0]["store_id"],
        "camera_ids": sorted({summary["camera_id"] for summary in ordered}),
        "window_start": min(summary["window_start"] for summary in ordered),
        "window_end": max(summary["window_end"] for summary in ordered),
        "executive_summary": " ".join(
            str(summary["executive_summary"]) for summary in ordered
        )[:12000],
        "summary_ids": [summary["job_id"] for summary in ordered],
        "important_incidents": [
            item
            for summary in ordered
            for item in summary.get("evidence", [])
            if item.get("event_id") in set(summary.get("incident_event_ids", []))
        ],
        "evidence": evidence,
        "coverage_gaps": [
            gap for summary in ordered for gap in summary.get("coverage_gaps", [])
        ],
        "model_id": REPORT_MODEL_ID,
        "model_version": REPORT_MODEL_VERSION,
        "source_summary_model_id": ordered[0].get("model_id", ""),
        "source_summary_model_version": ordered[0].get("model_version", ""),
        "created_at": utc_now(),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['report_type'].title()} report",
        "",
        f"- Store: `{report['store_id']}`",
        f"- Cameras: {', '.join(report['camera_ids'])}",
        f"- Window: {report['window_start']} — {report['window_end']}",
        f"- Report ID: `{report['report_id']}`",
        "",
        "## Executive summary",
        "",
        report["executive_summary"],
        "",
        "## Evidence timeline",
        "",
    ]
    for item in report["evidence"]:
        lines.append(
            f"- {item['start_time']} — {item['end_time']} · "
            f"`{item['camera_id']}` · {item.get('description', '')} · "
            f"`{item['asset_uri']}`"
        )
    lines.extend(["", "## Coverage gaps", ""])
    if report["coverage_gaps"]:
        for gap in report["coverage_gaps"]:
            lines.append(
                f"- {gap['start_time']} — {gap['end_time']}: "
                "unobserved (not a no-event assertion)"
            )
    else:
        lines.append("- None within the selected-media window.")
    return "\n".join(lines) + "\n"


def persist_report(root: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"{report['report_id']}.json"
    markdown_path = root / f"{report['report_id']}.md"
    temporary_json = json_path.with_suffix(".json.tmp")
    temporary_markdown = markdown_path.with_suffix(".md.tmp")
    temporary_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary_markdown.write_text(render_markdown(report), encoding="utf-8")
    temporary_json.replace(json_path)
    temporary_markdown.replace(markdown_path)
    return json_path, markdown_path
