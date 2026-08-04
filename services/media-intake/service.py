from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
ASSET_ID = re.compile(r"[0-9a-f]{64}")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.active = root / "active"
        self.prepared = root / "prepared"
        self.trash = root / "trash"
        self.registry = root / "registry.json"
        self.lock = threading.RLock()
        for path in (self.active, self.prepared, self.trash):
            path.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict]:
        if not self.registry.exists():
            return {}
        value = json.loads(self.registry.read_text(encoding="utf-8"))
        if value.get("store_id") != STORE_ID or not isinstance(value.get("assets"), dict):
            raise ValueError("invalid media registry")
        return value["assets"]

    def save(self, assets: dict[str, dict]) -> None:
        temporary = self.registry.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "store_id": STORE_ID,
                    "updated_at": utc_now(),
                    "assets": assets,
                },
                separators=(",", ":"),
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.registry)

    @staticmethod
    def validate(name: str, content_type: str, body: bytes) -> tuple[str, bool]:
        if (
            not name
            or len(name) > 200
            or Path(name).name != name
            or name.startswith(".")
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError("invalid_filename")
        extension = Path(name).suffix.lower()
        if extension not in {".mp4", ".mkv"}:
            raise ValueError("unsupported_container")
        if content_type not in {"video/mp4", "video/x-matroska"}:
            raise ValueError("unsupported_content_type")
        if extension == ".mp4":
            if (
                len(body) < 32
                or body[4:8] != b"ftyp"
                or b"moov" not in body
                or b"mdat" not in body
            ):
                raise ValueError("invalid_mp4")
            h264 = b"avc1" in body or b"avc3" in body
        else:
            if not body.startswith(b"\x1aE\xdf\xa3"):
                raise ValueError("invalid_matroska")
            h264 = b"V_MPEG4/ISO/AVC" in body
        if not h264:
            raise ValueError("unsupported_codec")
        return extension, extension == ".mp4"

    def create(
        self, name: str, content_type: str, body: bytes, idempotency_key: str
    ) -> tuple[dict, bool]:
        extension, summary_ready = self.validate(name, content_type, body)
        digest = hashlib.sha256(body).hexdigest()
        with self.lock:
            assets = self.load()
            existing = assets.get(digest)
            if existing and not existing.get("deleted"):
                return existing, False
            raw_path = self.active / f"{digest}{extension}"
            raw_path.write_bytes(body)
            if summary_ready:
                shutil.copy2(raw_path, self.prepared / f"{digest}.mp4")
            now = utc_now()
            record = {
                "schema_version": SCHEMA_VERSION,
                "store_id": STORE_ID,
                "asset_id": digest,
                "filename": name,
                "content_sha256": digest,
                "content_type": content_type,
                "container": extension.removeprefix("."),
                "codec": "h264",
                "bytes": len(body),
                "status": "prepared" if summary_ready else "uploaded",
                "summary_ready": summary_ready,
                "asset_uri": (
                    f"uploaded-media://{digest}.mp4" if summary_ready else None
                ),
                "created_at": now,
                "updated_at": now,
                "deleted": False,
                "idempotency_key": idempotency_key,
                "provenance": {
                    "plane": "media-intake",
                    "selection_required": True,
                    "raw_archive_scanned": False,
                },
            }
            assets[digest] = record
            self.save(assets)
            return record, True

    def mutate(self, asset_id: str, restore: bool) -> dict:
        if ASSET_ID.fullmatch(asset_id) is None:
            raise FileNotFoundError
        with self.lock:
            assets = self.load()
            record = assets.get(asset_id)
            if record is None:
                raise FileNotFoundError
            extension = f".{record['container']}"
            source_root = self.trash if restore else self.active
            target_root = self.active if restore else self.trash
            source = source_root / f"{asset_id}{extension}"
            target = target_root / f"{asset_id}{extension}"
            if source.exists():
                source.replace(target)
            prepared_source = (
                self.trash / f"{asset_id}.prepared.mp4"
                if restore
                else self.prepared / f"{asset_id}.mp4"
            )
            prepared_target = (
                self.prepared / f"{asset_id}.mp4"
                if restore
                else self.trash / f"{asset_id}.prepared.mp4"
            )
            if prepared_source.exists():
                prepared_source.replace(prepared_target)
            record["deleted"] = not restore
            record["status"] = (
                "prepared" if restore and record.get("summary_ready") else
                "uploaded" if restore else "quarantined"
            )
            record["updated_at"] = utc_now()
            record["restore_available"] = not restore
            assets[asset_id] = record
            self.save(assets)
            return record


class Handler(BaseHTTPRequestHandler):
    store: Store
    server_version = "NTC-Media-Intake"
    sys_version = ""

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in {"/health/live", "/health/ready"}:
            self._json(200, {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "status": "ready"})
            return
        if path == "/api/v1/assets":
            deleted = parse_qs(urlsplit(self.path).query).get("deleted", ["exclude"])[0]
            with self.store.lock:
                assets = list(self.store.load().values())
            if deleted == "exclude":
                assets = [item for item in assets if not item.get("deleted")]
            elif deleted == "only":
                assets = [item for item in assets if item.get("deleted")]
            elif deleted != "include":
                self._json(400, {"status": "error", "code": "invalid_deleted_filter"})
                return
            self._json(200, {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "assets": assets})
            return
        media = re.fullmatch(r"/api/v1/assets/([0-9a-f]{64})/media", path)
        if media:
            asset_id = media.group(1)
            with self.store.lock:
                record = self.store.load().get(asset_id)
            candidate = self.store.prepared / f"{asset_id}.mp4"
            if record is None or record.get("deleted") or not candidate.is_file():
                self._json(404, {"status": "error", "code": "asset_media_not_found"})
                return
            body = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        restore = re.fullmatch(r"/api/v1/assets/([0-9a-f]{64})/restore", path)
        if restore:
            try:
                self._json(200, self.store.mutate(restore.group(1), True))
            except FileNotFoundError:
                self._json(404, {"status": "error", "code": "asset_not_found"})
            return
        if path != "/api/v1/assets":
            self._json(404, {"status": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_UPLOAD_BYTES:
                raise ValueError("invalid_upload_size")
            name = unquote(self.headers.get("X-File-Name", ""))
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
            key = self.headers.get("Idempotency-Key", "")
            if not key or len(key) > 160:
                raise ValueError("idempotency_key_required")
            record, created = self.store.create(name, content_type, self.rfile.read(length), key)
            self._json(201 if created else 200, record)
        except ValueError as error:
            self._json(400, {"schema_version": SCHEMA_VERSION, "store_id": STORE_ID, "status": "error", "code": str(error)})

    def do_DELETE(self) -> None:  # noqa: N802
        match = re.fullmatch(r"/api/v1/assets/([0-9a-f]{64})", urlsplit(self.path).path)
        if match is None:
            self._json(404, {"status": "not_found"})
            return
        try:
            self._json(200, self.store.mutate(match.group(1), False))
        except FileNotFoundError:
            self._json(404, {"status": "error", "code": "asset_not_found"})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    Handler.store = Store(Path(os.environ.get("MEDIA_INTAKE_DIR", "/runtime/media-intake")))
    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("HTTP_PORT", "39420"))), Handler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
