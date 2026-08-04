from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:39410"
ES = "http://127.0.0.1:9200"
REGISTRY = ROOT / "runtime/summarization/evaluation-jobs.json"
EVAL_DIR = ROOT / "docs/evals/summarization"
BENCHMARK_DIR = ROOT / "artifacts/benchmarks/phase13-summarization"


def request(
    base: str, path: str, value: dict[str, Any] | None = None, method: str | None = None
) -> Any:
    request = Request(
        f"{base}{path}",
        data=None if value is None else json.dumps(value, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method=method or ("GET" if value is None else "POST"),
    )
    with urlopen(request, timeout=900) as response:
        body = response.read()
    return json.loads(body) if body else {}


def selected_assets() -> list[dict[str, Any]]:
    value = request(
        ES,
        "/vss-video-embeddings/_search",
        {
            "size": 20,
            "_source": ["asset_uri", "camera_id", "start_time", "end_time"],
            "sort": [{"start_time": "asc"}],
        },
    )
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in value["hits"]["hits"]:
        source = hit["_source"]
        uri = source["asset_uri"]
        if uri in seen:
            continue
        seen.add(uri)
        assets.append(
            {
                "asset_uri": uri,
                "start_time": source["start_time"].replace("000Z", "Z"),
                "end_time": source["end_time"].replace("000Z", "Z"),
            }
        )
    if len(assets) < 3:
        raise RuntimeError("Phase 13 evaluation requires three Phase 12 selected clips")
    return assets[:3]


def create_jobs() -> dict[str, str]:
    assets = selected_assets()
    short = request(
        API,
        "/api/v1/summaries",
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "camera_id": "cam-01",
            "source_type": "selected_video",
            "window_start": assets[0]["start_time"],
            "window_end": assets[0]["end_time"],
            "assets": [assets[0]],
            "title": "Phase 13 short selected-video evaluation",
            "idempotency_key": "phase13-short-v1",
        },
    )
    long = request(
        API,
        "/api/v1/summaries",
        {
            "schema_version": "1.0.0",
            "store_id": "store-001",
            "camera_id": "cam-01",
            "source_type": "time_window",
            "window_start": min(asset["start_time"] for asset in assets),
            "window_end": max(asset["end_time"] for asset in assets),
            "assets": assets,
            "title": "Phase 13 selected-event time-window evaluation",
            "idempotency_key": "phase13-time-window-v1",
        },
    )
    registry = {"short": short["job_id"], "long": long["job_id"]}
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return registry


def caption() -> None:
    registry = create_jobs()
    results = {}
    for label, job_id in registry.items():
        results[label] = request(API, f"/api/v1/jobs/{job_id}/caption", {})
        if results[label]["status"] not in {"queued_summary", "completed"}:
            raise RuntimeError(
                f"{label} caption job did not reach a resumable/completed state"
            )
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    (BENCHMARK_DIR / "caption-results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )


def _timestamp_ok(summary: dict[str, Any]) -> bool:
    start = datetime.fromisoformat(summary["window_start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(summary["window_end"].replace("Z", "+00:00"))
    return all(
        start
        <= datetime.fromisoformat(item["start_time"].replace("Z", "+00:00"))
        <= datetime.fromisoformat(item["end_time"].replace("Z", "+00:00"))
        <= end
        for item in summary["evidence"]
    )


def summarize() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    jobs = {
        label: request(API, f"/api/v1/jobs/{job_id}/summarize", {})
        for label, job_id in registry.items()
    }
    if any(job["status"] != "completed" for job in jobs.values()):
        raise RuntimeError("a Phase 13 summary job did not complete")
    supported = request(
        API,
        "/api/v1/qa",
        {
            "summary_id": registry["long"],
            "question": "What visible activity appears in the selected video events?",
        },
    )
    unsupported = request(
        API,
        "/api/v1/qa",
        {
            "summary_id": registry["long"],
            "question": "What color was the delivery truck?",
        },
    )
    reports = {
        "incident": request(
            API,
            "/api/v1/reports/incident",
            {
                "summary_ids": [registry["short"]],
                "incident_id": "phase13-evaluation-incident",
            },
        ),
        "shift": request(
            API, "/api/v1/reports/shift", {"summary_ids": [registry["long"]]}
        ),
        "daily": request(
            API, "/api/v1/reports/daily", {"summary_ids": [registry["long"]]}
        ),
    }
    summaries = {label: job["summary"] for label, job in jobs.items()}
    caption_event_count = sum(
        len(chunk["caption"]["events"]) for chunk in jobs["long"]["chunks"]
    )
    cited_event_count = len(summaries["long"]["evidence"])
    checks = {
        "short_completed": jobs["short"]["status"] == "completed",
        "time_window_completed": jobs["long"]["status"] == "completed",
        "hierarchical_partial_summaries": len(jobs["long"]["partial_summaries"]) >= 2,
        "timestamp_bounds": all(_timestamp_ok(value) for value in summaries.values()),
        "all_claims_have_evidence": all(
            value["evidence"] and value["event_ids"] for value in summaries.values()
        ),
        "supported_qa_has_evidence": supported["status"] == "answered"
        and bool(supported["evidence"]),
        "unsupported_qa_refuses": unsupported["status"] == "insufficient_evidence"
        and unsupported["answer"] == "không đủ dữ liệu"
        and unsupported["evidence"] == [],
        "all_reports_have_evidence": all(report["evidence"] for report in reports.values()),
        "unobserved_gap_policy": all(
            gap["status"] == "unobserved"
            for gap in summaries["long"]["coverage_gaps"]
        ),
    }
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evaluation = {
        "schema_version": "1.0.0",
        "evaluation_id": f"phase13-{now}",
        "result": "PARTIAL",
        "reason": (
            "Technical evidence-grounding gates passed on three selected clips from one "
            "physical camera; sample size and human ratings are insufficient for an "
            "accuracy or hallucination-rate claim."
        ),
        "jobs": registry,
        "checks": checks,
        "metrics": {
            "selected_clips": len(jobs["long"]["chunks"]),
            "caption_events_total": caption_event_count,
            "summary_events_cited": cited_event_count,
            "event_coverage": (
                cited_event_count / caption_event_count if caption_event_count else 0.0
            ),
            "partial_summaries": len(jobs["long"]["partial_summaries"]),
            "coverage_gaps": len(summaries["long"]["coverage_gaps"]),
            "unsupported_question_refusals": 1 if checks["unsupported_qa_refuses"] else 0,
            "human_ratings": 0,
        },
        "supported_qa": supported,
        "unsupported_qa": unsupported,
        "reports": reports,
    }
    if not all(checks.values()):
        evaluation["result"] = "FAIL"
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    output = EVAL_DIR / f"evaluation-{now}.json"
    output.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    (EVAL_DIR / "latest.json").write_text(
        json.dumps(evaluation, indent=2) + "\n", encoding="utf-8"
    )
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    (BENCHMARK_DIR / "summary-results.json").write_text(
        json.dumps(jobs, indent=2) + "\n", encoding="utf-8"
    )
    (BENCHMARK_DIR / "qa-results.json").write_text(
        json.dumps(
            {"supported": supported, "unsupported": unsupported}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    (BENCHMARK_DIR / "report-results.json").write_text(
        json.dumps(reports, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evaluation, separators=(",", ":")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("caption", "summarize"))
    args = parser.parse_args()
    if args.stage == "caption":
        caption()
    else:
        summarize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
