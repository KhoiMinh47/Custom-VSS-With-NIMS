from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from contracts import event_document, line_side, parse_utc, point_in_polygon, validate_config
from heatmap import HeatmapGrid


@dataclass
class TrackState:
    last_seen: datetime
    point: tuple[float, float]
    zones: set[str] = field(default_factory=set)
    zone_entered: dict[str, datetime] = field(default_factory=dict)
    dwell_emitted: set[str] = field(default_factory=set)
    line_side: float | None = None


class BehaviorEngine:
    def __init__(self, config: dict[str, Any]) -> None:
        validate_config(config)
        self.config = config
        heatmap = config["heatmap"]
        self.heatmap = HeatmapGrid(int(heatmap["columns"]), int(heatmap["rows"]))
        self.tracks: dict[str, TrackState] = {}
        self.processed_frames: deque[str] = deque(maxlen=2000)
        self.processed_frame_set: set[str] = set()
        self.last_frame_timestamp: str | None = None
        self.last_frame_time: datetime | None = None
        self.last_heatmap_emit: datetime | None = None
        self.frames = 0
        self.events = 0
        self.entry_count = 0
        self.exit_count = 0
        self.queue_active = False
        self.recent_events: deque[dict[str, Any]] = deque(maxlen=200)

    def _emit(
        self,
        frame: dict[str, Any],
        event_type: str,
        timestamp: datetime,
        *,
        track_ids: list[str] | None = None,
        rule_id: str,
        payload: dict[str, Any] | None = None,
        candidate: bool = False,
    ) -> dict[str, Any]:
        event = event_document(
            self.config,
            frame,
            event_type,
            timestamp,
            track_ids=track_ids,
            rule_id=rule_id,
            payload=payload,
            candidate=candidate,
        )
        self.events += 1
        self.recent_events.appendleft(event)
        return event

    def _remember_frame(self, frame_id: str) -> bool:
        if frame_id in self.processed_frame_set:
            return False
        if len(self.processed_frames) == self.processed_frames.maxlen:
            self.processed_frame_set.discard(self.processed_frames[0])
        self.processed_frames.append(frame_id)
        self.processed_frame_set.add(frame_id)
        return True

    def process_frame(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        if frame.get("store_id") != self.config["store_id"]:
            return []
        if frame.get("camera_id") != self.config["camera_id"]:
            return []
        frame_id = str(frame.get("payload", {}).get("frame_id", ""))
        if not frame_id or not self._remember_frame(frame_id):
            return []
        timestamp = parse_utc(str(frame["@timestamp"]))
        self.last_frame_timestamp = str(frame["@timestamp"])
        self.last_frame_time = timestamp
        self.frames += 1
        events: list[dict[str, Any]] = []
        current_ids: set[str] = set()
        allowed = {
            str(value).lower()
            for value in self.config.get("object_types", ["Person"])
        }
        zones = {str(zone["id"]): zone for zone in self.config.get("zones", [])}
        line = self.config["people_counting"]["line"]
        line_start = tuple(float(value) for value in line["start"])
        line_end = tuple(float(value) for value in line["end"])
        deadband = float(line.get("deadband", 0.02))

        for detected in frame.get("payload", {}).get("objects", []):
            track_id = str(detected.get("track_id", ""))
            if not track_id or str(detected.get("type", "")).lower() not in allowed:
                continue
            bbox = detected.get("bbox", {})
            point = (
                (float(bbox.get("left", 0)) + float(bbox.get("right", 0))) / 2,
                float(bbox.get("bottom", 0)),
            )
            current_ids.add(track_id)
            self.heatmap.add(*point)
            track = self.tracks.get(track_id)
            if track is None:
                track = TrackState(timestamp, point)
                self.tracks[track_id] = track

            current_zones = {
                zone_id
                for zone_id, zone in zones.items()
                if point_in_polygon(point, zone["polygon"])
            }
            for zone_id in current_zones - track.zones:
                zone = zones[zone_id]
                track.zone_entered[zone_id] = timestamp
                events.append(
                    self._emit(
                        frame,
                        "roi.entry",
                        timestamp,
                        track_ids=[track_id],
                        rule_id=zone_id,
                        payload={"zone_id": zone_id, "zone_type": zone["type"]},
                    )
                )
                if zone["type"] == "restricted":
                    events.append(
                        self._emit(
                            frame,
                            "restricted_zone.entry",
                            timestamp,
                            track_ids=[track_id],
                            rule_id=zone_id,
                            payload={"zone_id": zone_id},
                            candidate=True,
                        )
                    )
            for zone_id in track.zones - current_zones:
                zone = zones[zone_id]
                entered = track.zone_entered.pop(zone_id, timestamp)
                dwell_seconds = max(0.0, (timestamp - entered).total_seconds())
                track.dwell_emitted.discard(zone_id)
                events.append(
                    self._emit(
                        frame,
                        "roi.exit",
                        timestamp,
                        track_ids=[track_id],
                        rule_id=zone_id,
                        payload={
                            "zone_id": zone_id,
                            "zone_type": zone["type"],
                            "dwell_seconds": round(dwell_seconds, 3),
                        },
                    )
                )
            for zone_id in current_zones:
                zone = zones[zone_id]
                threshold = float(zone.get("dwell_threshold_seconds", 0))
                entered = track.zone_entered.get(zone_id, timestamp)
                dwell_seconds = max(0.0, (timestamp - entered).total_seconds())
                if (
                    threshold > 0
                    and dwell_seconds >= threshold
                    and zone_id not in track.dwell_emitted
                ):
                    track.dwell_emitted.add(zone_id)
                    events.append(
                        self._emit(
                            frame,
                            "dwell.threshold",
                            timestamp,
                            track_ids=[track_id],
                            rule_id=zone_id,
                            payload={
                                "zone_id": zone_id,
                                "dwell_seconds": round(dwell_seconds, 3),
                                "threshold_seconds": threshold,
                            },
                            candidate=True,
                        )
                    )

            side = line_side(point, line_start, line_end)
            if (
                track.line_side is not None
                and abs(track.line_side) > deadband
                and abs(side) > deadband
                and track.line_side * side < 0
            ):
                direction = (
                    "negative_to_positive" if track.line_side < side else "positive_to_negative"
                )
                count_type = line["directions"][direction]
                if count_type == "entry":
                    self.entry_count += 1
                else:
                    self.exit_count += 1
                common = {
                    "line_id": line["id"],
                    "direction": direction,
                    "count_type": count_type,
                    "entry_count": self.entry_count,
                    "exit_count": self.exit_count,
                }
                events.append(
                    self._emit(
                        frame,
                        "line_crossing",
                        timestamp,
                        track_ids=[track_id],
                        rule_id=str(line["id"]),
                        payload=common,
                    )
                )
                events.append(
                    self._emit(
                        frame,
                        f"people_count.{count_type}",
                        timestamp,
                        track_ids=[track_id],
                        rule_id=str(line["id"]),
                        payload=common,
                    )
                )
            track.line_side = side
            track.point = point
            track.zones = current_zones
            track.last_seen = timestamp

        ttl = float(self.config.get("tracking", {}).get("ttl_seconds", 5))
        for track_id, track in list(self.tracks.items()):
            if (timestamp - track.last_seen).total_seconds() > ttl:
                del self.tracks[track_id]

        queue = self.config["queue"]
        queue_zone = str(queue["zone_id"])
        queue_tracks = [
            track_id for track_id, track in self.tracks.items() if queue_zone in track.zones
        ]
        queue_wait = max(
            (
                (self.last_frame_time - self.tracks[track_id].zone_entered[queue_zone])
                .total_seconds()
                for track_id in queue_tracks
                if self.last_frame_time is not None
            ),
            default=0.0,
        )
        waits = [
            max(
                0.0,
                (timestamp - self.tracks[track_id].zone_entered[queue_zone]).total_seconds(),
            )
            for track_id in queue_tracks
        ]
        threshold = int(queue["length_threshold"])
        now_active = len(queue_tracks) >= threshold
        if now_active != self.queue_active:
            event_type = "queue.threshold" if now_active else "queue.cleared"
            events.append(
                self._emit(
                    frame,
                    event_type,
                    timestamp,
                    track_ids=queue_tracks,
                    rule_id=str(queue["id"]),
                    payload={
                        "zone_id": queue_zone,
                        "queue_length": len(queue_tracks),
                        "estimated_wait_seconds": round(max(waits, default=0.0), 3),
                        "threshold": threshold,
                    },
                    candidate=now_active,
                )
            )
            self.queue_active = now_active

        interval = float(self.config["heatmap"]["emit_interval_seconds"])
        if self.last_heatmap_emit is None:
            self.last_heatmap_emit = timestamp
        elif (timestamp - self.last_heatmap_emit).total_seconds() >= interval:
            self.last_heatmap_emit = timestamp
            events.append(
                self._emit(
                    frame,
                    "heatmap.snapshot",
                    timestamp,
                    rule_id=str(self.config["heatmap"]["id"]),
                    payload=self.heatmap.snapshot(),
                )
            )
        return events

    def snapshot(self) -> dict[str, Any]:
        queue_zone = str(self.config["queue"]["zone_id"])
        queue_tracks = [
            track_id for track_id, track in self.tracks.items() if queue_zone in track.zones
        ]
        queue_wait = max(
            (
                (self.last_frame_time - self.tracks[track_id].zone_entered[queue_zone])
                .total_seconds()
                for track_id in queue_tracks
                if self.last_frame_time is not None
            ),
            default=0.0,
        )
        occupancy = {
            str(zone["id"]): sum(
                str(zone["id"]) in track.zones for track in self.tracks.values()
            )
            for zone in self.config.get("zones", [])
        }
        return {
            "schema_version": self.config["schema_version"],
            "store_id": self.config["store_id"],
            "camera_id": self.config["camera_id"],
            "config_version": int(self.config["config_version"]),
            "calibration_status": self.config.get("calibration_status", "unknown"),
            "frames_processed": self.frames,
            "events_emitted": self.events,
            "last_frame_timestamp_utc": self.last_frame_timestamp,
            "active_tracks": len(self.tracks),
            "entry_count": self.entry_count,
            "exit_count": self.exit_count,
            "occupancy": occupancy,
            "queue_length": len(queue_tracks),
            "estimated_queue_wait_seconds": round(max(0.0, queue_wait), 3),
            "heatmap": self.heatmap.snapshot(),
            "recent_events": list(self.recent_events),
        }
