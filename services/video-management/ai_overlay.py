from __future__ import annotations

import copy
import json
import threading
import time
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.request import urlopen

SCHEMA_VERSION = "1.0.0"
STORE_ID = "store-001"
CAMERA_ID = "cam-01"
DEFAULT_STALE_AFTER_SECONDS = 10.0
DEFAULT_BBOX_GRACE_SECONDS = 5.0
DEFAULT_REQUEST_RETRIES = 3
DEFAULT_REQUEST_TIMEOUT_SECONDS = 0.75


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def normalized_bbox_pixels(
    bbox: dict[str, Any], width: float, height: float
) -> tuple[float, float, float, float]:
    left = clamp(float(bbox.get("left", 0.0)))
    top = clamp(float(bbox.get("top", 0.0)))
    right = clamp(float(bbox.get("right", 0.0)))
    bottom = clamp(float(bbox.get("bottom", 0.0)))
    return (
        left * width,
        top * height,
        max(0.0, right - left) * width,
        max(0.0, bottom - top) * height,
    )


def disconnected_state(
    *,
    status: str = "unavailable",
    message: str = "RT-CV unavailable - live video remains available",
    consecutive_failures: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "camera_id": CAMERA_ID,
        "server_timestamp_utc": utc_now(),
        "metadata_timestamp_utc": None,
        "metadata_age_seconds": -1,
        "metadata_fresh": False,
        "metrics_degraded": False,
        "ai_connected": status != "unavailable",
        "ai_status": status,
        "status_message": message,
        "consecutive_failures": consecutive_failures,
        "source_fps": None,
        "frame_counter": None,
        "line_crossings_total": 0,
        "line_crossing_indicator": False,
        "objects": [],
    }


def _stream_metrics(vendor_metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(vendor_metrics, dict):
        return None
    streams = vendor_metrics.get("metrics-info", {}).get("stream-stats", [])
    return next(
        (
            value
            for value in streams
            if isinstance(value, dict) and value.get("sensor_id") == CAMERA_ID
        ),
        None,
    )


def _frame_counter(frame: dict[str, Any], stream: dict[str, Any] | None) -> int | None:
    if stream is not None:
        try:
            return int(stream.get("frame_number", 0))
        except (TypeError, ValueError):
            pass
    try:
        return int(frame["frame_id"])
    except (KeyError, TypeError, ValueError):
        return None


def public_ai_state(
    metadata: dict[str, Any],
    vendor_metrics: dict[str, Any] | None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    bbox_grace_seconds: float = DEFAULT_BBOX_GRACE_SECONDS,
) -> dict[str, Any]:
    if not metadata.get("ready"):
        return disconnected_state()

    stream = _stream_metrics(vendor_metrics)
    try:
        age = float(metadata.get("last_message_age_seconds", -1))
    except (TypeError, ValueError):
        age = -1
    frame = metadata.get("last_frame")
    if not isinstance(frame, dict):
        frame = {}
    objects = frame.get("objects", [])
    if not isinstance(objects, list):
        objects = []

    has_frame = bool(frame)
    metadata_fresh = has_frame and 0 <= age <= stale_after_seconds
    boxes_in_grace = has_frame and 0 <= age <= bbox_grace_seconds
    public_objects: list[dict[str, Any]] = []
    if boxes_in_grace:
        for detected in objects:
            if not isinstance(detected, dict):
                continue
            bbox = detected.get("bbox")
            if not isinstance(bbox, dict):
                continue
            public_objects.append(
                {
                    "class": str(detected.get("type", "Object"))[:64],
                    "confidence": clamp(float(detected.get("confidence", 0.0))),
                    "track_id": str(detected.get("track_id", ""))[:128],
                    "bbox": {
                        "left": clamp(float(bbox.get("left", 0.0))),
                        "top": clamp(float(bbox.get("top", 0.0))),
                        "right": clamp(float(bbox.get("right", 0.0))),
                        "bottom": clamp(float(bbox.get("bottom", 0.0))),
                    },
                }
            )

    stream_active = False
    if stream is not None:
        try:
            stream_active = (
                float(stream.get("fps", 0.0)) > 0
                and int(stream.get("frame_number", -1)) >= 0
            )
        except (TypeError, ValueError):
            stream_active = False

    # RT-CV metadata is object-driven: an empty scene may produce no new
    # metadata while the vendor frame counter continues to advance normally.
    if stream_active:
        status = "connected"
        message = "AI connected"
    elif not has_frame:
        status = "waiting_for_metadata"
        message = "waiting for AI metadata"
    elif boxes_in_grace:
        status = "connected"
        message = "AI connected"
    else:
        status = "metadata_delayed"
        message = "AI metadata delayed"

    crossings = max(0, int(metadata.get("line_crossings", 0)))
    fps: float | None = None
    if stream is not None:
        try:
            fps = round(float(stream.get("fps", 0.0)), 3)
        except (TypeError, ValueError):
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "store_id": STORE_ID,
        "camera_id": CAMERA_ID,
        "server_timestamp_utc": utc_now(),
        "metadata_timestamp_utc": frame.get("timestamp") if has_frame else None,
        "metadata_age_seconds": age,
        "metadata_fresh": metadata_fresh,
        "metrics_degraded": stream is None,
        "ai_connected": True,
        "ai_status": status,
        "status_message": message,
        "consecutive_failures": 0,
        "source_fps": fps,
        "frame_counter": _frame_counter(frame, stream),
        "line_crossings_total": crossings,
        "line_crossing_indicator": crossings > 0,
        "objects": public_objects,
    }


