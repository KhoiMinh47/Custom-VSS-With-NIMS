from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from contracts import (
    REFUSAL_TEXT,
    UNOBSERVED_TEXT,
    SCHEMA_VERSION,
    STORE_ID,
    all_events,
    build_job,
    grounded_answer,
    normalize_caption,
    normalize_summary,
    question_scope,
    recover_interrupted_job,
    refusal,
    select_question_evidence,
    selected_clip_path,
    utc_now,
)
from providers import CosmosCaptionClient, NemotronClient, ProviderError
from reporting import build_report, persist_report


REPORT_NAME_PATTERN = re.compile(r"([0-9a-f]{64})\.(json|md)")


def structured_log(event: str, **fields: Any) -> None:
    print(
        json.dumps(
            {"@timestamp": utc_now(), "level": "INFO", "event": event, **fields},
            separators=(",", ":"),
        ),
        flush=True,
    )


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.jobs_dir = root / "jobs"
        self.reports_dir = root / "reports"
        self.dlq_path = root / "dlq.jsonl"
        self.lock = threading.RLock()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.recover()

    def path(self, job_id: str) -> Path:
        if len(job_id) != 64 or any(value not in "0123456789abcdef" for value in job_id):
            raise ValueError("invalid job_id")
        return self.jobs_dir / f"{job_id}.json"

    def save(self, job: dict[str, Any]) -> None:
        job["updated_at"] = utc_now()
        path = self.path(job["job_id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def load(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            path = self.path(job_id)
            if not path.is_file():
                raise FileNotFoundError("summary job does not exist")
            return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            jobs = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(self.jobs_dir.glob("*.json"))
            ]
        return sorted(jobs, key=lambda value: (value["created_at"], value["job_id"]))

    def report_path(self, name: str) -> Path:
        if REPORT_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError("invalid report name")
        path = (self.reports_dir / name).resolve()
        if path.parent != self.reports_dir.resolve():
            raise ValueError("invalid report path")
        return path

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        with self.lock:
            for path in sorted(self.reports_dir.glob("*.json")):
                match = REPORT_NAME_PATTERN.fullmatch(path.name)
                if match is None:
                    continue
                try:
                    safe_path = self.report_path(path.name)
                    value = json.loads(safe_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if (
                    not isinstance(value, dict)
                    or value.get("schema_version") != SCHEMA_VERSION
                    or value.get("store_id") != STORE_ID
                    or value.get("report_id") != match.group(1)
                    or value.get("report_type") not in {"incident", "shift", "daily"}
                    or not isinstance(value.get("created_at"), str)
                ):
                    continue
                report_id = match.group(1)
                try:
                    markdown_available = self.report_path(
                        f"{report_id}.md"
                    ).is_file()
                except ValueError:
                    markdown_available = False
                item = dict(value)
                item["downloads"] = {
                    "json": {
                        "href": f"/api/v1/reports/{report_id}.json",
                        "content_type": "application/json",
                    },
                    "markdown": (
                        {
                            "href": f"/api/v1/reports/{report_id}.md",
                            "content_type": "text/markdown",
                        }
                        if markdown_available
                        else None
                    ),
                }
                reports.append(item)
        return sorted(
            reports,
            key=lambda value: (
                str(value.get("created_at", "")),
                str(value.get("report_id", "")),
            ),
            reverse=True,
        )

    def create(
        self,
        payload: dict[str, Any],
        selected_root: Path,
        uploaded_root: Path | None = None,
    ) -> tuple[dict[str, Any], bool]:
        with self.lock:
            job = build_job(payload, selected_root, uploaded_root)
            path = self.path(job["job_id"])
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8")), False
            self.save(job)
            return job, True

    def recover(self) -> None:
        with self.lock:
            for path in self.jobs_dir.glob("*.json"):
                job = json.loads(path.read_text(encoding="utf-8"))
                before = job.get("status")
                recover_interrupted_job(job)
                if job.get("status") != before:
                    self.save(job)
                    structured_log("job_recovered", job_id=job["job_id"], from_status=before)

    def dlq(self, job: dict[str, Any], chunk: dict[str, Any], error: str) -> None:
        value = {
            "@timestamp": utc_now(),
            "schema_version": SCHEMA_VERSION,
            "store_id": job["store_id"],
            "camera_id": job["camera_id"],
            "job_id": job["job_id"],
            "chunk_id": chunk["chunk_id"],
            "asset_uri": chunk["asset_uri"],
            "error": error,
            "retry_count": chunk["caption_attempts"],
        }
        with self.dlq_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, separators=(",", ":")) + "\n")


