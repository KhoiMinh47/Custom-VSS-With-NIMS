from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
QUERY_SET = ROOT / "docs/evals/search-query-set.jsonl"
RESULT_ROOT = ROOT / "docs/evals/search-results"
SEARCH = "http://127.0.0.1:39310"


def post(path: str, payload: dict[str, Any]) -> Any:
    request = Request(
        f"{SEARCH}{path}",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        return json.load(response)


def main() -> int:
    queries = [
        json.loads(line)
        for line in QUERY_SET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = []
    for query in queries:
        response = post(
            "/api/v1/search",
            {
                "query": query["query"],
                "route": query["route"],
                "top_k": query["top_k"],
                "critic_top_k": 0,
            },
        )
        field = query["relevance_field"]
        result_ids = [str(value.get(field, "")) for value in response["results"]]
        metrics = post(
            "/api/v1/evaluation",
            {
                "query_id": query["query_id"],
                "result_ids": result_ids,
                "relevant_ids": query["relevant_ids"],
                "k": query["top_k"],
            },
        )
        rows.append(
            {
                "query": query,
                "search": response,
                "metrics": metrics,
            }
        )
    precision = sum(row["metrics"]["precision_at_k"] for row in rows) / len(rows)
    ndcg = sum(row["metrics"]["ndcg_at_k"] for row in rows) / len(rows)
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result = {
        "schema_version": "1.0.0",
        "evaluation_run_id": f"phase12-{now}",
        "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "query_count": len(rows),
        "mean_precision_at_k": precision,
        "mean_ndcg_at_k": ndcg,
        "label_limit": (
            "Phase 09 event labels are provisional and the snapshot set is small; "
            "metrics prove the evaluation path, not production search accuracy."
        ),
        "results": rows,
    }
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    output = RESULT_ROOT / f"evaluation-{now}.json"
    latest = RESULT_ROOT / "latest.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    latest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
