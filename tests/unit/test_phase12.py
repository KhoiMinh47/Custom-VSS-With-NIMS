from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rt_contracts = load(
    "phase12_rt_contracts", ROOT / "services/rt-embedding/contracts.py"
)
contracts = load("phase12_search_contracts", ROOT / "services/search/contracts.py")
clients = load("phase12_search_clients", ROOT / "services/search/clients.py")
admission = load(
    "phase12_admission", ROOT / "services/gpu-admission-controller/admission.py"
)


def test_cosmos_embedding_dimension_and_deterministic_chunk_ids() -> None:
    vector = [0.01] * 768
    first = rt_contracts.build_video_document(
        asset_id="clip-1",
        asset_uri="selected-clip://clip-1.mp4",
        camera_id="cam-01",
        creation_time="2026-07-29T09:00:00Z",
        chunk_index=0,
        start_offset_seconds=0,
        end_offset_seconds=10,
        vector=vector,
        frame_count=8,
        clip_sha256="a" * 64,
    )
    second = rt_contracts.build_video_document(
        asset_id="clip-1",
        asset_uri="selected-clip://clip-1.mp4",
        camera_id="cam-01",
        creation_time="2026-07-29T09:00:00Z",
        chunk_index=0,
        start_offset_seconds=0,
        end_offset_seconds=10,
        vector=vector,
        frame_count=8,
        clip_sha256="a" * 64,
    )
    assert first["embedding_id"] == second["embedding_id"]
    assert first["chunk_seconds"] == 10
    assert first["start_time"] == "2026-07-29T09:00:00Z"
    assert first["end_time"] == "2026-07-29T09:00:10Z"
    assert first["model_dimension"] == 768
    assert first["evidence"]["raw_storage_consumed"] is False


def test_vector_dimensions_are_hard_contracts() -> None:
    for vector, dimension in (([0.0] * 767, 768), ([0.0] * 1151, 1152)):
        try:
            contracts.validate_vector(vector, dimension)
        except ValueError:
            pass
        else:
            raise AssertionError("wrong vector dimension was accepted")


