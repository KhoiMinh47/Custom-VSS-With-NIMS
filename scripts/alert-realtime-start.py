from __future__ import annotations

import os
from pathlib import Path


runtime = Path("/app/runtime")
source = Path("/app/configs/config.yml").read_text(encoding="utf-8")
redis_port = os.environ.get("ALERT_REDIS_PORT", "6380")
source = source.replace("elastic:\n  enabled: true", "elastic:\n  enabled: false")
source = source.replace(
    "persistence:\n  enabled: true",
    "persistence:\n  enabled: false",
)
source = source.replace('type: "elastic"', 'type: "kafka"')
source = source.replace(
    "vlm_enhanced_sink:\n",
    'vlm_enhanced_sink:\n  type: "kafka"\n',
    1,
)
runtime.joinpath("source-config.yml").write_text(
    source.replace("localhost", "127.0.0.1").replace(
        "port: 6379", f"port: {redis_port}"
    ),
    encoding="utf-8",
)

os.execv(
    "/usr/local/bin/python",
    [
        "/usr/local/bin/python",
        "/app/env-substitute.py",
        "--source",
        "/app/runtime/source-config.yml",
        "--output",
        "/app/runtime/config.yml",
        "--",
        "/usr/local/bin/python",
        "enhance_alert_with_vlm.py",
        "--config",
        "/app/runtime/config.yml",
    ],
)