def _read_json(url: str, timeout: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("upstream response is not an object")
    return value


class AIStateResolver:
    """Fault-tolerant, credential-safe view of Phase 07 state for the browser."""

    def __init__(
        self,
        metadata_url: str,
        metrics_url: str,
        *,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        bbox_grace_seconds: float = DEFAULT_BBOX_GRACE_SECONDS,
        request_retries: int = DEFAULT_REQUEST_RETRIES,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        retry_delay_seconds: float = 0.05,
        fetch_json: Callable[[str, float], dict[str, Any]] = _read_json,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.metadata_url = metadata_url
        self.metrics_url = metrics_url
        self.stale_after_seconds = max(0.1, stale_after_seconds)
        self.bbox_grace_seconds = max(
            0.1, min(bbox_grace_seconds, self.stale_after_seconds)
        )
        self.request_retries = max(1, request_retries)
        self.request_timeout_seconds = max(0.1, request_timeout_seconds)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.fetch_json = fetch_json
        self.monotonic = monotonic
        self.sleep = sleep
        self._lock = threading.Lock()
        self._last_metrics: dict[str, Any] | None = None
        self._last_state: dict[str, Any] | None = None
        self._last_metadata_at: float | None = None
        self._last_objects: list[dict[str, Any]] = []
        self._last_objects_at: float | None = None
        self._consecutive_failures = 0

    def _fetch_with_retry(self, url: str) -> dict[str, Any]:
        for attempt in range(self.request_retries):
            try:
                return self.fetch_json(url, self.request_timeout_seconds)
            except Exception:
                if attempt + 1 < self.request_retries and self.retry_delay_seconds:
                    self.sleep(self.retry_delay_seconds)
        raise RuntimeError("upstream request failed")

    def _cached_objects(self, now: float) -> list[dict[str, Any]]:
        if (
            self._last_objects_at is not None
            and now - self._last_objects_at <= self.bbox_grace_seconds
        ):
            return copy.deepcopy(self._last_objects)
        return []

    def _failure_state(self, now: float) -> dict[str, Any]:
        self._consecutive_failures += 1
        unavailable = self._consecutive_failures >= 3
        if self._last_state is None:
            state = disconnected_state(
                status="unavailable" if unavailable else "reconnecting",
                message=(
                    "RT-CV unavailable - live video remains available"
                    if unavailable
                    else "AI reconnecting"
                ),
                consecutive_failures=self._consecutive_failures,
            )
        else:
            state = copy.deepcopy(self._last_state)
            state.update(
                {
                    "server_timestamp_utc": utc_now(),
                    "metadata_fresh": False,
                    "ai_connected": not unavailable,
                    "ai_status": "unavailable" if unavailable else "reconnecting",
                    "status_message": (
                        "RT-CV unavailable - live video remains available"
                        if unavailable
                        else "AI reconnecting"
                    ),
                    "consecutive_failures": self._consecutive_failures,
                    "objects": self._cached_objects(now),
                }
            )
            if self._last_metadata_at is not None:
                base_age = max(0.0, float(state.get("metadata_age_seconds", 0)))
                state["metadata_age_seconds"] = round(
                    base_age + now - self._last_metadata_at, 3
                )
        state["line_crossing_indicator"] = False
        return state

    def resolve(self) -> dict[str, Any]:
        # ThreadingHTTPServer may issue overlapping browser requests; serialize cache
        # mutation so the three-poll failure threshold is deterministic.
        with self._lock:
            now = self.monotonic()
            try:
                metadata = self._fetch_with_retry(self.metadata_url)
                if not metadata.get("ready"):
                    raise RuntimeError("metadata service is not ready")
            except Exception:
                return self._failure_state(now)

            metrics_degraded = False
            try:
                metrics = self._fetch_with_retry(self.metrics_url)
                self._last_metrics = metrics
            except Exception:
                metrics = self._last_metrics
                metrics_degraded = True

            state = public_ai_state(
                metadata,
                metrics,
                self.stale_after_seconds,
                self.bbox_grace_seconds,
            )
            state["metrics_degraded"] = metrics_degraded or state["metrics_degraded"]
            self._consecutive_failures = 0
            self._last_metadata_at = now
            self._last_state = copy.deepcopy(state)
            if state["objects"]:
                age = max(0.0, float(state["metadata_age_seconds"]))
                self._last_objects = copy.deepcopy(state["objects"])
                self._last_objects_at = now - age
            return state


def fetch_public_ai_state(
    metadata_url: str,
    metrics_url: str,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    """Compatibility helper for one-shot callers; the HTTP server reuses a resolver."""

    return AIStateResolver(
        metadata_url,
        metrics_url,
        stale_after_seconds=stale_after_seconds,
    ).resolve()


AI_OVERLAY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cam-01 live AI overlay</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:#070b11;color:#ecf2f8}
main{min-height:100vh;display:flex;flex-direction:column;padding:14px;gap:12px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
h1{font-size:18px;margin:0;font-weight:650}.meta{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:#17212c;border:1px solid #2c3a47;border-radius:999px;padding:6px 10px}
.ok{border-color:#1d9b68;color:#80f0bd}.wait{border-color:#bd8424;color:#ffd483}
.bad{border-color:#d04d57;color:#ff9da5}.cross{border-color:#dba52a;color:#ffdc7a}
#stage{position:relative;width:100%;max-width:1600px;aspect-ratio:16/9;margin:auto;
background:#101821;overflow:hidden;border:1px solid #263544;border-radius:10px}
#liveVideo,#aiOverlay{position:absolute;inset:0;width:100%;height:100%;display:block}
#liveVideo{object-fit:contain}#aiOverlay{pointer-events:none}
#videoWarning{position:absolute;inset:0;display:none;place-items:center;background:#111c;
font-size:20px;color:#ff9da5}
footer{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
font-size:13px;color:#9eb0c1}.legend{color:#79f2b5}
@media(max-width:640px){main{padding:8px}.chip{padding:5px 8px}h1{font-size:16px}}
</style>
</head>
<body>
<main>
<header>
  <h1>cam-01 · live video + RT-DETR/NvDCF</h1>
  <div class="meta">
    <span id="aiStatus" class="chip wait">connecting to AI…</span>
    <span id="fps" class="chip">FPS —</span>
    <span id="frame" class="chip">frame —</span>
    <span id="crossing" class="chip">line crossings 0</span>
  </div>
</header>
<section id="stage" aria-label="cam-01 live AI compositor">
  <img id="liveVideo" src="/mjpeg" alt="cam-01 live MJPEG stream">
  <canvas id="aiOverlay" aria-label="normalized AI bounding-box overlay"></canvas>
  <div id="videoWarning">live video unavailable</div>
</section>
<footer>
  <span id="timestamp">UTC metadata —</span>
  <span id="detections" class="legend">0 current detections</span>
</footer>
</main>
<script>
const video=document.getElementById("liveVideo");
const canvas=document.getElementById("aiOverlay");
const ctx=canvas.getContext("2d");
const stage=document.getElementById("stage");
const statusNode=document.getElementById("aiStatus");
const POLL_MS=400,STATE_TIMEOUT_MS=2500,BBOX_GRACE_MS=5000;
let latest=null,lastCrossings=0,frontendFailures=0,lastStateAt=0;
const clamp=v=>Math.max(0,Math.min(1,Number(v)||0));
function resize(){
  const rect=stage.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
  canvas.width=Math.max(1,Math.round(rect.width*dpr));
  canvas.height=Math.max(1,Math.round(rect.height*dpr));
  canvas.style.width=rect.width+"px";canvas.style.height=rect.height+"px";
  ctx.setTransform(dpr,0,0,dpr,0,0);draw();
}
function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight;
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle="#ffd24d";ctx.lineWidth=2;ctx.setLineDash([8,6]);
  ctx.beginPath();ctx.moveTo(.5*w,.05*h);ctx.lineTo(.5*w,.95*h);ctx.stroke();
  ctx.setLineDash([]);
  const objects=(latest&&latest.objects)||[];
  for(const obj of objects){
    const b=obj.bbox||{},x=clamp(b.left)*w,y=clamp(b.top)*h;
    const bw=Math.max(0,clamp(b.right)-clamp(b.left))*w;
    const bh=Math.max(0,clamp(b.bottom)-clamp(b.top))*h;
    ctx.strokeStyle="#58f5a6";ctx.lineWidth=Math.max(2,w/650);
    ctx.strokeRect(x,y,bw,bh);
    const label=`${obj.class||"Object"} · ${(100*clamp(obj.confidence)).toFixed(1)}% · #${obj.track_id||"—"}`;
    ctx.font=`600 ${Math.max(12,w/80)}px ui-sans-serif,system-ui`;
    const tw=ctx.measureText(label).width+12,th=Math.max(22,w/55);
    ctx.fillStyle="rgba(3,13,18,.86)";ctx.fillRect(x,Math.max(0,y-th),tw,th);
    ctx.fillStyle="#dfffee";ctx.fillText(label,x+6,Math.max(16,y-6));
  }
}
function render(state){
  latest=state;
  statusNode.textContent=state.status_message;
  const waiting=["reconnecting","metadata_delayed","waiting_for_metadata"].includes(state.ai_status);
  statusNode.className="chip "+(!state.ai_connected&&!waiting?"bad":waiting?"wait":"ok");
  document.getElementById("fps").textContent=`FPS ${state.source_fps??"—"}`;
  document.getElementById("frame").textContent=`frame ${state.frame_counter??"—"}`;
  const crossing=document.getElementById("crossing");
  crossing.textContent=`line crossings ${state.line_crossings_total||0}`;
  if((state.line_crossings_total||0)>lastCrossings) crossing.className="chip cross";
  else crossing.className="chip";
  lastCrossings=state.line_crossings_total||0;
  document.getElementById("timestamp").textContent=
    `UTC metadata ${state.metadata_timestamp_utc||state.server_timestamp_utc||"—"}`;
  document.getElementById("detections").textContent=
    `${(state.objects||[]).length} current detections`;
  draw();
}
async function fetchState(){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),STATE_TIMEOUT_MS);
  try{
    const response=await fetch("/api/ai-state",{cache:"no-store",signal:controller.signal});
    if(!response.ok) throw new Error("AI state unavailable");
    return await response.json();
  }finally{clearTimeout(timer)}
}
async function poll(){
  try{
    const state=await fetchState();
    frontendFailures=0;lastStateAt=Date.now();render(state);
  }catch(_error){
    frontendFailures+=1;
    const withinGrace=latest&&Date.now()-lastStateAt<=BBOX_GRACE_MS;
    const state={...(latest||{}),
      ai_connected:frontendFailures<3,
      metadata_fresh:false,
      ai_status:frontendFailures<3?"reconnecting":"unavailable",
      status_message:frontendFailures<3?"AI reconnecting":
        "RT-CV unavailable - live video remains available",
      objects:withinGrace?(latest.objects||[]):[],
      consecutive_failures:frontendFailures};
    render(state);
  }finally{setTimeout(poll,POLL_MS)}
}
video.addEventListener("error",()=>document.getElementById("videoWarning").style.display="grid");
video.addEventListener("load",()=>document.getElementById("videoWarning").style.display="none");
new ResizeObserver(resize).observe(stage);
poll();resize();
</script>
</body>
</html>
"""
