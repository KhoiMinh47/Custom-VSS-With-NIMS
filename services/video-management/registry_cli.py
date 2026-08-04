from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from contracts import ContractError, load_registry, validate_resolved_uri
from vios_client import ViosClient


def camera_channel_uri(uri: str, channel: str) -> str:
    parsed = urlsplit(uri)
    path = re.sub(
        r"/Streaming/Channels/(?:101|102)(?=/|$)",
        f"/Streaming/Channels/{channel}",
        parsed.path,
        flags=re.IGNORECASE,
    )
    if path == parsed.path and not re.search(
        rf"/Streaming/Channels/{channel}(?=/|$)",
        parsed.path,
        flags=re.IGNORECASE,
    ):
        raise ContractError("physical camera URI must use channel 101 or 102")
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def _stream_identity(stream: dict[str, Any]) -> tuple[str, str]:
    stream_id = str(stream.get("streamId") or stream.get("id") or stream.get("uuid") or "")
    name = str(stream.get("name") or stream.get("fileName") or stream.get("filename") or "")
    return stream_id, name


def _rtsp_uri(stream: dict[str, Any]) -> str:
    for key in ("rtspUrl", "url", "liveUrl", "rtspURL"):
        value = stream.get(key)
        if isinstance(value, str) and value.startswith("rtsp://"):
            return value
    nested = stream.get("stream")
    if isinstance(nested, dict):
        return _rtsp_uri(nested)
    return ""


