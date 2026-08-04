from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.request import Request, urlopen


SEARCH = "http://127.0.0.1:39310"
ES = "http://127.0.0.1:9200"
VIDEO_IDS = [
    "ba71b8136dab1a4067732b041ec5452febe235e2e17fd6b24c6e91383671876b",
    "a5fea5fc6bf3a728f28d251f179c461f31e0f41798096b3975f1ff0d7a845370",
    "a67fd0907af787e1f30921fdd63d4dc137d070e7d0af335103b7cc87d5030745",
]
SNAPSHOT_URI = "selected-snapshot://phase06-cam-01-20260728T092138Z.jpg"
SNAPSHOT_ASSET = "phase06-cam-01-20260728T092138Z"


def request(url: str, payload: dict[str, Any] | None = None) -> Any:
    value = Request(
        url,
        data=None if payload is None else json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urlopen(value, timeout=360) as response:
        return json.load(response)


def videos() -> list[dict[str, Any]]:
    results = []
    for incident_id in VIDEO_IDS:
        incident = request(f"{ES}/mdx-incidents/_doc/{incident_id}")["_source"]
        result = request(
            f"{SEARCH}/api/v1/index/video",
            {
                "asset_id": incident_id,
                "asset_uri": incident["asset_uri"],
                "camera_id": incident["camera_id"],
                "creation_time": incident["clip_start_time"],
                "event_type": incident["event_type"],
            },
        )
        results.append(result)
    for query in (
        "person entering a restricted area",
        "people waiting in a queue",
        "person sitting at a desk wearing a white shirt",
    ):
        request(
            f"{SEARCH}/api/v1/search",
            {"query": query, "route": "action", "top_k": 3},
        )
    return results


def objects() -> list[dict[str, Any]]:
    annotations = [
        {
            "object_id": "person-left-door",
            "track_id": "snapshot-person-1",
            "object_class": "Person",
            "bbox": [0.0, 0.125, 0.13, 0.79],
        },
        {
            "object_id": "person-center-tan-shirt",
            "track_id": "snapshot-person-2",
            "object_class": "Person",
            "bbox": [0.51, 0.19, 0.11, 0.31],
        },
        {
            "object_id": "person-right-white-shirt",
            "track_id": "snapshot-person-3",
            "object_class": "Person",
            "bbox": [0.566, 0.233, 0.11, 0.31],
        },
    ]
    results = []
    for annotation in annotations:
        results.append(
            request(
                f"{SEARCH}/api/v1/index/object",
                {
                    "asset_id": SNAPSHOT_ASSET,
                    "asset_uri": SNAPSHOT_URI,
                    "camera_id": "cam-01",
                    "frame_time": "2026-07-28T09:21:37Z",
                    "image_width": 640,
                    "image_height": 360,
                    **annotation,
                },
            )
        )
    for query in (
        "person wearing a white shirt",
        "person sitting at a desk wearing a white shirt",
    ):
        request(
            f"{SEARCH}/api/v1/search",
            {"query": query, "route": "attribute", "top_k": 3},
        )
    request(
        f"{SEARCH}/api/v1/search/image",
        {
            "asset_uri": SNAPSHOT_URI,
            "image_width": 640,
            "image_height": 360,
            "top_k": 3,
        },
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("channel", choices=("video", "object"))
    args = parser.parse_args()
    value = videos() if args.channel == "video" else objects()
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
