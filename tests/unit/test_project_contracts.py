from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_yaml(path: str) -> dict:
    with (ROOT / path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_raw_video_plane_is_explicitly_separate() -> None:
    architecture = read("docs/decisions/ADR-002-video-ai-plane.md")
    matrix = read("docs/architecture/feature-matrix.md")
    assert "No direct raw-storage-to-analytics-output connection" in architecture
    assert "There is no direct raw-storage-to-output path" in matrix


def test_camera_inventory_has_ten_data_rows_and_no_rtsp_passwords() -> None:
    rows = read("docs/architecture/camera-inventory-template.csv").splitlines()
    assert len(rows) == 11
    assert all("secret://cameras/" in row for row in rows[1:])
    assert all("rtsp://" not in row for row in rows[1:])


def test_required_models_are_locked() -> None:
    manifest = load_yaml("config/models/model-manifest.yaml")
    assert manifest["release"]["vss"]["version"] == "3.2.1"
    assert manifest["llm"]["id"] == "nvidia/nvidia-nemotron-nano-9b-v2"
    assert manifest["vlm"]["id"] == "nvidia/cosmos3-nano-reasoner"
    assert manifest["rt_cv"]["detector"]["version"] == "1.0.2"
    assert manifest["rt_embed"]["embedding_dim"] == 768
    assert manifest["object_embedding"]["model"] == "siglip2-so400m-patch16-256"


def test_infra_has_no_gpu_service_and_binds_ports_to_localhost() -> None:
    compose = load_yaml("deploy/compose/infra.compose.yml")
    for service in compose["services"].values():
        assert "deploy" not in service or "devices" not in str(service["deploy"])
        for port in service.get("ports", []):
            assert "127.0.0.1" in port or "INFRA_BIND_ADDRESS" in port


def test_scripts_have_no_destructive_docker_commands() -> None:
    forbidden = re.compile(
        r"docker\s+(?:system|image|builder|volume)\s+prune"
        r"|docker\s+rmi"
        r"|docker\s+compose[^\n]*\sdown\s+-v"
    )
    for script in (ROOT / "scripts").glob("*.sh"):
        assert not forbidden.search(script.read_text(encoding="utf-8")), script


def test_model_download_is_single_profile_only() -> None:
    script = read("scripts/download-model-cache.sh")
    assert "download-to-cache -p" in script
    assert "download-to-cache --all" not in script
    assert "LLM_PROFILE_ID" in script
    assert "VLM_PROFILE_ID" in script


def test_phase05_restore_is_dry_run_by_default() -> None:
    restore = read("scripts/restore-infra.sh")
    assert "execute=false" in restore
    assert 'if [[ "$execute" != true ]]' in restore
    assert "refusing to overwrite" in restore
