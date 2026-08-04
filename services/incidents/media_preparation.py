from __future__ import annotations

import hashlib
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(os.environ.get("SELECTED_CLIP_DIR", "/runtime/clips"))


def safe_clip(name: str) -> Path:
    if (
        len(name) != 68
        or not name.endswith(".mp4")
        or any(character not in "0123456789abcdef" for character in name[:-4])
    ):
        raise ValueError("invalid selected clip name")
    return ROOT / name


def prepare(name: str) -> dict[str, Any]:
    source = safe_clip(name)
    if not source.is_file():
        raise FileNotFoundError("selected clip is missing")
    temporary = ROOT / f"{name[:-4]}.prepared.tmp.mp4"
    command = [
        "gst-launch-1.0",
        "-q",
        "uridecodebin",
        f"uri={source.resolve().as_uri()}",
        "!",
        "videoconvert",
        "!",
        "videoscale",
        "!",
        "video/x-raw,width=1280,height=720,pixel-aspect-ratio=1/1",
        "!",
        "x264enc",
        "speed-preset=ultrafast",
        "tune=zerolatency",
        "bitrate=2000",
        "key-int-max=25",
        "!",
        "h264parse",
        "!",
        "mp4mux",
        "faststart=true",
        "!",
        "filesink",
        f"location={temporary}",
    ]
    try:
        subprocess.run(command, check=True, timeout=180, capture_output=True)
        payload = temporary.read_bytes()
        if len(payload) <= 32 or b"ftyp" not in payload[:32]:
            raise RuntimeError("prepared media is not MP4")
        temporary.replace(source)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "schema_version": "1.0.0",
        "status": "prepared",
        "filename": name,
        "width": 1280,
        "height": 720,
        "codec": "h264",
        "clip_bytes": source.stat().st_size,
        "clip_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, value: Any) -> None:
        content = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/health/ready":
            self._json(200, {"status": "ready", "schema_version": "1.0.0"})
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/v1/prepare":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length))
            self._json(200, prepare(str(value["filename"])))
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self._json(400, {"status": "rejected", "error": str(error)})
        except Exception as error:
            self._json(503, {"status": "failed", "error_type": type(error).__name__})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("HTTP_PORT", "8080"))), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