class Runtime:
    def __init__(self) -> None:
        self.selected_root = Path(os.environ.get("SELECTED_CLIP_DIR", "/selected-clips"))
        self.uploaded_root = Path(os.environ.get("UPLOADED_MEDIA_DIR", "/uploaded-media"))
        self.runtime_root = Path(os.environ.get("SUMMARY_RUNTIME_DIR", "/runtime/summarization"))
        self.admission_root = Path(os.environ.get("ADMISSION_DIR", "/runtime/admission"))
        self.es_url = os.environ.get("ELASTICSEARCH_URL", "http://elasticsearch:9200").rstrip("/")
        prompt_root = Path(os.environ.get("PROMPT_DIR", "/config/prompts"))
        self.caption_prompt = json.loads(
            (prompt_root / "caption.json").read_text(encoding="utf-8")
        )
        self.summary_prompt = json.loads(
            (prompt_root / "summary.json").read_text(encoding="utf-8")
        )
        self.qa_prompt = json.loads((prompt_root / "qa.json").read_text(encoding="utf-8"))
        self.store = JobStore(self.runtime_root)
        self.cosmos = CosmosCaptionClient(
            os.environ.get("VLM_BASE_URL", "http://poc-cosmos3:8000/v1"),
            os.environ.get("VLM_MODEL", "nvidia/cosmos3-nano-reasoner"),
            float(os.environ.get("VLM_TIMEOUT_SECONDS", "300")),
        )
        self.nemotron = NemotronClient(
            os.environ.get("LLM_BASE_URL", "http://poc-nemotron:8000/v1"),
            os.environ.get("LLM_MODEL", "nvidia/nvidia-nemotron-nano-9b-v2"),
            float(os.environ.get("LLM_TIMEOUT_SECONDS", "180")),
        )
        self.started = time.monotonic()
        self.caption_requests = 0
        self.summary_requests = 0
        self.qa_requests = 0
        self.refusals = 0
        self.report_requests = 0
        self.provider_failures = 0
        self.ready = False
        self.queue_stop = threading.Event()
        self.check_health()

    def process_queued_jobs(self) -> None:
        """Run persisted jobs whenever their explicitly admitted provider is ready.

        The CPU service never starts a model or changes admission. It only
        consumes queued work after the host GPU worker has granted the fixed
        lease, which lets the host worker restore RT-CV when the managed stage
        reaches its checkpoint.
        """
        while not self.queue_stop.wait(2.0):
            try:
                jobs = self.store.list()
                if self.admitted("phase13-vlm.lease", "summarization_vlm") and self.cosmos.ready():
                    queued = next(
                        (job for job in jobs if job.get("status") == "queued_caption"),
                        None,
                    )
                    if queued:
                        self.caption_job(str(queued["job_id"]))
                        continue
                if self.admitted("phase13-llm.lease", "summarization_llm") and self.nemotron.ready():
                    queued = next(
                        (job for job in jobs if job.get("status") == "queued_summary"),
                        None,
                    )
                    if queued:
                        self.summarize_job(str(queued["job_id"]))
            except (FileNotFoundError, ProviderError, ValueError, RuntimeError) as error:
                structured_log("queued_job_waiting", error_type=type(error).__name__)

    def es(self, method: str, path: str, value: dict[str, Any] | None = None) -> Any:
        request = Request(
            f"{self.es_url}{path}",
            data=None if value is None else json.dumps(value, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=15) as response:
                body = response.read()
            return json.loads(body) if body else {}
        except HTTPError as error:
            raise RuntimeError(f"Elasticsearch request failed: HTTP {error.code}") from error

    def check_health(self) -> None:
        value = self.es("GET", "/_cluster/health?wait_for_status=yellow")
        self.ready = value.get("status") in {"yellow", "green"}

    def admitted(self, name: str, profile: str) -> bool:
        path = self.admission_root / name
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return False
        return value.get("status") == "granted" and value.get("profile") == profile

    def state(self) -> dict[str, Any]:
        jobs = self.store.list()
        status_counts: dict[str, int] = {}
        for job in jobs:
            status = str(job.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "ready": self.ready,
            "uptime_seconds": round(time.monotonic() - self.started, 3),
            "jobs": len(jobs),
            "status_counts": status_counts,
            "caption_provider": "available" if self.cosmos.ready() else "unavailable",
            "summary_provider": "available" if self.nemotron.ready() else "unavailable",
            "caption_admission": self.admitted(
                "phase13-vlm.lease", "summarization_vlm"
            ),
            "summary_admission": self.admitted(
                "phase13-llm.lease", "summarization_llm"
            ),
            "reports": len(list(self.store.reports_dir.glob("*.json"))),
            "refusals": self.refusals,
            "evidence_policy": {
                "accepted_uri": "selected-clip://",
                "unobserved_gaps": "not_no_event_claims",
            },
        }

    def index_caption(self, value: dict[str, Any]) -> None:
        self.es("PUT", f"/vss-captions/_doc/{value['chunk_id']}?refresh=true", value)

    def index_summary(self, value: dict[str, Any]) -> None:
        self.es("PUT", f"/vss-summaries/_doc/{value['job_id']}?refresh=true", value)

    def caption_job(self, job_id: str) -> dict[str, Any]:
        if not self.admitted("phase13-vlm.lease", "summarization_vlm"):
            raise ProviderError("Phase 13 caption admission lease is absent")
        if not self.cosmos.ready():
            raise ProviderError("Cosmos3 caption provider is unavailable")
        with self.store.lock:
            job = self.store.load(job_id)
            if job["status"] in {"completed", "queued_summary"}:
                return job
            if job["status"] not in {"queued_caption", "captioning", "failed"}:
                raise ValueError("job is not eligible for captioning")
            job["status"] = "captioning"
            job["last_error"] = ""
            self.store.save(job)
            for chunk in job["chunks"]:
                if chunk.get("caption_status") == "completed":
                    continue
                path = selected_clip_path(
                    self.selected_root,
                    chunk["asset_uri"],
                    self.uploaded_root,
                )
                last_error = ""
                for attempt in range(int(chunk.get("caption_attempts", 0)) + 1, 4):
                    chunk["caption_attempts"] = attempt
                    self.store.save(job)
                    try:
                        raw = self.cosmos.caption(
                            path,
                            system_prompt=self.caption_prompt["system_prompt"],
                            user_prompt=self.caption_prompt["user_prompt"].format(
                                camera_id=job["camera_id"],
                                start_time=chunk["start_time"],
                                end_time=chunk["end_time"],
                                asset_uri=chunk["asset_uri"],
                            ),
                        )
                        caption = normalize_caption(raw, chunk, job["camera_id"])
                        chunk["caption"] = caption
                        chunk["caption_status"] = "completed"
                        chunk["caption_completed_at"] = utc_now()
                        self.index_caption(caption)
                        self.caption_requests += 1
                        self.store.save(job)
                        structured_log(
                            "chunk_captioned",
                            job_id=job_id,
                            chunk_id=chunk["chunk_id"],
                            attempt=attempt,
                        )
                        break
                    except (ProviderError, ValueError) as error:
                        self.provider_failures += 1
                        last_error = type(error).__name__
                        chunk["last_error"] = last_error
                        job["retry_count"] = int(job.get("retry_count", 0)) + 1
                        self.store.save(job)
                if chunk.get("caption_status") != "completed":
                    chunk["caption_status"] = "failed"
                    job["status"] = "failed"
                    job["last_error"] = last_error
                    self.store.dlq(job, chunk, last_error)
                    self.store.save(job)
                    return job
            job["status"] = "queued_summary"
            self.store.save(job)
            return job

    def _summarize_batch(
        self,
        job: dict[str, Any],
        events: list[dict[str, Any]],
        *,
        level: int,
    ) -> dict[str, Any]:
        raw = self.nemotron.generate_json(
            self.summary_prompt["system_prompt"],
            {
                "job": {
                    "store_id": job["store_id"],
                    "camera_id": job["camera_id"],
                    "window_start": job["window_start"],
                    "window_end": job["window_end"],
                },
                "events": events,
                "required_event_ids": [event["event_id"] for event in events],
            },
        )
        return normalize_summary(raw, events, job=job, level=level)

    def summarize_job(self, job_id: str) -> dict[str, Any]:
        if not self.admitted("phase13-llm.lease", "summarization_llm"):
            raise ProviderError("Phase 13 summary admission lease is absent")
        if not self.nemotron.ready():
            raise ProviderError("Nemotron summary provider is unavailable")
        with self.store.lock:
            job = self.store.load(job_id)
            if job["status"] == "completed":
                return job
            if job["status"] not in {"queued_summary", "summarizing"}:
                raise ValueError("all captions must complete before summarization")
            events = all_events(job)
            if not events:
                job["status"] = "failed"
                job["last_error"] = "NoEvidence"
                self.store.save(job)
                return job
            job["status"] = "summarizing"
            self.store.save(job)
            partials = [
                partial
                for partial in job.get("partial_summaries", [])
                if isinstance(partial, dict) and partial.get("hierarchy_level") == 0
            ]
            for offset in range(0, len(events), 2):
                batch_index = offset // 2
                if batch_index < len(partials):
                    continue
                partials.append(
                    self._summarize_batch(job, events[offset : offset + 2], level=0)
                )
                job["partial_summaries"] = partials
                self.store.save(job)
            job["partial_summaries"] = partials
            self.store.save(job)
            raw_final = self.nemotron.generate_json(
                self.summary_prompt["system_prompt"],
                {
                    "job": {
                        "store_id": job["store_id"],
                        "camera_id": job["camera_id"],
                        "window_start": job["window_start"],
                        "window_end": job["window_end"],
                    },
                    "partial_summaries": [
                        {
                            "executive_summary": partial["executive_summary"],
                            "event_ids": partial["event_ids"],
                        }
                        for partial in partials
                    ],
                    "available_event_ids": [event["event_id"] for event in events],
                },
            )
            final = normalize_summary(raw_final, events, job=job, level=1)
            final["partial_summary_count"] = len(partials)
            job["summary"] = final
            job["status"] = "completed"
            job["completed_at"] = utc_now()
            self.index_summary(final)
            self.summary_requests += 1
            self.store.save(job)
            structured_log(
                "job_summarized",
                job_id=job_id,
                events=len(events),
                partials=len(partials),
            )
            return job

    def retry_job(self, job_id: str) -> dict[str, Any]:
        with self.store.lock:
            job = self.store.load(job_id)
            if job.get("status") != "failed":
                raise ValueError("only failed jobs can be retried")
            for chunk in job.get("chunks", []):
                if chunk.get("caption_status") == "failed":
                    chunk["caption_status"] = "pending"
                    chunk["caption_attempts"] = 0
                    chunk.pop("last_error", None)
            job["status"] = (
                "queued_summary"
                if all(
                    chunk.get("caption_status") == "completed"
                    for chunk in job.get("chunks", [])
                )
                else "queued_caption"
            )
            job["last_error"] = ""
            self.store.save(job)
            structured_log("job_retried", job_id=job_id, status=job["status"])
            return job

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValueError("question is required")
        job = self.store.load(str(payload.get("summary_id") or ""))
        if job.get("status") != "completed":
            value = refusal(question, "summary is not completed")
            value["summary_id"] = str(payload.get("summary_id") or "")
            value["answer_source"] = "refusal"
            return value
        scope = question_scope(
            question,
            default_window_start=job["window_start"],
            default_window_end=job["window_end"],
        )
        candidates = select_question_evidence(
            question,
            all_events(job),
            default_window_start=job["window_start"],
            default_window_end=job["window_end"],
        )
        if not candidates:
            self.refusals += 1
            has_explicit_scope = bool(
                scope["camera_ids"]
                or scope.get("window_start")
                or scope.get("window_end")
                or scope.get("camera_ambiguous")
                or scope.get("time_ambiguous")
            )
            value = refusal(
                question,
                (
                    "no selected-media evidence matches the requested camera and UTC time"
                    if has_explicit_scope
                    else "no matching evidence"
                ),
                answer=UNOBSERVED_TEXT if has_explicit_scope else REFUSAL_TEXT,
            )
            value["summary_id"] = job["job_id"]
            value["answer_source"] = "refusal"
            self.qa_requests += 1
            return value
        if not self.admitted("phase13-llm.lease", "summarization_llm"):
            answer = {
                "answer": "; ".join(event["description"] for event in candidates[:3]),
                "event_ids": [event["event_id"] for event in candidates[:3]],
                "insufficient_evidence": False,
            }
            source = "evidence_extract_fallback"
        else:
            raw = self.nemotron.generate_json(
                self.qa_prompt["system_prompt"],
                {"question": question, "events": candidates},
            )
            answer = raw
            source = "nemotron"
        value = grounded_answer(question, answer, candidates)
        value["summary_id"] = job["job_id"]
        value["answer_source"] = source
        self.qa_requests += 1
        if value["answer"] == REFUSAL_TEXT:
            self.refusals += 1
        return value

    def report(self, report_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        summary_ids = payload.get("summary_ids")
        if not isinstance(summary_ids, list) or not summary_ids:
            raise ValueError("summary_ids must be a non-empty list")
        summaries = []
        for summary_id in summary_ids:
            job = self.store.load(str(summary_id))
            if job.get("status") != "completed" or not isinstance(job.get("summary"), dict):
                raise ValueError("reports require completed summaries")
            summaries.append(job["summary"])
        value = build_report(
            report_type,
            summaries,
            incident_id=str(payload.get("incident_id") or ""),
        )
        json_path, markdown_path = persist_report(self.store.reports_dir, value)
        value["json_path"] = json_path.name
        value["markdown_path"] = markdown_path.name
        self.report_requests += 1
        structured_log("report_created", report_id=value["report_id"], report_type=report_type)
        return value

    def metrics(self) -> str:
        jobs = self.store.list()
        completed = sum(job.get("status") == "completed" for job in jobs)
        failed = sum(job.get("status") == "failed" for job in jobs)
        queue = sum(str(job.get("status", "")).startswith("queued") for job in jobs)
        oldest_age = 0.0
        queued = [job for job in jobs if str(job.get("status", "")).startswith("queued")]
        if queued:
            from datetime import datetime

            created = min(
                datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))
                for job in queued
            )
            oldest_age = max(0.0, time.time() - created.timestamp())
        return "\n".join(
            [
                "# HELP phase13_summarization_ready Phase 13 service readiness.",
                "# TYPE phase13_summarization_ready gauge",
                f"phase13_summarization_ready {1 if self.ready else 0}",
                f"phase13_summary_jobs_total {len(jobs)}",
                f"phase13_summary_jobs_completed {completed}",
                f"phase13_summary_jobs_failed {failed}",
                f"phase13_summary_queue_depth {queue}",
                f"phase13_summary_oldest_queue_age_seconds {oldest_age:.3f}",
                f"phase13_caption_requests_total {self.caption_requests}",
                f"phase13_summary_requests_total {self.summary_requests}",
                f"phase13_qa_requests_total {self.qa_requests}",
                f"phase13_qa_refusals_total {self.refusals}",
                f"phase13_reports_total {self.report_requests}",
                f"phase13_provider_failures_total {self.provider_failures}",
                "",
            ]
        )


