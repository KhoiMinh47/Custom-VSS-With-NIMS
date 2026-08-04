from __future__ import annotations

import json
import os
import signal
import socket
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtsp", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import GLib, Gst, GstRtsp, GstRtspServer  # noqa: E402

from contracts import CAMERA_ID, SCHEMA_VERSION, derive_ai_input_uri


def log(level: str, event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "level": level,
                "service": "phase07-secure-rtsp-relay",
                "event": event,
                "camera_id": CAMERA_ID,
                **fields,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def read_secret(socket_path: Path) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(socket_path))
        client.sendall(b"GET\n")
        response = client.recv(64 * 1024).decode().strip()
    if not response.startswith("rtsp://"):
        raise RuntimeError("camera secret lease is unavailable")
    return derive_ai_input_uri(response)


def read_vios_proxy(streams_url: str) -> str:
    with urlopen(streams_url, timeout=10) as response:
        wrappers = json.load(response)
    for wrapper in wrappers:
        for streams in wrapper.values():
            if not isinstance(streams, list):
                continue
            for stream in streams:
                if (
                    isinstance(stream, dict)
                    and stream.get("name") == CAMERA_ID
                    and str(stream.get("url", "")).startswith("rtsp://")
                ):
                    return str(stream["url"])
    raise RuntimeError("VIOS returned no live proxy for cam-01")


class RelayFactory(GstRtspServer.RTSPMediaFactory):
    def __init__(self, source_uri: str, input_codec: str) -> None:
        super().__init__()
        self.source_uri = source_uri
        self.input_codec = input_codec
        self.set_shared(True)
        self.set_eos_shutdown(True)

    @staticmethod
    def _pad_added(_source: Gst.Element, pad: Gst.Pad, depay: Gst.Element) -> None:
        sink = depay.get_static_pad("sink")
        if sink and not sink.is_linked():
            pad.link(sink)

    def do_create_element(self, _url: GstRtsp.RTSPUrl) -> Gst.Element:
        container = Gst.Bin.new("secure-camera-relay")
        source = Gst.ElementFactory.make("rtspsrc", "camera-source")
        depay = Gst.ElementFactory.make(
            "rtph264depay" if self.input_codec == "h264" else "rtph265depay",
            "depay",
        )
        input_parser = Gst.ElementFactory.make(
            "h264parse" if self.input_codec == "h264" else "h265parse",
            "input-parser",
        )
        output_parser = Gst.ElementFactory.make("h264parse", "output-parser")
        payloader = Gst.ElementFactory.make("rtph264pay", "pay0")
        decoder = Gst.ElementFactory.make(
            "avdec_h264" if self.input_codec == "h264" else "avdec_h265",
            "decoder",
        )
        converter = Gst.ElementFactory.make("videoconvert", "converter")
        scaler = Gst.ElementFactory.make("videoscale", "scaler")
        rate = Gst.ElementFactory.make("videorate", "rate")
        capsfilter = Gst.ElementFactory.make("capsfilter", "output-caps")
        encoder = Gst.ElementFactory.make("x264enc", "encoder")
        processing = [decoder, converter, scaler, rate, capsfilter, encoder]
        capsfilter.set_property(
            "caps",
            Gst.Caps.from_string(
                "video/x-raw,format=I420,width=1280,height=720,framerate=25/1"
            ),
        )
        encoder.set_property("bitrate", 2048)
        encoder.set_property("speed-preset", "ultrafast")
        encoder.set_property("tune", "zerolatency")
        encoder.set_property("key-int-max", 25)
        encoder.set_property("byte-stream", True)
        elements = [source, depay, input_parser, *processing, output_parser, payloader]
        if not all(elements):
            raise RuntimeError("required secure relay elements are unavailable")
        source.set_property("location", self.source_uri)
        source.set_property("protocols", GstRtsp.RTSPLowerTrans.TCP)
        source.set_property("latency", 120)
        source.set_property("drop-on-latency", True)
        payloader.set_property("pt", 96)
        payloader.set_property("config-interval", 1)
        for element in elements:
            container.add(element)
        chain = [depay, input_parser, *processing, output_parser, payloader]
        if not all(left.link(right) for left, right in zip(chain, chain[1:])):
            raise RuntimeError("could not link the secure relay pipeline")
        source.connect("pad-added", self._pad_added, depay)
        return container


class HealthHandler(BaseHTTPRequestHandler):
    relay_state: dict[str, object] = {}

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/health/live", "/health/ready"}:
            self.send_error(404)
            return
        body = json.dumps(
            {
                "status": "ok",
                "schema_version": SCHEMA_VERSION,
                "camera_id": CAMERA_ID,
                "source_role": "ai_substream",
                **self.relay_state,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    Gst.init(None)
    streams_url = os.environ.get("VIOS_STREAMS_URL", "")
    try:
        source_uri = read_secret(Path(os.environ["CAMERA_SECRET_SOCKET"]))
        source_kind = "physical_ai_substream"
        input_codec = "h264"
        upstream_channel = "102"
    except Exception as error:
        if not streams_url:
            raise
        log(
            "warning",
            "physical_ai_secret_unavailable",
            error_type=type(error).__name__,
            fallback="vios_mainstream_proxy",
        )
        source_uri = read_vios_proxy(streams_url)
        source_kind = "vios_mainstream_fallback"
        input_codec = "h265"
        upstream_channel = "101"
    server = GstRtspServer.RTSPServer.new()
    server.set_address("0.0.0.0")
    server.set_service(os.environ.get("RELAY_RTSP_PORT", "39554"))
    mounts = server.get_mount_points()
    relay_path = "/Streaming/Channels/102"
    mounts.add_factory(relay_path, RelayFactory(source_uri, input_codec))
    if server.attach(None) == 0:
        raise RuntimeError("could not attach the RTSP relay server")

    HealthHandler.relay_state = {
        "logical_channel": "102",
        "upstream_channel": upstream_channel,
        "source_kind": source_kind,
        "codec": "h264",
        "resolution": "1280x720",
    }
    health_server = ThreadingHTTPServer(
        ("0.0.0.0", int(os.environ.get("RELAY_HEALTH_PORT", "39101"))),
        HealthHandler,
    )
    threading.Thread(target=health_server.serve_forever, daemon=True).start()
    loop = GLib.MainLoop()

    def stop(_signum: int, _frame: object) -> None:
        log("info", "shutdown_requested")
        health_server.shutdown()
        loop.quit()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log(
        "info",
        "relay_ready",
        listen_path=relay_path,
        codec="h264",
        upstream_channel=upstream_channel,
        logical_channel="102",
        source_kind=source_kind,
        resolution="1280x720",
    )
    try:
        loop.run()
    finally:
        source_uri = ""
        log("info", "relay_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
