from __future__ import annotations

import socket
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener


def secret(socket_path: Path) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(socket_path))
        connection.sendall(b"GET\n")
        value = connection.recv(65536).decode().strip()
    if not value.startswith("rtsp://"):
        raise RuntimeError("secret agent returned no RTSP URI")
    return value


def main() -> int:
    socket_path = Path(sys.argv[1] if len(sys.argv) > 1 else "runtime/secrets/camera-secret.sock")
    uri = secret(socket_path)
    parsed = urlsplit(uri)
    base = f"http://{parsed.hostname}:80"
    manager = HTTPPasswordMgrWithDefaultRealm()
    manager.add_password(
        None,
        base,
        unquote(parsed.username or ""),
        unquote(parsed.password or ""),
    )
    opener = build_opener(HTTPDigestAuthHandler(manager))
    now = datetime.now().astimezone().replace(microsecond=0).isoformat()
    payload = f'''<?xml version="1.0" encoding="UTF-8"?>
<Time version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
<timeMode>manual</timeMode>
<localTime>{now}</localTime>
<timeZone>CST-7:00:00</timeZone>
</Time>'''.encode()
    request = Request(
        f"{base}/ISAPI/System/time",
        data=payload,
        headers={"Content-Type": "application/xml"},
        method="PUT",
    )
    with opener.open(request, timeout=10) as response:
        response.read()
        print(f"camera_clock_sync=PASS camera={parsed.hostname} local_time={now}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
