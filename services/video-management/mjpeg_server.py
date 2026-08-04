from __future__ import annotations

import argparse
import http.server
import json
import os
import signal
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from ai_overlay import AI_OVERLAY_HTML, AIStateResolver


class LiveHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ntc-vss-live/1.0"

    def _send_bytes(self, content: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self'; connect-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
        )
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/":
            page = b"""<!doctype html><meta charset=utf-8>
<title>cam-01 mainstream 101</title>
<style>body{margin:0;background:#111;color:#eee;font:14px sans-serif}header{padding:8px}img{display:block;max-width:100vw;max-height:calc(100vh - 44px);margin:auto}</style>
<header>cam-01 channel 101 mainstream | 2560x1440 | browser time: <span id=t></span></header>
<img src=/mjpeg-main><script>setInterval(()=>t.textContent=new Date().toLocaleString(),250);</script>"""
            self._send_bytes(page, "text/html; charset=utf-8")
            return
        if path == "/ai-overlay":
            self._send_bytes(
                AI_OVERLAY_HTML.encode("utf-8"), "text/html; charset=utf-8"
            )
            return
        if path == "/api/ai-state":
            state = self.server.ai_state_resolver.resolve()
            self._send_bytes(
                json.dumps(state, separators=(",", ":")).encode(),
                "application/json",
            )
            return
        if path not in {"/mjpeg", "/mjpeg-main"}:
            self.send_error(404)
            return
        if path == "/mjpeg-main":
            width, height, fps, pipeline_name = 2560, 1440, 5, "mjpeg-main"
        else:
            width, height, fps, pipeline_name = 1280, 720, 8, "mjpeg-ai"
        uri = self.server.proxy_uri()
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        pipeline = (
            "IFS= read -r camera_uri; "
            "exec gst-launch-1.0 -q "
            'rtspsrc location="$camera_uri" protocols=tcp latency=100 '
            'drop-on-latency=true buffer-mode=none ! '
            "decodebin ! queue max-size-buffers=2 max-size-time=200000000 "
            "leaky=downstream ! nvvideoconvert ! videoscale ! "
            f"videorate drop-only=true max-rate={fps} ! "
            f"video/x-raw,format=I420,width={width},height={height},"
            f"framerate={fps}/1 ! identity name={pipeline_name} ! "
            "nvjpegenc quality=82 ! multipartmux boundary=frame ! fdsink fd=1"
        )
        process = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                self.server.container,
                "bash",
                "-lc",
                pipeline,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            assert process.stdin is not None
            process.stdin.write((uri + "\n").encode())
            process.stdin.close()
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            subprocess.run(
                [
                    "docker",
                    "exec",
                    self.server.container,
                    "pkill",
                    "-TERM",
                    "-f",
                    f"identity name={pipeline_name}",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)

    def log_message(self, format: str, *args: object) -> None:
        return


class LiveServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        secret_socket: Path,
        container: str,
        vios_streams_url: str,
        metadata_state_url: str,
        rt_cv_metrics_url: str,
        metadata_stale_seconds: float,
        bbox_grace_seconds: float,
        ai_request_retries: int,
        ai_request_timeout_seconds: float,
    ):
        super().__init__(address, LiveHandler)
        self.secret_socket = secret_socket
        self.container = container
        self.vios_streams_url = vios_streams_url
        self.ai_state_resolver = AIStateResolver(
            metadata_state_url,
            rt_cv_metrics_url,
            stale_after_seconds=metadata_stale_seconds,
            bbox_grace_seconds=bbox_grace_seconds,
            request_retries=ai_request_retries,
            request_timeout_seconds=ai_request_timeout_seconds,
        )

    def proxy_uri(self) -> str:
        with urlopen(self.vios_streams_url, timeout=10) as response:
            wrappers = json.load(response)
        for wrapper in wrappers:
            for values in wrapper.values():
                if not isinstance(values, list):
                    continue
                for stream in values:
                    if (
                        isinstance(stream, dict)
                        and stream.get("name") == "cam-01"
                        and str(stream.get("url", "")).startswith("rtsp://")
                    ):
                        return str(stream["url"])
        raise RuntimeError("VIOS returned no live proxy for cam-01")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--secret-socket", type=Path, required=True)
    parser.add_argument("--container", default="ntc-vss-phase06-streamprocessing")
    parser.add_argument(
        "--vios-streams-url",
        default="http://127.0.0.1:30888/vst/api/v1/sensor/streams",
    )
    parser.add_argument(
        "--metadata-state-url",
        default="http://127.0.0.1:39080/debug/state",
    )
    parser.add_argument(
        "--rt-cv-metrics-url",
        default="http://127.0.0.1:39000/api/v1/metrics",
    )
    parser.add_argument("--metadata-stale-seconds", type=float, default=10.0)
    parser.add_argument("--bbox-grace-seconds", type=float, default=5.0)
    parser.add_argument("--ai-request-retries", type=int, default=3)
    parser.add_argument("--ai-request-timeout-seconds", type=float, default=0.75)
    args = parser.parse_args()
    server = LiveServer(
        (args.host, args.port),
        args.secret_socket,
        args.container,
        args.vios_streams_url,
        args.metadata_state_url,
        args.rt_cv_metrics_url,
        args.metadata_stale_seconds,
        args.bbox_grace_seconds,
        args.ai_request_retries,
        args.ai_request_timeout_seconds,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
