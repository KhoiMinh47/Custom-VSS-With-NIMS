from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.append(os.environ.get("RT_EMBEDDING_MODULE_DIR", "/opt/ntc/rt-embedding"))
from client import RTEmbeddingClient, RTEmbeddingError  # noqa: E402
from clients import CriticClient, LLMClient, ProviderError, SigLIPClient  # noqa: E402
from contracts import (  # noqa: E402
    OBJECT_DIMENSION,
    OBJECT_MODEL_ID,
    OBJECT_MODEL_VERSION,
    SCHEMA_VERSION,
    STORE_ID,
    build_object_document,
    fallback_decomposition,
    generation_id,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank_fusion,
    validate_vector,
)


VIDEO_DIMENSION = 768
VIDEO_MODEL_ID = "cosmos-embed1-448p-anomaly-detection"
VIDEO_MODEL_VERSION = "1.0"
VIDEO_GENERATION = generation_id(VIDEO_MODEL_ID, VIDEO_MODEL_VERSION, VIDEO_DIMENSION)
OBJECT_GENERATION = generation_id(
    OBJECT_MODEL_ID, OBJECT_MODEL_VERSION, OBJECT_DIMENSION
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def log(level: str, event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": utc_now(),
                "level": level,
                "service": "phase12-search",
                "event": event,
                **fields,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def json_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 30,
) -> Any:
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=None if payload is None else json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else {}


def add_seconds(timestamp: str, seconds: float) -> str:
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return datetime.fromtimestamp(
        value.timestamp() + seconds, UTC
    ).isoformat().replace("+00:00", "Z")


def chunk_time(creation_time: str, value: Any) -> str:
    try:
        return add_seconds(creation_time, float(value))
    except (TypeError, ValueError):
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("embedding chunk timestamp must include a timezone")
        return timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clip_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def video_embedding_id(asset_id: str, chunk_index: int) -> str:
    return hashlib.sha256(
        f"{asset_id}\n{chunk_index}\n{VIDEO_GENERATION}".encode()
    ).hexdigest()


def selected_path(root: Path, uri: str, scheme: str, suffix: str) -> Path:
    prefix = f"{scheme}://"
    if not uri.startswith(prefix):
        raise ValueError(f"only {prefix} assets are accepted")
    name = uri.removeprefix(prefix)
    if name != Path(name).name or not name.lower().endswith(suffix):
        raise ValueError(f"invalid {scheme} URI")
    candidate = (root / name).resolve()
    if candidate.parent != root.resolve() or not candidate.is_file():
        raise ValueError(f"selected {scheme} asset is missing")
    return candidate


class ReindexRequired(RuntimeError):
    pass


class Runtime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.ready = False
        self.video_indexed = 0
        self.objects_indexed = 0
        self.searches = 0
        self.provider_failures = 0
        self.last_search: dict[str, Any] | None = None
        self.es_url = os.environ.get("ELASTICSEARCH_URL", "http://elasticsearch:9200")
        self.rt_embed = RTEmbeddingClient(
            os.environ.get("RT_EMBEDDING_URL", "http://rt-embedding:8000"),
            float(os.environ.get("RT_EMBEDDING_TIMEOUT_SECONDS", "300")),
        )
        self.siglip = SigLIPClient(
            os.environ.get("SIGLIP_URL", "http://siglip-object-embedding:9000"),
            float(os.environ.get("SIGLIP_TIMEOUT_SECONDS", "180")),
        )
        self.llm = LLMClient(
            os.environ.get("LLM_BASE_URL", "http://host.docker.internal:30081/v1"),
            os.environ.get("LLM_MODEL", "nvidia/nvidia-nemotron-nano-9b-v2"),
        )
        self.critic = CriticClient(
            os.environ.get("VLM_BASE_URL", "http://host.docker.internal:30082/v1"),
            os.environ.get("VLM_MODEL", "nvidia/cosmos3-nano-reasoner"),
        )
        self.clip_root = Path(os.environ.get("SELECTED_CLIP_DIR", "/selected-clips"))
        self.snapshot_root = Path(
            os.environ.get("SELECTED_SNAPSHOT_DIR", "/selected-snapshots")
        )
        self.runtime_root = Path(os.environ.get("SEARCH_RUNTIME_DIR", "/runtime/search"))
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.generation_path = self.runtime_root / "index-generations.json"
        self.cache_path = self.runtime_root / "query-cache.json"
        self.admission_root = Path(
            os.environ.get("ADMISSION_DIR", "/runtime/admission")
        )

    def es(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        return json_request(self.es_url, method, path, payload)

    def check_health(self) -> None:
        health = self.es("GET", "/_cluster/health?wait_for_status=yellow")
        self.ready = health.get("status") in {"yellow", "green"}

    def provider_ready(self, url: str) -> bool:
        try:
            with urlopen(url, timeout=3) as response:
                return response.status == 200
        except Exception:
            return False

    def lease(self, name: str, profile: str) -> bool:
        try:
            value = json.loads(
                (self.admission_root / f"{name}.lease").read_text(encoding="utf-8")
            )
            return value.get("status") == "granted" and value.get("profile") == profile
        except (OSError, json.JSONDecodeError):
            return False

    def state(self) -> dict[str, Any]:
        video_count = 0
        object_count = 0
        try:
            video_count = int(
                self.es("GET", "/vss-video-embeddings/_count").get("count", 0)
            )
            object_count = int(
                self.es("GET", "/vss-object-embeddings/_count").get("count", 0)
            )
        except Exception:
            pass
        rt_embedding_ready = self.provider_ready(
            os.environ.get(
                "RT_EMBEDDING_READY_URL",
                "http://rt-embedding:8000/v1/ready",
            )
        )
        siglip_ready = self.provider_ready(
            os.environ.get(
                "SIGLIP_READY_URL",
                "http://siglip-object-embedding:9000/api/v1/ready",
            )
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "ready": self.ready,
            "uptime_seconds": round(time.monotonic() - self.started, 3),
            "video_model": {
                "id": VIDEO_MODEL_ID,
                "version": VIDEO_MODEL_VERSION,
                "dimension": VIDEO_DIMENSION,
                "generation": VIDEO_GENERATION,
            },
            "object_model": {
                "id": OBJECT_MODEL_ID,
                "version": OBJECT_MODEL_VERSION,
                "dimension": OBJECT_DIMENSION,
                "generation": OBJECT_GENERATION,
            },
            "providers": {
                "rt_embedding": (
                    "admitted"
                    if rt_embedding_ready
                    and self.lease("phase12-rt-embedding", "rt_embedding")
                    else "running_unadmitted"
                    if rt_embedding_ready
                    else "offline"
                ),
                "siglip2": (
                    "admitted"
                    if siglip_ready
                    and self.lease("phase12-siglip", "siglip_object")
                    else "running_unadmitted"
                    if siglip_ready
                    else "offline"
                ),
                "query_llm": "admitted"
                if self.lease("phase12-llm", "search_llm")
                else "fallback",
                "critic_vlm": "admitted"
                if self.lease("phase12-critic", "search_critic")
                else "unavailable",
            },
            "video_documents": video_count,
            "object_documents": object_count,
            "searches": self.searches,
            "provider_failures": self.provider_failures,
            "last_search": self.last_search,
        }

    def cache(self) -> dict[str, Any]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": SCHEMA_VERSION, "vectors": {}}

    def cache_vector(self, channel: str, key: str, vector: list[float]) -> None:
        with self.lock:
            value = self.cache()
            value.setdefault("vectors", {})[f"{channel}:{key.lower().strip()}"] = vector
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, self.cache_path)

    def cached_vector(self, channel: str, key: str, dimension: int) -> list[float]:
        vector = self.cache().get("vectors", {}).get(
            f"{channel}:{key.lower().strip()}"
        )
        if vector is None:
            raise ProviderError(f"{channel} provider unavailable and query is not cached")
        return validate_vector(vector, dimension)

    def generation_guard(self, channel: str, generation: str) -> None:
        with self.lock:
            try:
                current = json.loads(
                    self.generation_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                current = {"schema_version": SCHEMA_VERSION}
            previous = current.get(channel)
            if previous is not None and previous != generation:
                alias = (
                    "vss-video-embeddings"
                    if channel == "video"
                    else "vss-object-embeddings"
                )
                document_count = int(
                    self.es("GET", f"/{alias}/_count").get("count", 0)
                )
                if document_count:
                    raise ReindexRequired(
                        f"{channel} model generation changed; create a new index and reindex"
                    )
                current[channel] = generation
            if previous is None:
                current[channel] = generation
            temporary = self.generation_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(current, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temporary, self.generation_path)

    def index_document(self, alias: str, document_id: str, document: dict[str, Any]) -> None:
        self.es("PUT", f"/{alias}/_doc/{document_id}?refresh=wait_for", document)

    def index_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = {"asset_id", "asset_uri", "camera_id", "creation_time"}
        if not required.issubset(payload):
            raise ValueError(f"missing fields: {sorted(required.difference(payload))}")
        path = selected_path(
            self.clip_root, str(payload["asset_uri"]), "selected-clip", ".mp4"
        )
        self.generation_guard("video", VIDEO_GENERATION)
        chunks = self.rt_embed.video(path, str(payload["creation_time"]))
        digest = clip_sha256(path)
        indexed = []
        for index, chunk in enumerate(chunks):
            vector = validate_vector(
                chunk.get("embeddings", chunk.get("embedding")), VIDEO_DIMENSION
            )
            start_value = chunk.get("start_time", chunk.get("start_offset", index * 10))
            end_value = chunk.get("end_time", chunk.get("end_offset", (index + 1) * 10))
            start_time = chunk_time(str(payload["creation_time"]), start_value)
            end_time = chunk_time(str(payload["creation_time"]), end_value)
            document_id = video_embedding_id(str(payload["asset_id"]), index)
            document = {
                "@timestamp": start_time,
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "camera_id": str(payload["camera_id"]),
                "event_type": str(payload.get("event_type", "search.selected_clip")),
                "model_id": VIDEO_MODEL_ID,
                "model_version": VIDEO_MODEL_VERSION,
                "embedding_generation": VIDEO_GENERATION,
                "embedding_id": document_id,
                "asset_id": str(payload["asset_id"]),
                "asset_uri": str(payload["asset_uri"]),
                "source_type": "selected_clip",
                "chunk_index": index,
                "chunk_seconds": 10,
                "start_time": start_time,
                "end_time": end_time,
                "frame_count": int(chunk.get("frame_count", 8)),
                "clip_sha256": digest,
                "model_dimension": VIDEO_DIMENSION,
                "latency_ms": round(float(chunk.get("chunk_latency_ms", 0))),
                "embedding": vector,
                "evidence": {
                    "media_plane": "selected_prepared_clip",
                    "raw_storage_consumed": False,
                },
            }
            self.index_document("vss-video-embeddings", document_id, document)
            indexed.append(document_id)
        with self.lock:
            self.video_indexed += len(indexed)
        return {
            "schema_version": SCHEMA_VERSION,
            "asset_id": payload["asset_id"],
            "chunks_indexed": len(indexed),
            "embedding_ids": indexed,
            "generation": VIDEO_GENERATION,
        }

    def image_payload(self, payload: dict[str, Any]) -> tuple[Path, dict[str, int] | None]:
        path = selected_path(
            self.snapshot_root,
            str(payload["asset_uri"]),
            "selected-snapshot",
            (".jpg", ".jpeg", ".png"),
        )
        bbox = payload.get("bbox")
        if bbox is None:
            return path, None
        checked = [float(value) for value in bbox]
        if len(checked) != 4 or min(checked) < 0:
            raise ValueError("bbox must contain four normalized coordinates")
        width = int(payload["image_width"])
        height = int(payload["image_height"])
        return path, {
            "left": round(checked[0] * width),
            "top": round(checked[1] * height),
            "width": round(checked[2] * width),
            "height": round(checked[3] * height),
        }

    def index_object(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = {
            "asset_id",
            "asset_uri",
            "camera_id",
            "frame_time",
            "object_id",
            "track_id",
            "object_class",
            "bbox",
            "image_width",
            "image_height",
        }
        if not required.issubset(payload):
            raise ValueError(f"missing fields: {sorted(required.difference(payload))}")
        path, bbox_pixels = self.image_payload(payload)
        self.generation_guard("object", OBJECT_GENERATION)
        vector = validate_vector(
            self.siglip.image(f"/selected-snapshots/{path.name}", bbox_pixels),
            OBJECT_DIMENSION,
        )
        document = build_object_document(
            asset_id=str(payload["asset_id"]),
            asset_uri=str(payload["asset_uri"]),
            camera_id=str(payload["camera_id"]),
            frame_time=str(payload["frame_time"]),
            object_id=str(payload["object_id"]),
            track_id=str(payload["track_id"]),
            object_class=str(payload["object_class"]),
            bbox=list(payload["bbox"]),
            vector=vector,
        )
        document_id = str(document["object_embedding_id"])
        self.index_document("vss-object-embeddings", document_id, document)
        with self.lock:
            self.objects_indexed += 1
        return {
            "schema_version": SCHEMA_VERSION,
            "object_embedding_id": document_id,
            "generation": OBJECT_GENERATION,
        }

    def action_vector(self, query: str) -> tuple[list[float], str]:
        if not self.lease("phase12-rt-embedding", "rt_embedding"):
            return self.cached_vector("action", query, VIDEO_DIMENSION), "cache"
        try:
            vector = validate_vector(self.rt_embed.text(query), VIDEO_DIMENSION)
            self.cache_vector("action", query, vector)
            return vector, "live"
        except (RTEmbeddingError, ValueError):
            with self.lock:
                self.provider_failures += 1
            return self.cached_vector("action", query, VIDEO_DIMENSION), "cache"

    def attribute_vector(self, query: str) -> tuple[list[float], str]:
        if not self.lease("phase12-siglip", "siglip_object"):
            return self.cached_vector("attribute", query, OBJECT_DIMENSION), "cache"
        try:
            vector = validate_vector(self.siglip.text(query), OBJECT_DIMENSION)
            self.cache_vector("attribute", query, vector)
            return vector, "live"
        except (ProviderError, ValueError):
            with self.lock:
                self.provider_failures += 1
            return self.cached_vector("attribute", query, OBJECT_DIMENSION), "cache"

    def knn(
        self,
        alias: str,
        vector: list[float],
        top_k: int,
        channel: str,
        camera_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": vector,
            "k": top_k,
            "num_candidates": max(top_k * 10, 20),
        }
        if camera_ids:
            knn["filter"] = {"terms": {"camera_id": camera_ids}}
        value = self.es(
            "POST",
            f"/{alias}/_search",
            {
                "size": top_k,
                "knn": knn,
                "_source": {"excludes": ["embedding"]},
            },
        )
        results = []
        for hit in value.get("hits", {}).get("hits", []):
            source = dict(hit["_source"])
            source.update(
                {
                    "id": hit["_id"],
                    "score": hit.get("_score", 0),
                    "search_channel": channel,
                }
            )
            results.append(source)
        return results

    def decompose(self, query: str) -> dict[str, Any]:
        if not self.lease("phase12-llm", "search_llm"):
            return fallback_decomposition(query)
        try:
            return self.llm.decompose(query)
        except ProviderError:
            with self.lock:
                self.provider_failures += 1
            return fallback_decomposition(query)

    def critic_results(
        self, query: str, results: list[dict[str, Any]], critic_top_k: int
    ) -> tuple[list[dict[str, Any]], str]:
        if critic_top_k <= 0 or not self.lease("phase12-critic", "search_critic"):
            return results, "unavailable"
        attempted = 0
        for result in results[:critic_top_k]:
            uri = str(result.get("asset_uri", ""))
            try:
                clip = selected_path(
                    self.clip_root, uri, "selected-clip", ".mp4"
                )
                result["critic"] = self.critic.evaluate(query, clip)
                attempted += 1
            except (ValueError, ProviderError):
                result["critic"] = {
                    "verdict": "uncertain",
                    "confidence": 0,
                    "reason": "critic unavailable for this result",
                }
        return results, "completed" if attempted else "unavailable"

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        top_k = min(max(int(payload.get("top_k", 5)), 1), 50)
        requested_route = payload.get("route")
        if (
            requested_route is None
            or requested_route == ""
            or requested_route == "auto"
        ):
            decomposition = self.decompose(query)
            route = str(decomposition.get("route", ""))
        else:
            if not isinstance(requested_route, str):
                raise ValueError(
                    "route must be auto, action, attribute or fusion"
                )
            route = str(requested_route)
            if route not in {"action", "attribute", "fusion"}:
                raise ValueError(
                    "route must be auto, action, attribute or fusion"
                )
            decomposition = {
                "route": route,
                "action_query": query if route in {"action", "fusion"} else "",
                "attribute_query": query
                if route in {"attribute", "fusion"}
                else "",
                "camera_ids": [],
                "source": "manual",
            }
        if route not in {"action", "attribute", "fusion"}:
            raise ValueError("route must be auto, action, attribute or fusion")
        camera_ids = payload.get("camera_ids") or decomposition.get("camera_ids") or []
        provider_sources: dict[str, str] = {}
        degraded_channels: list[str] = []
        action: list[dict[str, Any]] = []
        attribute: list[dict[str, Any]] = []
        if route in {"action", "fusion"}:
            action_query = str(decomposition.get("action_query") or query)
            vector, provider_sources["action"] = self.action_vector(action_query)
            action = self.knn(
                "vss-video-embeddings", vector, top_k, "action", camera_ids
            )
        if route in {"attribute", "fusion"}:
            attribute_query = str(decomposition.get("attribute_query") or query)
            try:
                vector, provider_sources["attribute"] = self.attribute_vector(
                    attribute_query
                )
                attribute = self.knn(
                    "vss-object-embeddings", vector, top_k, "attribute", camera_ids
                )
            except ProviderError:
                if route != "fusion":
                    raise
                provider_sources["attribute"] = "disabled"
                degraded_channels.append("attribute")
        if route == "fusion":
            results = reciprocal_rank_fusion([action, attribute])[:top_k]
        else:
            results = (action or attribute)[:top_k]
        results, critic_status = self.critic_results(
            query, results, min(int(payload.get("critic_top_k", 0)), 3)
        )
        response = {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "query": query,
            "route": route,
            "decomposition": decomposition,
            "provider_sources": provider_sources,
            "degraded_channels": degraded_channels,
            "critic_status": critic_status,
            "result_count": len(results),
            "results": results,
            "searched_at": utc_now(),
        }
        with self.lock:
            self.searches += 1
            self.last_search = {
                "query": query,
                "route": route,
                "result_count": len(results),
                "critic_status": critic_status,
                "searched_at": response["searched_at"],
            }
        return response

    def search_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        path, bbox_pixels = self.image_payload(payload)
        cache_key = f"{path.name}:{json.dumps(bbox_pixels, sort_keys=True)}"
        try:
            vector = validate_vector(
                self.siglip.image(f"/selected-snapshots/{path.name}", bbox_pixels),
                OBJECT_DIMENSION,
            )
            self.cache_vector("image", cache_key, vector)
            source = "live"
        except (ProviderError, ValueError):
            vector = self.cached_vector("image", cache_key, OBJECT_DIMENSION)
            source = "cache"
        top_k = min(max(int(payload.get("top_k", 5)), 1), 50)
        results = self.knn(
            "vss-object-embeddings",
            vector,
            top_k,
            "search_by_image",
            payload.get("camera_ids"),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "store_id": STORE_ID,
            "query_image": payload["asset_uri"],
            "provider_source": source,
            "result_count": len(results),
            "results": results,
            "searched_at": utc_now(),
        }

    def evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        result_ids = [str(value) for value in payload.get("result_ids", [])]
        relevant_ids = {str(value) for value in payload.get("relevant_ids", [])}
        k = int(payload.get("k", 5))
        return {
            "schema_version": SCHEMA_VERSION,
            "query_id": str(payload.get("query_id", "")),
            "k": k,
            "precision_at_k": precision_at_k(result_ids, relevant_ids, k),
            "ndcg_at_k": ndcg_at_k(result_ids, relevant_ids, k),
            "evaluated_at": utc_now(),
        }

    def metrics(self) -> str:
        state = self.state()
        return "\n".join(
            [
                "# HELP phase12_search_ready Search service readiness.",
                "# TYPE phase12_search_ready gauge",
                f'phase12_search_ready{{store_id="{STORE_ID}"}} {1 if self.ready else 0}',
                "# HELP phase12_search_requests_total Search requests handled.",
                "# TYPE phase12_search_requests_total counter",
                f"phase12_search_requests_total {self.searches}",
                "# HELP phase12_video_embedding_documents Indexed video chunks.",
                "# TYPE phase12_video_embedding_documents gauge",
                f"phase12_video_embedding_documents {state['video_documents']}",
                "# HELP phase12_object_embedding_documents Indexed object crops.",
                "# TYPE phase12_object_embedding_documents gauge",
                f"phase12_object_embedding_documents {state['object_documents']}",
                "# HELP phase12_provider_failures_total Provider failures with fallback.",
                "# TYPE phase12_provider_failures_total counter",
                f"phase12_provider_failures_total {self.provider_failures}",
                "",
            ]
        )


DASHBOARD_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 12 video search</title><style>
body{margin:0;background:#071018;color:#edf6ff;font:14px system-ui}
main{max-width:1180px;margin:auto;padding:18px}form,.card{background:#111d28;
border:1px solid #294052;border-radius:10px;padding:14px;margin-bottom:12px}
input,select,button{font:inherit;padding:9px;border-radius:6px;border:1px solid #486276}
input{width:min(620px,70%)}button{background:#76e7ae;color:#062015;font-weight:700}
.result{border-left:4px solid #76e7ae;padding:9px;margin:8px 0;background:#0d1822}
.muted{color:#94aabc}.warn{color:#ffd27d}code{color:#9ed7ff}
</style></head><body><main><h1>Phase 12 · video search</h1>
<p class="muted">Cosmos-Embed1 action search · attribute search chỉ dùng khi SigLIP2 được bật</p>
<form id="f"><input id="q" value="person walking with a backpack" required>
<select id="route"><option value="">auto</option><option>action</option>
<option>attribute</option><option>fusion</option></select>
<button>Search</button></form><div class="card"><b id="status">Ready</b>
<div id="results"></div></div></main><script>
const f=document.querySelector('#f'),s=document.querySelector('#status'),r=document.querySelector('#results');
f.addEventListener('submit',async e=>{e.preventDefault();s.textContent='Searching…';r.innerHTML='';
try{const body={query:q.value,top_k:5,critic_top_k:0};if(route.value)body.route=route.value;
const x=await fetch('/api/v1/search',{method:'POST',headers:{'content-type':'application/json'},
body:JSON.stringify(body)});const j=await x.json();if(!x.ok)throw Error(j.error||x.status);
s.textContent=`${j.route} · ${j.result_count} results · critic ${j.critic_status}`+
(j.degraded_channels?.length?` · skipped ${j.degraded_channels.join(", ")}`:"");
r.innerHTML=j.results.map(v=>`<div class=result><b>${v.camera_id||'unknown camera'}</b>
 · ${v.start_time||v.frame_time||v['@timestamp']||''}<br><code>${v.asset_uri||''}</code>
<br><span class=muted>score ${Number(v.fusion_score||v.score||0).toFixed(4)}
 · ${v.object_class||v.search_channel||''}</span></div>`).join('')||'<p>No indexed match.</p>';
}catch(e){s.textContent='Search unavailable: '+e.message;s.className='warn'}})
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    runtime: Runtime

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_value(
        self, value: Any, status: HTTPStatus = HTTPStatus.OK, content_type: str = "application/json"
    ) -> None:
        if content_type == "application/json":
            body = json.dumps(value, separators=(",", ":")).encode()
        else:
            body = str(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 10 * 1024 * 1024:
            raise ValueError("request body is empty or too large")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health/live":
            self.send_value({"status": "live", "schema_version": SCHEMA_VERSION})
        elif path == "/health/ready":
            state = self.runtime.state()
            self.send_value(
                state,
                HTTPStatus.OK if state["ready"] else HTTPStatus.SERVICE_UNAVAILABLE,
            )
        elif path == "/api/v1/state":
            self.send_value(self.runtime.state())
        elif path in {"/", "/dashboard"}:
            self.send_value(DASHBOARD_HTML, content_type="text/html")
        elif path == "/metrics":
            self.send_value(self.runtime.metrics(), content_type="text/plain")
        else:
            self.send_value({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            payload = self.payload()
            if path == "/api/v1/index/video":
                value = self.runtime.index_video(payload)
            elif path == "/api/v1/index/object":
                value = self.runtime.index_object(payload)
            elif path == "/api/v1/search":
                value = self.runtime.search(payload)
            elif path == "/api/v1/search/image":
                value = self.runtime.search_image(payload)
            elif path == "/api/v1/decompose":
                value = self.runtime.decompose(str(payload.get("query", "")))
            elif path == "/api/v1/evaluation":
                value = self.runtime.evaluation(payload)
            else:
                self.send_value({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            self.send_value(value)
        except ReindexRequired as error:
            self.send_value(
                {"error": str(error), "code": "reindex_required"},
                HTTPStatus.CONFLICT,
            )
        except (ValueError, json.JSONDecodeError, KeyError) as error:
            self.send_value({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except (RTEmbeddingError, ProviderError) as error:
            self.send_value(
                {"error": str(error), "code": "provider_unavailable"},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except Exception as error:
            log("error", "request_failed", path=path, error_type=type(error).__name__)
            self.send_value(
                {"error": "internal search error"}, HTTPStatus.INTERNAL_SERVER_ERROR
            )


def main() -> int:
    runtime = Runtime()
    runtime.check_health()
    lock_path = runtime.runtime_root / "indexer.lock"
    lock_file = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("error", "duplicate_indexer_denied", lock=str(lock_path))
        return 2
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    Handler.runtime = runtime
    server = ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("HTTP_PORT", "8080"))), Handler
    )
    stop = threading.Event()

    def shutdown(signum: int, frame: object) -> None:
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log(
        "info",
        "service_ready",
        store_id=STORE_ID,
        video_generation=VIDEO_GENERATION,
        object_generation=OBJECT_GENERATION,
    )
    server.serve_forever(poll_interval=0.5)
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
