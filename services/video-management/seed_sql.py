from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from contracts import load_registry

NAMESPACE = uuid.UUID("ad4f3a08-b30d-4cf4-91ed-10bc566867d0")


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render(registry_path: Path) -> str:
    registry = load_registry(registry_path)
    store = registry["store"]
    store_uuid = uuid.uuid5(NAMESPACE, store["store_id"])
    statements = [
        "BEGIN;",
        (
            "INSERT INTO stores(id, code, name, timezone) VALUES "
            f"('{store_uuid}', {quote(store['store_id'])}, {quote(store['name'])}, "
            f"{quote(store['timezone'])}) "
            "ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, "
            "timezone=EXCLUDED.timezone, updated_at=now();"
        ),
    ]
    for camera in registry["cameras"]:
        camera_uuid = uuid.uuid5(NAMESPACE, f"{store['store_id']}:{camera['camera_id']}")
        statements.append(
            "INSERT INTO cameras(id, store_id, external_id, name, status) VALUES "
            f"('{camera_uuid}', '{store_uuid}', {quote(camera['camera_id'])}, "
            f"{quote(camera['name'])}, 'enabled') "
            "ON CONFLICT (store_id, external_id) DO UPDATE SET "
            "name=EXCLUDED.name, status=EXCLUDED.status, updated_at=now();"
        )
        statements.append(
            "INSERT INTO camera_credentials_ref(camera_id, secret_provider, secret_ref) VALUES "
            f"('{camera_uuid}', 'runtime_file', "
            f"{quote(camera['main_stream']['uri_secret_ref'])}) "
            "ON CONFLICT (camera_id) DO UPDATE SET secret_provider=EXCLUDED.secret_provider, "
            "secret_ref=EXCLUDED.secret_ref, updated_at=now();"
        )
        for stream_type, key in (("main", "main_stream"), ("ai_substream", "ai_substream")):
            stream = camera[key]
            stream_uuid = uuid.uuid5(NAMESPACE, f"{camera_uuid}:{stream_type}")
            statements.append(
                "INSERT INTO camera_streams"
                "(id, camera_id, stream_type, uri_secret_ref, codec, width, height, fps, enabled) "
                f"VALUES ('{stream_uuid}', '{camera_uuid}', {quote(stream_type)}, "
                f"{quote(stream['uri_secret_ref'])}, {quote(stream['codec'])}, "
                f"{stream['width']}, {stream['height']}, {stream['fps']}, true) "
                "ON CONFLICT (camera_id, stream_type) DO UPDATE SET "
                "uri_secret_ref=EXCLUDED.uri_secret_ref, codec=EXCLUDED.codec, "
                "width=EXCLUDED.width, height=EXCLUDED.height, fps=EXCLUDED.fps, "
                "enabled=EXCLUDED.enabled;"
            )
    statements.extend(
        [
            "INSERT INTO schema_migrations(version) VALUES ('002_video_management') "
            "ON CONFLICT (version) DO NOTHING;",
            "COMMIT;",
        ]
    )
    return "\n".join(statements) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("config/cameras/cameras.simulated.json"),
    )
    args = parser.parse_args()
    print(render(args.registry), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
