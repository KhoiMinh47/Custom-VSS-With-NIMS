from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:30888/vst/api/v1/sensor/streams",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/phase06-live-streams.m3u"),
    )
    args = parser.parse_args()
    with urlopen(args.url, timeout=15) as response:
        wrappers = json.load(response)
    streams = [
        stream
        for wrapper in wrappers
        for values in wrapper.values()
        for stream in values
        if isinstance(stream, dict) and stream.get("name") and stream.get("url")
    ]
    streams.sort(key=lambda item: str(item["name"]))
    lines = ["#EXTM3U"]
    for stream in streams:
        lines.extend((f"#EXTINF:-1,{stream['name']}", str(stream["url"])))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"playlist={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