def generate_simulated_secrets(registry: dict[str, Any], source: ViosClient, path: Path) -> None:
    streams = source.streams()
    candidates: list[tuple[str, str, str]] = []
    for stream in streams:
        stream_id, name = _stream_identity(stream)
        uri = _rtsp_uri(stream)
        if stream_id and uri:
            candidates.append((name, stream_id, uri))
    candidates.sort()
    if len(candidates) < len(registry["cameras"]):
        raise ContractError(
            f"NVStreamer exposes {len(candidates)} usable streams; "
            f"{len(registry['cameras'])} required"
        )
    secrets: dict[str, str] = {}
    selected = candidates[: len(registry["cameras"])]
    for camera, (_, _, uri) in zip(registry["cameras"], selected, strict=True):
        validate_resolved_uri(uri)
        secrets[camera["main_stream"]["uri_secret_ref"]] = uri
        secrets[camera["ai_substream"]["uri_secret_ref"]] = uri
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(secrets, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def load_secrets(path: Path) -> dict[str, str]:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ContractError(f"{path} must not be accessible by group/other")
    data = json.loads(path.read_text(encoding="utf-8"))
    for uri in data.values():
        validate_resolved_uri(uri)
    return data


def onboard(
    registry: dict[str, Any],
    secrets: dict[str, str],
    target: ViosClient,
    streamprocessor: ViosClient,
) -> None:
    existing = {str(stream.get("name", "")) for stream in target.streams()}
    for camera in registry["cameras"]:
        camera_id = camera["camera_id"]
        if camera_id in existing:
            continue
        ref = camera["main_stream"]["uri_secret_ref"]
        if ref not in secrets:
            raise ContractError(f"missing secret value for {ref}")
        target.add_sensor(camera_id, camera["name"], secrets[ref])

    sync_proxies(registry, secrets, target, streamprocessor)


def sync_proxies(
    registry: dict[str, Any],
    secrets: dict[str, str],
    target: ViosClient,
    streamprocessor: ViosClient,
    force: bool = False,
) -> None:
    target_streams = {
        str(stream.get("name", "")): stream for stream in target.streams()
    }
    proxied_ids = {
        str(stream.get("sensorId", "")) for stream in streamprocessor.proxy_streams()
    }
    for camera in registry["cameras"]:
        camera_id = camera["camera_id"]
        stream = target_streams.get(camera_id)
        if stream is None:
            raise ContractError(f"VIOS did not return a stream for {camera_id}")
        stream_id, _ = _stream_identity(stream)
        if not stream_id:
            raise ContractError(f"VIOS returned no stable stream ID for {camera_id}")
        if stream_id in proxied_ids and not force:
            continue
        if stream_id in proxied_ids:
            streamprocessor.delete_proxy(stream_id)
        profile = camera["main_stream"]
        streamprocessor.add_proxy(
            stream_id,
            camera_id,
            secrets[profile["uri_secret_ref"]],
            profile["codec"].lower(),
            f"{profile['width']}x{profile['height']}",
            str(profile["fps"]),
        )


def activate_camera(
    registry: dict[str, Any],
    secrets: dict[str, str],
    camera_id: str,
    uri: str,
    target: ViosClient,
    streamprocessor: ViosClient,
) -> None:
    camera = next(
        (item for item in registry["cameras"] if item["camera_id"] == camera_id),
        None,
    )
    if camera is None:
        raise ContractError(f"camera {camera_id!r} is not present in the registry")
    validate_resolved_uri(uri)
    main_uri = camera_channel_uri(uri, "101")
    ai_uri = camera_channel_uri(uri, "102")
    secrets[camera["main_stream"]["uri_secret_ref"]] = main_uri
    secrets[camera["ai_substream"]["uri_secret_ref"]] = ai_uri

    existing = {
        str(stream.get("name", "")): stream for stream in target.streams()
    }.get(camera_id)
    if existing is not None:
        stream_id, _ = _stream_identity(existing)
        if not stream_id:
            raise ContractError(f"VIOS returned no stable stream ID for {camera_id}")
        try:
            streamprocessor.delete_proxy(stream_id)
        except RuntimeError:
            pass
        target.delete_sensor(stream_id)

    target.add_sensor(camera_id, camera["name"], main_uri)
    deadline = time.monotonic() + 60
    replacement: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        replacement = next(
            (
                stream
                for stream in target.streams()
                if str(stream.get("name", "")) == camera_id
            ),
            None,
        )
        if replacement is not None:
            break
        time.sleep(2)
    if replacement is None:
        raise ContractError(f"VIOS did not expose replacement stream for {camera_id}")
    stream_id, _ = _stream_identity(replacement)
    profile = camera["main_stream"]
    streamprocessor.add_proxy(
        stream_id,
        camera_id,
        main_uri,
        profile["codec"].lower(),
        f"{profile['width']}x{profile['height']}",
        str(profile["fps"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 06 VIOS camera registry adapter")
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("config/cameras/cameras.simulated.json"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    generate = subparsers.add_parser("generate-simulated-secrets")
    generate.add_argument("--source-url", default="http://127.0.0.1:31000")
    generate.add_argument("--output", type=Path, default=Path(".secrets/camera-uris.json"))
    sync = subparsers.add_parser("onboard")
    sync.add_argument("--secrets", type=Path, default=Path(".secrets/camera-uris.json"))
    sync.add_argument("--target-url", default="http://127.0.0.1:30888/vst")
    sync.add_argument("--streamprocessor-url", default="http://127.0.0.1:30001")
    refresh = subparsers.add_parser("refresh-proxies")
    refresh.add_argument("--secrets", type=Path, default=Path(".secrets/camera-uris.json"))
    refresh.add_argument("--target-url", default="http://127.0.0.1:30888/vst")
    refresh.add_argument("--streamprocessor-url", default="http://127.0.0.1:30001")
    status = subparsers.add_parser("status")
    status.add_argument("--target-url", default="http://127.0.0.1:30888/vst")
    activate = subparsers.add_parser("activate-camera")
    activate.add_argument("--camera-id", required=True)
    activate.add_argument("--secrets", type=Path, default=Path(".secrets/camera-uris.json"))
    activate.add_argument("--target-url", default="http://127.0.0.1:30888/vst")
    activate.add_argument("--streamprocessor-url", default="http://127.0.0.1:30001")
    args = parser.parse_args()
    try:
        registry = load_registry(args.registry)
        if args.command == "validate":
            print(json.dumps({"status": "ok", "cameras": len(registry["cameras"])}))
        elif args.command == "generate-simulated-secrets":
            generate_simulated_secrets(registry, ViosClient(args.source_url), args.output)
            print(json.dumps({"status": "ok", "secret_refs": len(registry["cameras"]) * 2}))
        elif args.command == "onboard":
            onboard(
                registry,
                load_secrets(args.secrets),
                ViosClient(args.target_url),
                ViosClient(args.streamprocessor_url),
            )
            print(json.dumps({"status": "ok", "cameras": len(registry["cameras"])}))
        elif args.command == "refresh-proxies":
            sync_proxies(
                registry,
                load_secrets(args.secrets),
                ViosClient(args.target_url),
                ViosClient(args.streamprocessor_url),
                force=True,
            )
            print(json.dumps({"status": "ok", "refreshed_proxies": len(registry["cameras"])}))
        elif args.command == "status":
            print(json.dumps(ViosClient(args.target_url).statuses(), indent=2))
        elif args.command == "activate-camera":
            uri = sys.stdin.readline().strip()
            activate_camera(
                registry,
                load_secrets(args.secrets),
                args.camera_id,
                uri,
                ViosClient(args.target_url),
                ViosClient(args.streamprocessor_url),
            )
            uri = ""
            print(json.dumps({"status": "ok", "camera_id": args.camera_id}))
    except (ContractError, OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
