from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:39200"


def request(method: str, path: str, value: dict | None = None) -> dict:
    payload = None if value is None else json.dumps(value, separators=(",", ":")).encode()
    call = Request(
        f"{BASE_URL}{path}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(call, timeout=300) as response:
        body = response.read()
    return json.loads(body) if body else {}


def register() -> None:
    config = json.loads(
        (ROOT / "config/prompts/rt-vlm-alert/person-presence.json").read_text(
            encoding="utf-8"
        )
    )
    current = request("GET", "/v1/stream/get-stream-info")
    if any(item.get("camera_id") == "cam-01" for item in current.get("stream_list", [])):
        print("phase11_stream=already_registered")
        return
    value = {
        "key": "sensor",
        "value": {
            "camera_id": "cam-01",
            "camera_name": "cam-01-direct-rt-vlm",
            "camera_url": "rtsp://rtsp-relay:39554/Streaming/Channels/102",
            "change": "camera_add",
            "metadata": {
                "resolution": "1280x720",
                "codec": "H264",
                "framerate": 25,
                "prompt": config["prompt"],
                "system_prompt": config["system_prompt"],
                "model": config["model_id"],
                "max_tokens": 512,
                "temperature": 0.2,
                "chunk_duration": config["chunk_duration_seconds"],
                "chunk_overlap_duration": config["chunk_overlap_seconds"],
                "num_frames_per_second_or_fixed_frames_chunk": config[
                    "frame_sampling"
                ]["frames"],
                "use_fps_for_chunking": False,
                "vlm_input_width": 1280,
                "vlm_input_height": 720,
                "enable_reasoning": False,
                "alert_category": config["use_case_id"],
                "response_format_type": config["response_format"],
            },
        },
        "headers": {
            "source": "ntc-phase11-direct",
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    }
    result = request("POST", "/v1/stream/add", value)
    if result.get("camera_id") != "cam-01" or not result.get("inference"):
        raise RuntimeError("RT-VLM did not start direct inference")
    print(
        f'phase11_stream=registered asset_id={result["asset_id"]} '
        f'status={result["status"]}'
    )


def unregister() -> None:
    value = {
        "key": "sensor",
        "value": {"camera_id": "cam-01", "change": "camera_remove"},
    }
    try:
        result = request("POST", "/v1/stream/remove", value)
        print(f'phase11_stream=removed asset_id={result["asset_id"]}')
    except HTTPError as error:
        if error.code != 404:
            raise
        print("phase11_stream=absent")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "unregister"))
    args = parser.parse_args()
    if args.action == "register":
        register()
    else:
        unregister()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
