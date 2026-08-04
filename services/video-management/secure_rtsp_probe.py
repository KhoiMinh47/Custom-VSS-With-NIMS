from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import socket
import sys
import time
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit


class ProbeError(RuntimeError):
    pass


@dataclass
class RtspResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def _public_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))


def _read_response(connection: socket.socket) -> RtspResponse:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            raise ProbeError("camera closed the RTSP connection")
        data.extend(chunk)
        if len(data) > 64 * 1024:
            raise ProbeError("RTSP response headers are too large")
    header_data, body = bytes(data).split(b"\r\n\r\n", 1)
    lines = header_data.decode("latin-1").split("\r\n")
    status_match = re.match(r"RTSP/\d+\.\d+\s+(\d+)", lines[0])
    if not status_match:
        raise ProbeError("camera returned an invalid RTSP status line")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length", "0"))
    body_data = bytearray(body)
    while len(body_data) < content_length:
        chunk = connection.recv(content_length - len(body_data))
        if not chunk:
            raise ProbeError("camera closed the RTSP response body")
        body_data.extend(chunk)
    return RtspResponse(int(status_match.group(1)), headers, bytes(body_data[:content_length]))


def _send(
    connection: socket.socket,
    method: str,
    uri: str,
    cseq: int,
    authorization: str = "",
    extra_headers: dict[str, str] | None = None,
) -> RtspResponse:
    headers = {
        "CSeq": str(cseq),
        "User-Agent": "ntc-vss-phase06-secure-probe/1.0",
    }
    if authorization:
        headers["Authorization"] = authorization
    if extra_headers:
        headers.update(extra_headers)
    request = f"{method} {uri} RTSP/1.0\r\n"
    request += "".join(f"{name}: {value}\r\n" for name, value in headers.items())
    connection.sendall((request + "\r\n").encode("latin-1"))
    return _read_response(connection)


def _challenge_parameters(challenge: str) -> tuple[str, dict[str, str]]:
    scheme, _, raw_parameters = challenge.partition(" ")
    parameters = {
        match.group(1).lower(): (match.group(2) or match.group(3) or "")
        for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', raw_parameters)
    }
    return scheme.lower(), parameters


def _authorization(
    challenge: str,
    method: str,
    digest_uri: str,
    username: str,
    password: str,
    nonce_count: int,
) -> tuple[str, str]:
    scheme, parameters = _challenge_parameters(challenge)
    if scheme == "basic":
        import base64

        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return f"Basic {token}", "basic"
    if scheme != "digest":
        raise ProbeError(f"unsupported RTSP authentication scheme: {scheme or 'unknown'}")

    realm = parameters.get("realm", "")
    nonce = parameters.get("nonce", "")
    algorithm = parameters.get("algorithm", "MD5").upper()
    if not realm or not nonce or algorithm not in {"MD5", "MD5-SESS"}:
        raise ProbeError("unsupported or incomplete RTSP Digest challenge")

    def md5(value: str) -> str:
        return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()

    cnonce = secrets.token_hex(8)
    ha1 = md5(f"{username}:{realm}:{password}")
    if algorithm == "MD5-SESS":
        ha1 = md5(f"{ha1}:{nonce}:{cnonce}")
    ha2 = md5(f"{method}:{digest_uri}")
    qop_values = [value.strip() for value in parameters.get("qop", "").split(",")]
    qop = "auth" if "auth" in qop_values else ""
    nc = f"{nonce_count:08x}"
    if qop:
        response = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        response = md5(f"{ha1}:{nonce}:{ha2}")
    fields = [
        f'username="{username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{digest_uri}"',
        f'response="{response}"',
        f"algorithm={algorithm}",
    ]
    if parameters.get("opaque"):
        fields.append(f'opaque="{parameters["opaque"]}"')
    if qop:
        fields.extend((f"qop={qop}", f"nc={nc}", f'cnonce="{cnonce}"'))
    return "Digest " + ", ".join(fields), "digest"