def test_selected_clip_rejects_other_schemes_and_traversal(tmp_path: Path) -> None:
    valid = tmp_path / "clip.mp4"
    valid.write_bytes(b"test")
    assert rt_contracts.selected_clip_path(
        tmp_path, "selected-clip://clip.mp4"
    ) == valid
    for invalid in (
        "file:///runtime/raw-video/clip.mp4",
        "selected-clip://../clip.mp4",
        "selected-clip://clip.mkv",
    ):
        try:
            rt_contracts.selected_clip_path(tmp_path, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe media input accepted: {invalid}")


def test_siglip_object_contract_uses_normalized_bbox_and_versions() -> None:
    value = contracts.build_object_document(
        asset_id="snapshot-1",
        asset_uri="selected-snapshot://snapshot.jpg",
        camera_id="cam-01",
        frame_time="2026-07-29T09:00:00Z",
        object_id="person-1",
        track_id="42",
        object_class="Person",
        bbox=[0.1, 0.2, 0.3, 0.4],
        vector=[0.02] * 1152,
    )
    assert value["model_id"] == "siglip2-so400m-patch16-256"
    assert value["model_version"] == "v1.1"
    assert value["model_dimension"] == 1152
    assert value["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert value["store_id"] == "store-001"
    assert value["camera_id"] == "cam-01"
    assert value["@timestamp"].endswith("Z")


def test_bbox_outside_image_is_rejected() -> None:
    for bbox in ([-0.1, 0, 0.2, 0.2], [0.8, 0, 0.3, 0.2], [0, 0.9, 0.2, 0.2]):
        try:
            contracts.normalized_bbox(bbox)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid bbox accepted: {bbox}")


def test_query_decomposition_routes_action_attribute_and_fusion() -> None:
    assert contracts.fallback_decomposition("person walking")["route"] == "fusion"
    assert contracts.fallback_decomposition("red backpack")["route"] == "attribute"
    assert contracts.fallback_decomposition("someone entering")["route"] == "action"
    assert (
        contracts.fallback_decomposition("person entering with a backpack")["route"]
        == "fusion"
    )


def test_reciprocal_rank_fusion_is_stable_and_deduplicated() -> None:
    action = [
        {"asset_id": "a", "search_channel": "action"},
        {"asset_id": "b", "search_channel": "action"},
    ]
    attribute = [
        {"asset_id": "b", "search_channel": "attribute"},
        {"asset_id": "c", "search_channel": "attribute"},
    ]
    value = contracts.reciprocal_rank_fusion([action, attribute])
    assert [item["asset_id"] for item in value] == ["b", "a", "c"]
    assert value[0]["channels"] == ["action", "attribute"]


def test_precision_and_ndcg_metrics() -> None:
    results = ["a", "b", "c"]
    relevant = {"a", "c"}
    assert contracts.precision_at_k(results, relevant, 3) == 2 / 3
    assert 0 < contracts.ndcg_at_k(results, relevant, 3) <= 1
    assert contracts.ndcg_at_k(["a", "c", "b"], relevant, 3) == 1


def test_model_change_produces_a_new_generation_and_requires_reindex_policy() -> None:
    old = contracts.generation_id("model", "1", 768)
    assert old != contracts.generation_id("model", "2", 768)
    assert old != contracts.generation_id("model", "1", 1152)
    source = (ROOT / "services/search/service.py").read_text(encoding="utf-8")
    assert "ReindexRequired" in source
    assert "create a new index and reindex" in source


def test_compose_is_pinned_serialized_and_raw_plane_isolated() -> None:
    text = (ROOT / "deploy/compose/phase12.compose.yml").read_text(encoding="utf-8")
    assert "sha256:978ef47aca4eca1e158b587a962b23a5bd9b7a3e717e61763b5c15e7228a1438" in text
    assert "sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458" in text
    assert "runtime/raw-video" not in text
    assert "FILE_URL_ALLOWED_DIRS: /selected-clips" in text
    assert "NGC_API_KEY" not in text
    assert "camera_password" not in text.lower()
    assert "profiles: [rt-embedding]" in text
    assert "profiles: [siglip]" in text


def test_admission_has_all_phase12_gpu_profiles() -> None:
    source = (
        ROOT / "services/gpu-admission-controller/admission.py"
    ).read_text(encoding="utf-8")
    for profile in ("rt_embedding", "siglip_object", "search_llm", "search_critic"):
        assert profile in source
    assert not admission.decision({"ntc-vss-phase12-rt-embedding"}, 48935, 40000)[0]
    assert not admission.decision({"ntc-vss-phase12-siglip-object"}, 48935, 40000)[0]
    assert admission.decision(set(), 48935, 40000)[0]


def test_critic_unavailable_is_explicit_graceful_degradation() -> None:
    source = (ROOT / "services/search/service.py").read_text(encoding="utf-8")
    assert 'return results, "unavailable"' in source
    assert "critic_status" in source
    assert "returned unchanged" in (
        ROOT / "services/search/README.md"
    ).read_text(encoding="utf-8")


def test_duplicate_indexer_lock_and_search_ui_exist() -> None:
    source = (ROOT / "services/search/service.py").read_text(encoding="utf-8")
    assert "LOCK_EX | fcntl.LOCK_NB" in source
    assert "duplicate_indexer_denied" in source
    assert "Phase 12 · video search" in source
    assert "/api/v1/search/image" in source


def test_query_set_has_all_search_modes_and_no_credentials() -> None:
    lines = (
        ROOT / "docs/evals/search-query-set.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    values = [json.loads(line) for line in lines]
    assert {value["route"] for value in values} == {"action", "attribute", "fusion"}
    combined = json.dumps(values).lower()
    assert "rtsp://" not in combined
    assert "password" not in combined


def test_provider_json_parser_accepts_plain_fenced_and_thinking_responses() -> None:
    expected = {"verdict": "relevant", "confidence": 0.95}
    assert clients.parse_json_object(json.dumps(expected)) == expected
    assert clients.parse_json_object(
        f"```json\n{json.dumps(expected)}\n```"
    ) == expected
    assert clients.parse_json_object(
        f"<think>internal reasoning</think>\n{json.dumps(expected)}"
    ) == expected


def test_provider_json_parser_rejects_non_json_content() -> None:
    try:
        clients.parse_json_object("relevant with high confidence")
    except clients.ProviderError:
        pass
    else:
        raise AssertionError("non-JSON provider response was accepted")


def load_search_service(monkeypatch: pytest.MonkeyPatch):
    rt_client = load(
        "phase12_rt_client_for_service",
        ROOT / "services/rt-embedding/client.py",
    )
    monkeypatch.setitem(sys.modules, "client", rt_client)
    monkeypatch.setitem(sys.modules, "clients", clients)
    monkeypatch.setitem(sys.modules, "contracts", contracts)
    return load(
        "phase12_search_service_for_test",
        ROOT / "services/search/service.py",
    )


def test_query_embedding_providers_require_exact_admission_leases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = load_search_service(monkeypatch)
    runtime = object.__new__(service.Runtime)
    lease_checks: list[tuple[str, str]] = []

    class Provider:
        def text(self, _query: str) -> list[float]:
            raise AssertionError("unleased provider must not be called")

    runtime.rt_embed = Provider()
    runtime.siglip = Provider()
    runtime.lease = lambda name, profile: (
        lease_checks.append((name, profile)) or False
    )
    runtime.cached_vector = (
        lambda channel, _query, dimension: [0.1 if channel == "action" else 0.2]
        * dimension
    )

    action, action_source = runtime.action_vector("cached action")
    attribute, attribute_source = runtime.attribute_vector("cached attribute")

    assert action_source == "cache"
    assert attribute_source == "cache"
    assert len(action) == service.VIDEO_DIMENSION
    assert len(attribute) == service.OBJECT_DIMENSION
    assert lease_checks == [
        ("phase12-rt-embedding", "rt_embedding"),
        ("phase12-siglip", "siglip_object"),
    ]


def test_provider_state_distinguishes_ready_but_unadmitted_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = load_search_service(monkeypatch)
    runtime = object.__new__(service.Runtime)
    runtime.es = lambda *_args, **_kwargs: {"count": 3}
    runtime.ready = True
    runtime.started = time.monotonic()
    runtime.searches = 0
    runtime.provider_failures = 0
    runtime.last_search = None
    runtime.provider_ready = lambda _url: True
    runtime.lease = lambda _name, _profile: False

    value = runtime.state()
    assert value["providers"]["rt_embedding"] == "running_unadmitted"
    assert value["providers"]["siglip2"] == "running_unadmitted"

    runtime.lease = lambda _name, _profile: True
    value = runtime.state()
    assert value["providers"]["rt_embedding"] == "admitted"
    assert value["providers"]["siglip2"] == "admitted"


def test_manual_search_route_skips_decomposition_and_invalid_route_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = load_search_service(monkeypatch)
    runtime = object.__new__(service.Runtime)
    runtime.lock = threading.RLock()
    runtime.searches = 0
    runtime.last_search = None
    runtime.decompose = lambda _query: (_ for _ in ()).throw(
        AssertionError("manual route must not invoke decomposition")
    )
    runtime.action_vector = lambda _query: ([0.1] * service.VIDEO_DIMENSION, "cache")
    runtime.knn = lambda _alias, _vector, _top_k, channel, _camera_ids: [
        {"id": "result-1", "asset_id": "asset-1", "search_channel": channel}
    ]
    runtime.critic_results = lambda _query, results, _top_k: (
        results,
        "unavailable",
    )

    value = runtime.search(
        {"query": "person walking", "route": "action", "top_k": 5}
    )
    assert value["route"] == "action"
    assert value["decomposition"]["source"] == "manual"
    assert value["provider_sources"] == {"action": "cache"}

    for invalid_route in ("invalid", ["action"]):
        with pytest.raises(ValueError, match="route must be"):
            runtime.search(
                {"query": "person walking", "route": invalid_route}
            )


def test_auto_search_route_uses_decomposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = load_search_service(monkeypatch)
    runtime = object.__new__(service.Runtime)
    runtime.lock = threading.RLock()
    runtime.searches = 0
    runtime.last_search = None
    calls: list[str] = []
    runtime.decompose = lambda query: (
        calls.append(query)
        or {
            "route": "action",
            "action_query": query,
            "attribute_query": "",
            "camera_ids": [],
            "source": "deterministic_fallback",
        }
    )
    runtime.action_vector = lambda _query: ([0.1] * service.VIDEO_DIMENSION, "cache")
    runtime.knn = lambda _alias, _vector, _top_k, channel, _camera_ids: [
        {"id": "result-1", "asset_id": "asset-1", "search_channel": channel}
    ]
    runtime.critic_results = lambda _query, results, _top_k: (
        results,
        "unavailable",
    )

    assert runtime.search({"query": "person walking", "route": "auto"})[
        "route"
    ] == "action"
    assert calls == ["person walking"]
