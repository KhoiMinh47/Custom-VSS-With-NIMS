from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from vios_client import ViosClient


INGRESS = "http://127.0.0.1:30888/vst"
NVSTREAMER = "http://127.0.0.1:31000"
STREAMPROCESSOR = "http://127.0.0.1:30001"


def _get_json(url: str) -> Any:
    with urlopen(url, timeout=30) as response:
        return json.load(response)


def _download(url: str, query: dict[str, str], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(f"{url}?{urlencode(query)}", timeout=60) as response:
        destination.write_bytes(response.read())


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc:
        raise RuntimeError(f"timeline timestamp is not UTC: {value}")
    return parsed


def main() -> int:
    source_streams = ViosClient(NVSTREAMER).streams()
    target_streams = ViosClient(INGRESS).streams()
    statuses = ViosClient(INGRESS).statuses()
    proxies = ViosClient(STREAMPROCESSOR).proxy_streams()
    if len(source_streams) != 10 or len(target_streams) != 10:
        raise RuntimeError(
            f"expected 10 source/target streams, got {len(source_streams)}/{len(target_streams)}"
        )
    online = [
        value
        for value in statuses.values()
        if isinstance(value, dict) and value.get("state") == "online"
    ]
    if len(online) != 10:
        raise RuntimeError(f"expected 10 online streams, got {len(online)}")
    live_proxies = [item for item in proxies if item.get("proxyUrl")]
    if len(live_proxies) != 10:
        raise RuntimeError(f"expected 10 live proxies, got {len(live_proxies)}")

    by_name = {str(stream.get("name")): stream for stream in target_streams}
    timelines_by_name: dict[str, list[dict[str, str]]] = {}
    for name, stream in by_name.items():
        stream_id = str(stream["streamId"])
        stream_timelines = _get_json(
            f"{INGRESS}/api/v1/storage/{stream_id}/timelines"
        )
        if not stream_timelines:
            raise RuntimeError(f"{name} has no recording timeline")
        _parse_utc(stream_timelines[0]["startTime"])
        _parse_utc(stream_timelines[0]["endTime"])
        timelines_by_name[name] = stream_timelines
    if len(timelines_by_name) != 10:
        raise RuntimeError(
            f"expected recording timelines for 10 streams, got {len(timelines_by_name)}"
        )

    cam01 = by_name["cam-01"]
    stream_id = str(cam01["streamId"])
    timelines = timelines_by_name["cam-01"]
    latest_timeline = timelines[-1]
    for _ in range(15):
        duration = (
            _parse_utc(latest_timeline["endTime"])
            - _parse_utc(latest_timeline["startTime"])
        ).total_seconds()
        if duration >= 15:
            break
        time.sleep(2)
        timelines = _get_json(f"{INGRESS}/api/v1/storage/{stream_id}/timelines")
        latest_timeline = timelines[-1]
    timeline_start = _parse_utc(latest_timeline["startTime"])
    timeline_end = _parse_utc(latest_timeline["endTime"])
    end = timeline_end
    start = max(timeline_start, end - timedelta(seconds=10))
    if (end - start).total_seconds() < 2:
        raise RuntimeError("recording timeline is too short for media probes")
    timestamp = start.strftime("%Y%m%dT%H%M%SZ")
    iso_start = start.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    iso_end = end.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    snapshot = Path(f"runtime/snapshots/phase06-cam-01-{timestamp}.jpg")
    clip = Path(f"runtime/clips/phase06-cam-01-{timestamp}.mp4")
    _download(
        f"{INGRESS}/api/v1/storage/stream/{stream_id}/picture",
        {"startTime": iso_start, "width": "640", "height": "360"},
        snapshot,
    )
    _download(
        f"{INGRESS}/api/v1/storage/file/{stream_id}",
        {
            "startTime": iso_start,
            "endTime": iso_end,
            "container": "mp4",
            "transcode": "none",
        },
        clip,
    )
    if not snapshot.read_bytes().startswith(b"\xff\xd8\xff"):
        raise RuntimeError("picture API did not return JPEG")
    if b"ftyp" not in clip.read_bytes()[:32]:
        raise RuntimeError("clip API did not return MP4")

    print(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "sources": len(source_streams),
                "online": len(online),
                "live_proxies": len(live_proxies),
                "recording_timelines": len(timelines_by_name),
                "timeline_start_utc": latest_timeline["startTime"],
                "timeline_end_utc": latest_timeline["endTime"],
                "snapshot": str(snapshot),
                "snapshot_bytes": snapshot.stat().st_size,
                "clip": str(clip),
                "clip_bytes": clip.stat().st_size,
                "result": "PASS",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