DASHBOARD = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 13 · Summary & Q&A</title><style>
:root{font-family:system-ui;color:#edf6ff;background:#071018}*{box-sizing:border-box}
body{margin:0}main{max-width:1180px;margin:auto;padding:24px}.muted{color:#9db0bf}
.status{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.chip{padding:7px 10px;border:1px solid #294052;
border-radius:999px;background:#111d28}.ready{color:#73efb2}.standby{color:#ffd27d}
.layout{display:grid;grid-template-columns:360px 1fr;gap:12px}.panel{background:#111d28;
border:1px solid #294052;border-radius:12px;padding:14px}.jobs{display:grid;gap:8px}
.job{width:100%;padding:12px;border:1px solid #294052;border-radius:9px;background:#0b151e;
color:#edf6ff;text-align:left;cursor:pointer}.job:hover,.job.active{border-color:#73efb2}
.job strong,.job small{display:block}.job small{margin-top:6px;color:#9db0bf}.summary{line-height:1.6}
form{display:grid;gap:9px;margin-top:14px}textarea{min-height:88px;resize:vertical;padding:10px;
border:1px solid #294052;border-radius:8px;background:#071018;color:#edf6ff}button.action{
padding:9px 12px;border:0;border-radius:8px;background:#1c9168;color:white;font-weight:700;cursor:pointer}
.answer{min-height:48px;margin-top:12px;padding:12px;border-left:3px solid #73efb2;background:#0b151e;
white-space:pre-wrap}.evidence{margin-top:10px;color:#9db0bf;font-size:.88rem}
@media(max-width:760px){.layout{grid-template-columns:1fr}}</style></head><body><main>
<h1>Phase 13 · Tóm tắt và hỏi đáp video</h1>
<p class="muted">Chỉ sử dụng clip đã được chọn. Khoảng thời gian không có clip được ghi nhận là chưa quan sát.</p>
<div class="status"><span id="captionStatus" class="chip">Cosmos3 —</span>
<span id="summaryStatus" class="chip">Nemotron 9B —</span><span id="jobCount" class="chip">0 bản tóm tắt</span></div>
<div class="layout"><section class="panel"><h2>Bản tóm tắt</h2><div id="jobs" class="jobs">Đang tải…</div></section>
<section class="panel"><h2 id="summaryTitle">Chọn một bản tóm tắt</h2>
<p id="summaryWindow" class="muted">—</p><div id="summaryText" class="summary">Chưa chọn dữ liệu.</div>
<form id="qaForm"><label for="question"><strong>Hỏi về khoảng thời gian đã chọn</strong></label>
<textarea id="question" placeholder="Ví dụ: Trong khoảng thời gian này có sự kiện gì xảy ra?" required></textarea>
<button class="action" type="submit">Hỏi hệ thống</button></form>
<div id="answer" class="answer">Câu trả lời sẽ xuất hiện tại đây.</div>
<div id="evidence" class="evidence"></div></section></div>
<script>
const state={jobs:[],selected:null};const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
function localTime(value){return new Intl.DateTimeFormat("vi-VN",{timeZone:"Asia/Ho_Chi_Minh",
dateStyle:"medium",timeStyle:"medium"}).format(new Date(value))}
function renderJobs(){jobs.innerHTML=state.jobs.map(job=>`<button class="job ${job.job_id===state.selected?"active":""}"
data-id="${esc(job.job_id)}"><strong>${esc(job.title)}</strong><small>${esc(job.camera_id)} · ${esc(localTime(job.window_start))}
 → ${esc(localTime(job.window_end))}</small><small>${esc(job.status)}</small></button>`).join("")||"Chưa có bản tóm tắt."}
function selectJob(id){const job=state.jobs.find(item=>item.job_id===id);if(!job)return;state.selected=id;renderJobs();
summaryTitle.textContent=job.title;summaryWindow.textContent=`${job.camera_id} · ${localTime(job.window_start)} → ${localTime(job.window_end)}`;
summaryText.textContent=job.summary?.executive_summary||"Bản tóm tắt chưa hoàn thành.";answer.textContent="Câu trả lời sẽ xuất hiện tại đây.";evidence.textContent=""}
async function load(){const [s,j]=await Promise.all([fetch("/api/v1/state"),fetch("/api/v1/jobs")]);
const status=await s.json();state.jobs=(await j.json()).jobs;captionStatus.textContent=`Cosmos3 ${status.caption_provider}`;
summaryStatus.textContent=`Nemotron 9B ${status.summary_provider}`;captionStatus.className=`chip ${status.caption_provider==="available"?"ready":"standby"}`;
summaryStatus.className=`chip ${status.summary_provider==="available"?"ready":"standby"}`;jobCount.textContent=`${state.jobs.length} bản tóm tắt`;
renderJobs();if(!state.selected&&state.jobs.length)selectJob(state.jobs[0].job_id)}
jobs.addEventListener("click",event=>{const button=event.target.closest("[data-id]");if(button)selectJob(button.dataset.id)});
qaForm.addEventListener("submit",async event=>{event.preventDefault();if(!state.selected)return;
answer.textContent="Đang tìm bằng chứng…";evidence.textContent="";const response=await fetch("/api/v1/qa",{method:"POST",
headers:{"Content-Type":"application/json"},body:JSON.stringify({summary_id:state.selected,question:question.value})});
const value=await response.json();answer.textContent=value.answer||value.error||"Không có câu trả lời.";
evidence.textContent=(value.evidence||[]).map(item=>`${item.camera_id} · ${localTime(item.start_time)} · ${item.description}`).join("\\n")})
load().catch(()=>{jobs.textContent="Không tải được dữ liệu.";answer.textContent="Summary API không khả dụng."});
</script></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    runtime: Runtime

    def send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            if path == "/health/live":
                self.send_json(200, {"status": "live", "schema_version": SCHEMA_VERSION})
            elif path == "/health/ready":
                self.runtime.check_health()
                self.send_json(
                    200 if self.runtime.ready else 503,
                    {"status": "ready" if self.runtime.ready else "not_ready"},
                )
            elif path == "/api/v1/state":
                self.send_json(200, self.runtime.state())
            elif path == "/api/v1/jobs":
                self.send_json(200, {"jobs": self.runtime.store.list()})
            elif path.startswith("/api/v1/jobs/"):
                self.send_json(200, self.runtime.store.load(path.rsplit("/", 1)[1]))
            elif path == "/api/v1/reports":
                self.send_json(
                    200,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "store_id": STORE_ID,
                        "reports": self.runtime.store.list_reports(),
                    },
                )
            elif path.startswith("/api/v1/reports/"):
                name = path.rsplit("/", 1)[1]
                report_path = self.runtime.store.report_path(name)
                if not report_path.is_file():
                    raise FileNotFoundError("report does not exist")
                body = report_path.read_bytes()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/markdown; charset=utf-8"
                    if name.endswith(".md")
                    else "application/json",
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{name}"'
                )
                self.end_headers()
                self.wfile.write(body)
            elif path == "/metrics":
                body = self.runtime.metrics().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path in {"/", "/dashboard"}:
                body = DASHBOARD.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)
        except FileNotFoundError as error:
            self.send_json(404, {"status": "not_found", "error": str(error)})
        except (ValueError, RuntimeError) as error:
            self.send_json(400, {"status": "rejected", "error": str(error)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/v1/summaries":
                value, created = self.runtime.store.create(
                    payload,
                    self.runtime.selected_root,
                    self.runtime.uploaded_root,
                )
                structured_log("job_created" if created else "job_reused", job_id=value["job_id"])
                self.send_json(201 if created else 200, value)
            elif path.startswith("/api/v1/jobs/") and path.endswith("/caption"):
                job_id = path.split("/")[-2]
                self.send_json(200, self.runtime.caption_job(job_id))
            elif path.startswith("/api/v1/jobs/") and path.endswith("/summarize"):
                job_id = path.split("/")[-2]
                self.send_json(200, self.runtime.summarize_job(job_id))
            elif path.startswith("/api/v1/jobs/") and path.endswith("/retry"):
                job_id = path.split("/")[-2]
                self.send_json(200, self.runtime.retry_job(job_id))
            elif path == "/api/v1/qa":
                self.send_json(200, self.runtime.answer(payload))
            elif path.startswith("/api/v1/reports/"):
                report_type = path.rsplit("/", 1)[1]
                self.send_json(201, self.runtime.report(report_type, payload))
            else:
                self.send_error(404)
        except FileNotFoundError as error:
            self.send_json(404, {"status": "not_found", "error": str(error)})
        except ProviderError as error:
            self.send_json(503, {"status": "waiting_for_gpu", "error": str(error)})
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self.send_json(400, {"status": "rejected", "error": str(error)})
        except Exception as error:
            structured_log("request_failed", error_type=type(error).__name__)
            self.send_json(500, {"status": "failed", "error_type": type(error).__name__})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    runtime = Runtime()
    Handler.runtime = runtime
    port = int(os.environ.get("HTTP_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    queue_thread = threading.Thread(
        target=runtime.process_queued_jobs,
        name="phase13-queue-worker",
        daemon=True,
    )
    queue_thread.start()
    structured_log("service_started", port=port)
    try:
        server.serve_forever()
    finally:
        runtime.queue_stop.set()
        queue_thread.join(timeout=5)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