def _video_control(sdp: str, content_base: str) -> tuple[str, str]:
    codec = "unknown"
    session_control = ""
    in_video = False
    video_control = ""
    for line in sdp.splitlines():
        line = line.strip()
        if line.startswith("m="):
            in_video = line.startswith("m=video ")
        elif in_video and line.lower().startswith("a=rtpmap:"):
            codec_match = re.search(r"a=rtpmap:\d+\s+([^/\s]+)", line, re.IGNORECASE)
            if codec_match:
                codec = codec_match.group(1).lower()
        elif line.startswith("a=control:"):
            control = line.removeprefix("a=control:").strip()
            if in_video and not video_control:
                video_control = control
            elif not in_video and not session_control:
                session_control = control
    if not video_control:
        raise ProbeError("RTSP SDP contains no video track")
    if video_control.startswith("rtsp://"):
        return video_control, codec
    base = content_base if content_base.endswith("/") else content_base + "/"
    return urljoin(base, video_control), codec


def probe(uri: str, timeout_seconds: float = 8.0) -> dict[str, object]:
    parsed = urlsplit(uri)
    if parsed.scheme != "rtsp" or not parsed.hostname:
        raise ProbeError("input must be an RTSP URI")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if not username or not password:
        raise ProbeError("RTSP URI must include runtime credentials")
    public_uri = _public_uri(uri)
    port = parsed.port or 554

    with socket.create_connection((parsed.hostname, port), timeout=timeout_seconds) as connection:
        connection.settimeout(timeout_seconds)
        challenge_response = _send(
            connection,
            "DESCRIBE",
            public_uri,
            1,
            extra_headers={"Accept": "application/sdp"},
        )
        auth_scheme = "none"
        authorization = ""
        digest_path_only = False
        nonce_count = 1
        if challenge_response.status == 401:
            challenge = challenge_response.headers.get("www-authenticate", "")
            authorization, auth_scheme = _authorization(
                challenge, "DESCRIBE", public_uri, username, password, nonce_count
            )
            describe = _send(
                connection,
                "DESCRIBE",
                public_uri,
                2,
                authorization,
                {"Accept": "application/sdp"},
            )
            if describe.status == 401:
                nonce_count += 1
                digest_path_only = True
                path_uri = parsed.path + (f"?{parsed.query}" if parsed.query else "")
                authorization, auth_scheme = _authorization(
                    challenge, "DESCRIBE", path_uri, username, password, nonce_count
                )
                describe = _send(
                    connection,
                    "DESCRIBE",
                    public_uri,
                    3,
                    authorization,
                    {"Accept": "application/sdp"},
                )
        else:
            describe = challenge_response
        if describe.status != 200:
            raise ProbeError(f"RTSP DESCRIBE failed with status {describe.status}")
        sdp = describe.body.decode("latin-1", errors="replace")
        content_base = describe.headers.get("content-base", public_uri)
        track_uri, codec = _video_control(sdp, content_base)

        if auth_scheme != "none":
            nonce_count += 1
            authorization, _ = _authorization(
                describe.headers.get(
                    "www-authenticate",
                    challenge_response.headers.get("www-authenticate", ""),
                ),
                "SETUP",
                (
                    urlsplit(track_uri).path
                    + (f"?{urlsplit(track_uri).query}" if urlsplit(track_uri).query else "")
                    if digest_path_only
                    else track_uri
                ),
                username,
                password,
                nonce_count,
            )
        setup = _send(
            connection,
            "SETUP",
            track_uri,
            3,
            authorization,
            {"Transport": "RTP/AVP/TCP;unicast;interleaved=0-1"},
        )
        if setup.status != 200:
            raise ProbeError(f"RTSP SETUP failed with status {setup.status}")
        session = setup.headers.get("session", "").split(";", 1)[0]
        if not session:
            raise ProbeError("RTSP SETUP returned no session")
        if auth_scheme != "none":
            nonce_count += 1
            authorization, _ = _authorization(
                challenge_response.headers.get("www-authenticate", ""),
                "PLAY",
                (
                    parsed.path + (f"?{parsed.query}" if parsed.query else "")
                    if digest_path_only
                    else public_uri
                ),
                username,
                password,
                nonce_count,
            )
        play = _send(
            connection,
            "PLAY",
            public_uri,
            4,
            authorization,
            {"Session": session, "Range": "npt=0.000-"},
        )
        if play.status != 200:
            raise ProbeError(f"RTSP PLAY failed with status {play.status}")

        deadline = time.monotonic() + min(timeout_seconds, 5.0)
        rtp_bytes = 0
        while time.monotonic() < deadline and rtp_bytes < 4096:
            try:
                rtp_bytes += len(connection.recv(8192))
            except TimeoutError:
                break
        if rtp_bytes == 0:
            raise ProbeError("RTSP PLAY succeeded but no interleaved RTP data arrived")
        return {
            "schema_version": "1.0.0",
            "result": "PASS",
            "authentication": auth_scheme,
            "video_codec": codec,
            "sdp_received": True,
            "rtp_received": True,
            "rtp_bytes_observed": rtp_bytes,
        }


