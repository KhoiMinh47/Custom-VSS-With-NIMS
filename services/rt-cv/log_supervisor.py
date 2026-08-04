from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from datetime import UTC, datetime

USERINFO = re.compile(r"(rtsp://)[^/@\s]+@", re.IGNORECASE)


def emit(message: str, level: str = "info") -> None:
    sanitized = USERINFO.sub(r"\1[REDACTED]@", message.rstrip())
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "level": level,
                "service": "phase07-rtcv",
                "message": sanitized,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def main() -> int:
    command = sys.argv[1:]
    if not command:
        emit("missing supervised command", "error")
        return 2
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    def forward(signum: int, _frame: object) -> None:
        if process.poll() is None:
            os.killpg(process.pid, signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    assert process.stdout is not None
    for line in process.stdout:
        lowered = line.lower()
        level = "error" if "error" in lowered or "failed" in lowered else "info"
        emit(line, level)
    return_code = process.wait()
    emit("supervised process exited", "info" if return_code == 0 else "error")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
