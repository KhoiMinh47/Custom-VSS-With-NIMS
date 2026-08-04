from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def render(source_root: Path, target: Path) -> None:
    upstream = source_root / "deploy/docker/services/vios/configs"
    nv_upstream = (
        source_root
        / "services/vios/deployment/stream-processing/docker-compose/nvstreamer/configs"
    )
    target.mkdir(parents=True, exist_ok=True)

    vios = json.loads((upstream / "vst_config.json").read_text(encoding="utf-8"))
    vios["network"]["ntp_servers"] = []
    vios["network"]["use_sensor_ntp_time"] = True
    vios["data"]["always_recording"] = True
    vios["data"]["restore_rtsp_streams_on_startup"] = True
    vios["data"]["default_file_expiry_minutes"] = 10080
    vios["notifications"]["enable_notification"] = False
    vios["notifications"]["enable_notification_consumer"] = False
    vios["notifications"]["redis_server_env_var"] = "127.0.0.1:16379"
    vios["notifications"]["kafka_server_address"] = "127.0.0.1:9092"
    vios["debug"]["enable_prometheus"] = True
    vios["debug"]["prometheus_port"] = "18080"
    vios["security"]["use_https"] = False
    (target / "vst_config.json").write_text(
        json.dumps(vios, indent=2) + "\n", encoding="utf-8"
    )

    nvstreamer = json.loads((nv_upstream / "vst_config.json").read_text(encoding="utf-8"))
    nvstreamer["network"]["ntp_servers"] = []
    nvstreamer["network"]["use_sensor_ntp_time"] = False
    nvstreamer["data"]["nv_streamer_loop_playback"] = True
    nvstreamer["data"]["always_recording"] = False
    nvstreamer["notifications"]["enable_notification"] = False
    nvstreamer["notifications"]["enable_notification_consumer"] = False
    (target / "nvstreamer-vst-config.json").write_text(
        json.dumps(nvstreamer, indent=2) + "\n", encoding="utf-8"
    )

    shutil.copy2(upstream / "vst_storage.json", target / "vst-storage.json")
    shutil.copy2(upstream / "nginx-vst-direct.conf", target / "nginx-vst-direct.conf")
    shutil.copy2(upstream / "adaptor_config.json", target / "adaptor_config.json")
    shutil.copy2(upstream / "rtsp_streams.json", target / "rtsp_streams.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("third_party/video-search-and-summarization"),
    )
    parser.add_argument("--target", type=Path, default=Path("runtime/vios/config"))
    args = parser.parse_args()
    render(args.source_root, args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