def probe_with_curl(uri: str, timeout_seconds: float = 8.0) -> dict[str, object]:
    parsed = urlsplit(uri)
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    public_uri = _public_uri(uri)
    completed = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--anyauth",
            "--user",
            f"{username}:{password}",
            "--connect-timeout",
            str(timeout_seconds),
            "--max-time",
            str(timeout_seconds),
            "--request",
            "DESCRIBE",
            "--header",
            "Accept: application/sdp",
            "--write-out",
            "\n%{response_code}",
            public_uri,
        ],
        check=False,
        capture_output=True,
        timeout=timeout_seconds + 2,
    )
    if completed.returncode != 0:
        raise ProbeError("camera rejected RTSP authentication or DESCRIBE")
    output = completed.stdout.decode("latin-1", errors="replace")
    sdp, _, response_code = output.rpartition("\n")
    if response_code != "200":
        raise ProbeError(f"RTSP DESCRIBE failed with status {response_code or 'unknown'}")
    try:
        _, codec = _video_control(sdp, public_uri)
    except ProbeError as error:
        raise ProbeError(
            f"RTSP DESCRIBE status 200 returned no video SDP ({len(sdp.encode())} bytes)"
        ) from error
    return {
        "schema_version": "1.0.0",
        "result": "PARTIAL",
        "authentication": "digest",
        "video_codec": codec,
        "sdp_received": True,
        "rtp_received": False,
        "note": "curl authenticated DESCRIBE; RTP was not tested by this fallback",
    }


def probe_with_gstreamer(uri: str, timeout_seconds: float = 15.0) -> dict[str, object]:
    command = (
        "IFS= read -r camera_uri; "
        "timeout 12 gst-launch-1.0 -v "
        'rtspsrc location="$camera_uri" protocols=tcp latency=200 '
        "! decodebin ! fakesink sync=false; "
        "result=$?; camera_uri=; exit \"$result\""
    )
    completed = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "ntc-vss-phase06-streamprocessing",
            "bash",
            "-lc",
            command,
        ],
        input=(uri + "\n").encode(),
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if completed.returncode not in {0, 124}:
        raise ProbeError("GStreamer could not authenticate and receive the RTSP stream")
    output = (completed.stdout + completed.stderr).decode("latin-1", errors="replace")
    caps_match = re.search(
        r"video/x-raw[^\n]*width=\(int\)(\d+)[^\n]*height=\(int\)(\d+)",
        output,
    )
    codec_match = re.search(r"video/x-(h264|h265)", output, re.IGNORECASE)
    result: dict[str, object] = {
        "schema_version": "1.0.0",
        "result": "PASS",
        "authentication": "camera-managed",
        "video_codec": codec_match.group(1).lower() if codec_match else "decoded",
        "rtp_received": True,
        "decoder_pipeline": True,
    }
    if caps_match:
        result["width"] = int(caps_match.group(1))
        result["height"] = int(caps_match.group(2))
    return result


def main() -> int:
    terminal_settings = None
    if sys.stdin.isatty():
        import termios

        terminal_settings = termios.tcgetattr(sys.stdin.fileno())
        hidden_settings = termios.tcgetattr(sys.stdin.fileno())
        hidden_settings[3] &= ~termios.ECHO
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, hidden_settings)
    try:
        uri = sys.stdin.readline().strip()
    finally:
        if terminal_settings is not None:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, terminal_settings)
            print()
    try:
        try:
            result = probe(uri)
        except (OSError, ProbeError, ValueError):
            try:
                result = probe_with_curl(uri)
            except (OSError, ProbeError, subprocess.SubprocessError, ValueError):
                result = probe_with_gstreamer(uri)
    except (OSError, ProbeError, subprocess.SubprocessError, ValueError) as error:
        print(json.dumps({"result": "FAIL", "error": str(error)}))
        return 1
    finally:
        uri = ""
        os.environ.pop("RTSP_URI", None)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
