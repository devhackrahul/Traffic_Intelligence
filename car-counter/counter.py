"""YOLO + Supervision traffic analytics engine for government monitoring."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

from store import TrafficStore
from stream import StreamResolver

# COCO: person, bicycle, car, motorcycle, bus, truck
DETECT_CLASS_IDS = {0, 1, 2, 3, 5, 7}
CLASS_LABELS = {
    0: "pedestrian",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}
VEHICLE_IDS = {1, 2, 3, 5, 7}  # includes bicycle for detection overlays
ROAD_VEHICLE_IDS = {2, 3, 5, 7}  # counted in "total vehicles"
HEAVY_CLASS_IDS = {5, 7}
CLASS_MIN_CONF = {
    0: float(os.getenv("PED_CONFIDENCE", "0.30")),
    1: float(os.getenv("BIKE_CONFIDENCE", "0.25")),
    2: float(os.getenv("CAR_CONFIDENCE", "0.40")),
    3: float(os.getenv("MOTORCYCLE_CONFIDENCE", "0.20")),
    5: float(os.getenv("BUS_CONFIDENCE", "0.40")),
    7: float(os.getenv("TRUCK_CONFIDENCE", "0.35")),
}
MODEL_NAME = os.getenv("YOLO_MODEL", "yolo11n.pt")
QUEUE_Y_RATIO = float(os.getenv("QUEUE_Y_RATIO", "0.70"))
CONFIDENCE = float(os.getenv("DETECTION_CONFIDENCE", "0.20"))
INFER_IMGSZ = int(os.getenv("INFER_IMGSZ", "960"))
# Ignore parked / jittering objects inside the intersection
MIN_COUNT_SPEED_PX = float(os.getenv("MIN_COUNT_SPEED_PX", "1.2"))
MIN_TRACK_AGE = int(os.getenv("MIN_TRACK_AGE", "4"))
# Deduplicate tracker ID switches for the same physical vehicle
DEDUP_SECONDS = float(os.getenv("COUNT_DEDUP_SECONDS", "3.0"))
DEDUP_DISTANCE_PX = float(os.getenv("COUNT_DEDUP_DISTANCE_PX", "110"))
# Planning-grade motion bands (pixels per frame)
SPEED_SLOW = float(os.getenv("SPEED_SLOW_PX", "4"))
SPEED_FAST = float(os.getenv("SPEED_FAST_PX", "18"))
# Intersection count polygon (normalized x,y) — main road + left side-street mouth
# Tuned for ffm0 Fairview overhead cam looking down the corridor.
_DEFAULT_INTERSECTION = "0.05,0.30;0.95,0.30;0.98,0.90;0.45,0.98;0.02,0.90"
INTERSECTION_POLY_RAW = os.getenv("INTERSECTION_POLY", _DEFAULT_INTERSECTION)
# Smaller crosswalk conflict zone (near-miss), separate from count zone
CROSSWALK = {
    "x1": float(os.getenv("CROSSWALK_X1", "0.12")),
    "y1": float(os.getenv("CROSSWALK_Y1", "0.58")),
    "x2": float(os.getenv("CROSSWALK_X2", "0.88")),
    "y2": float(os.getenv("CROSSWALK_Y2", "0.92")),
}
SCHOOL_HOURS = os.getenv("SCHOOL_HOURS", "07-09,14-16")
TRUCK_SPIKE = int(os.getenv("TRUCK_SPIKE_THRESHOLD", "8"))
OVERNIGHT_SPIKE = int(os.getenv("OVERNIGHT_SPIKE_THRESHOLD", "12"))
CORRIDOR_NAME = os.getenv("CORRIDOR_NAME", "Fairview Main St (ffm0)")


def _parse_poly(raw: str) -> np.ndarray:
    pts = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        x_s, y_s = part.split(",")
        pts.append([float(x_s), float(y_s)])
    return np.array(pts, dtype=np.float32)


INTERSECTION_POLY_NORM = _parse_poly(INTERSECTION_POLY_RAW)


def _empty_type_counts() -> dict[str, int]:
    return {name: 0 for name in CLASS_LABELS.values()}


def _empty_hourly() -> dict[str, int]:
    return {f"{h:02d}": 0 for h in range(24)}


def _parse_school_windows(raw: str) -> list[tuple[int, int]]:
    windows = []
    for part in raw.split(","):
        part = part.strip()
        if "-" not in part:
            continue
        a, b = part.split("-", 1)
        windows.append((int(a), int(b)))
    return windows


class CarCounterEngine:
    def __init__(
        self,
        resolver: Optional[StreamResolver] = None,
        store: Optional[TrafficStore] = None,
    ):
        self.resolver = resolver or StreamResolver()
        self.store = store or TrafficStore()
        self.model = YOLO(MODEL_NAME)
        self.tracker = sv.ByteTrack()
        self.intersection_zone: Optional[sv.PolygonZone] = None
        self.intersection_annotator: Optional[sv.PolygonZoneAnnotator] = None
        self.box_annotator = sv.BoxAnnotator(thickness=2)
        self.label_annotator = sv.LabelAnnotator(text_thickness=1, text_scale=0.45)
        self.trace_annotator = sv.TraceAnnotator(thickness=2)

        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest_jpeg: Optional[bytes] = None
        self._status = "idle"
        self._error: Optional[str] = None
        self._frame_size: Optional[tuple[int, int]] = None

        self._by_type: dict[str, int] = _empty_type_counts()
        self._in_frame_by_type: dict[str, int] = _empty_type_counts()
        self._counted_ids: set[int] = set()
        self._track_age: dict[int, int] = {}
        self._inside_prev: dict[int, bool] = {}
        self._recent_count_events: deque[tuple[float, float, float, int]] = deque(maxlen=80)
        self._unique_vehicle_count = 0
        self._vehicles_in_intersection = 0
        self._approaches = {
            "toward_camera": 0,
            "away_from_camera": 0,
            "side_street": 0,
        }
        self._hourly: dict[str, int] = _empty_hourly()
        self._hourly_heavy: dict[str, int] = _empty_hourly()
        self._hourly_ped: dict[str, int] = _empty_hourly()
        self._speed_bands = {"slow": 0, "normal": 0, "fast": 0}
        self._session_started_at: Optional[str] = None
        self._last_event_at: Optional[str] = None
        self._last_frame_at: Optional[float] = None
        self._vehicles_in_frame = 0
        self._pedestrians_in_frame = 0
        self._queue_length = 0
        self._crossing_times: deque[float] = deque(maxlen=500)
        self._recent_truck_times: deque[float] = deque(maxlen=200)
        self._prev_centroid: dict[int, tuple[float, float]] = {}
        self._motion: dict[int, tuple[float, float]] = {}
        self._near_miss_count = 0
        self._conflict_cooldown_until = 0.0
        self._blur_score = 0.0
        self._brightness = 0.0
        self._camera_status = "unknown"
        self._school_windows = _parse_school_windows(SCHOOL_HOURS)
        self._school_counts = {"vehicles": 0, "pedestrians": 0, "bicycles": 0}
        self._input_source = "camera_stream"
        self._source_label = self.resolver.alias
        self._source_mode = os.getenv("VIDEO_SOURCE_MODE", "auto").strip().lower()
        self._local_video_path = os.getenv("LOCAL_VIDEO_PATH", "").strip()
        self._local_video_loop = os.getenv("LOCAL_VIDEO_LOOP", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _validate_source_mode(self, mode: str) -> str:
        normalized = mode.strip().lower()
        if normalized not in {"auto", "live", "stream", "file", "local"}:
            raise RuntimeError(
                "VIDEO_SOURCE_MODE must be one of: auto, live, stream, file, local"
            )
        return normalized

    def configure_source(
        self,
        mode: str,
        local_video_path: Optional[str] = None,
        local_video_loop: Optional[bool] = None,
    ) -> dict:
        with self._lock:
            self._source_mode = self._validate_source_mode(mode)
            if local_video_path is not None:
                self._local_video_path = local_video_path.strip()
            if local_video_loop is not None:
                self._local_video_loop = bool(local_video_loop)
            return self._source_config_unlocked()

    def _source_config_unlocked(self) -> dict:
        return {
            "mode": self._source_mode,
            "local_video_path": self._local_video_path,
            "local_video_loop": self._local_video_loop,
        }

    def get_source_config(self) -> dict:
        with self._lock:
            return self._source_config_unlocked()

    def _resolve_input_source(self) -> tuple[str, bool]:
        local_path = self._local_video_path
        mode = self._validate_source_mode(self._source_mode)

        use_local = mode in {"file", "local"} or (mode == "auto" and bool(local_path))
        if use_local:
            if not local_path:
                raise RuntimeError(
                    "LOCAL_VIDEO_PATH is required when VIDEO_SOURCE_MODE is file/local"
                )
            p = Path(local_path).expanduser().resolve()
            if not p.exists() or not p.is_file():
                raise RuntimeError(f"Local video file not found: {p}")
            return (str(p), True)

        url = self.resolver.get_url(force=True)
        return (url, False)

    def _class_name(self, class_id: int) -> str:
        return CLASS_LABELS.get(int(class_id), str(class_id))

    def _ensure_zones(self, width: int, height: int) -> None:
        if self.intersection_zone is not None and self._frame_size == (width, height):
            return
        poly = np.zeros_like(INTERSECTION_POLY_NORM)
        poly[:, 0] = INTERSECTION_POLY_NORM[:, 0] * width
        poly[:, 1] = INTERSECTION_POLY_NORM[:, 1] * height
        self.intersection_zone = sv.PolygonZone(
            polygon=poly.astype(np.int32),
            triggering_anchors=(sv.Position.BOTTOM_CENTER,),
        )
        self.intersection_annotator = sv.PolygonZoneAnnotator(
            zone=self.intersection_zone,
            thickness=2,
            text_thickness=1,
            text_scale=0.5,
            color=sv.Color.from_hex("#22c55e"),
        )
        self._frame_size = (width, height)

    def _classify_approach(self, tid: int) -> str:
        dx, dy = self._motion.get(tid, (0.0, 0.0))
        if abs(dx) >= max(abs(dy), 1.0) * 0.85:
            return "side_street"
        if dy > 0:
            return "toward_camera"
        return "away_from_camera"

    def _commit_count(
        self,
        tid: int,
        cid: int,
        cx: float,
        cy: float,
        now: float,
        stamp: str,
        hour_key: str,
    ) -> bool:
        if tid in self._counted_ids:
            return False
        if self._track_age.get(tid, 0) < MIN_TRACK_AGE:
            return False
        if self._motion_speed(tid) < MIN_COUNT_SPEED_PX:
            return False
        if self._is_spatial_duplicate(cx, cy, cid, now):
            self._counted_ids.add(tid)
            return False

        name = self._class_name(cid)
        self._counted_ids.add(tid)
        self._recent_count_events.append((cx, cy, now, cid))
        self._by_type[name] = self._by_type.get(name, 0) + 1
        self._last_event_at = stamp
        if self._session_started_at is None:
            self._session_started_at = stamp

        band = self._speed_band_for(tid)
        if cid in ROAD_VEHICLE_IDS:
            self._unique_vehicle_count += 1
            approach = self._classify_approach(tid)
            self._approaches[approach] = self._approaches.get(approach, 0) + 1
            self._hourly[hour_key] = self._hourly.get(hour_key, 0) + 1
            self._crossing_times.append(now)
            self._speed_bands[band] = self._speed_bands.get(band, 0) + 1
            is_heavy = cid in HEAVY_CLASS_IDS
            if is_heavy:
                self._hourly_heavy[hour_key] = self._hourly_heavy.get(hour_key, 0) + 1
                self._recent_truck_times.append(now)
            self.store.add_crossing(name, tid, band, is_heavy)
            if self._in_school_hours(int(hour_key)):
                self._school_counts["vehicles"] += 1
            return True
        if cid == 1:
            self.store.add_crossing(name, tid, band, False)
            if self._in_school_hours(int(hour_key)):
                self._school_counts["bicycles"] += 1
            return True
        if cid == 0:
            self._hourly_ped[hour_key] = self._hourly_ped.get(hour_key, 0) + 1
            self.store.add_crossing(name, tid, band, False)
            if self._in_school_hours(int(hour_key)):
                self._school_counts["pedestrians"] += 1
            return True
        return False

    def _count_intersection_entries(self, detections: sv.Detections) -> int:
        """Count each object once when it enters the intersection polygon."""
        if (
            self.intersection_zone is None
            or detections.tracker_id is None
            or detections.class_id is None
            or len(detections) == 0
        ):
            self._vehicles_in_intersection = 0
            return 0

        inside_mask = self.intersection_zone.trigger(detections)
        now_dt = datetime.now(timezone.utc).astimezone()
        hour_key = f"{now_dt.hour:02d}"
        stamp = now_dt.isoformat(timespec="seconds")
        now = time.time()
        in_zone_vehicles = 0

        for i, (tracker_id, class_id) in enumerate(
            zip(detections.tracker_id, detections.class_id)
        ):
            tid = int(tracker_id)
            cid = int(class_id)
            inside = bool(inside_mask[i]) if i < len(inside_mask) else False
            x1, y1, x2, y2 = detections.xyxy[i]
            cx = float((x1 + x2) / 2.0)
            cy = float((y1 + y2) / 2.0)

            if inside and cid in ROAD_VEHICLE_IDS:
                in_zone_vehicles += 1

            # While inside and not yet counted, keep trying until track is mature+moving.
            if inside and tid not in self._counted_ids:
                self._commit_count(tid, cid, cx, cy, now, stamp, hour_key)

            self._inside_prev[tid] = inside

        # Cleanup stale inside flags
        live = set(int(t) for t in detections.tracker_id)
        for tid in list(self._inside_prev.keys()):
            if tid not in live:
                self._inside_prev.pop(tid, None)

        self._vehicles_in_intersection = in_zone_vehicles
        return in_zone_vehicles

    def _update_track_ages(self, detections: sv.Detections) -> None:
        if detections.tracker_id is None:
            return
        seen = set()
        for tracker_id in detections.tracker_id:
            tid = int(tracker_id)
            seen.add(tid)
            self._track_age[tid] = self._track_age.get(tid, 0) + 1
        # Drop ages for vanished tracks to avoid unbounded growth
        stale = [tid for tid in self._track_age if tid not in seen]
        for tid in stale:
            # Keep age briefly so flicker doesn't reset; hard-drop after long absence
            self._track_age[tid] = max(0, self._track_age[tid] - 2)
            if self._track_age[tid] <= 0:
                self._track_age.pop(tid, None)

    def _motion_speed(self, tid: int) -> float:
        dx, dy = self._motion.get(tid, (0.0, 0.0))
        return float((dx * dx + dy * dy) ** 0.5)

    def _is_spatial_duplicate(self, cx: float, cy: float, class_id: int, now: float) -> bool:
        for px, py, ts, cid in self._recent_count_events:
            if int(cid) != int(class_id):
                continue
            if now - ts > DEDUP_SECONDS:
                continue
            if ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5 <= DEDUP_DISTANCE_PX:
                return True
        return False

    def _filter_detections(self, detections: sv.Detections) -> sv.Detections:
        if detections.class_id is None or len(detections) == 0:
            return detections
        class_mask = np.isin(detections.class_id, list(DETECT_CLASS_IDS))
        if detections.confidence is None:
            return detections[class_mask]
        conf_ok = np.array(
            [
                float(conf) >= CLASS_MIN_CONF.get(int(cid), CONFIDENCE)
                for conf, cid in zip(detections.confidence, detections.class_id)
            ],
            dtype=bool,
        )
        return detections[class_mask & conf_ok]

    def _update_motion(self, detections: sv.Detections) -> None:
        if detections.tracker_id is None or len(detections) == 0:
            return
        for i, tracker_id in enumerate(detections.tracker_id):
            tid = int(tracker_id)
            x1, y1, x2, y2 = detections.xyxy[i]
            cx, cy = float((x1 + x2) / 2), float((y1 + y2) / 2)
            prev = self._prev_centroid.get(tid)
            if prev is not None:
                self._motion[tid] = (cx - prev[0], cy - prev[1])
            self._prev_centroid[tid] = (cx, cy)

    def _speed_band_for(self, tid: int) -> str:
        dx, dy = self._motion.get(tid, (0.0, 0.0))
        speed = (dx * dx + dy * dy) ** 0.5
        if speed < SPEED_SLOW:
            return "slow"
        if speed >= SPEED_FAST:
            return "fast"
        return "normal"

    def _in_school_hours(self, hour: int) -> bool:
        for start, end in self._school_windows:
            if start <= hour < end:
                return True
        return False

    def _in_crosswalk(self, cx: float, cy: float, width: int, height: int) -> bool:
        return (
            CROSSWALK["x1"] * width <= cx <= CROSSWALK["x2"] * width
            and CROSSWALK["y1"] * height <= cy <= CROSSWALK["y2"] * height
        )

    def _update_camera_health(self, frame: np.ndarray) -> None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        self._brightness = float(np.mean(gray))
        self._last_frame_at = time.time()
        if self._blur_score < 40:
            self._camera_status = "blur"
        elif self._brightness < 35:
            self._camera_status = "night_or_dark"
        else:
            self._camera_status = "ok"

    def _evaluate_alerts(self) -> None:
        now = time.time()
        recent_trucks = sum(1 for t in self._recent_truck_times if now - t <= 600)
        if recent_trucks >= TRUCK_SPIKE:
            self.store.add_alert(
                "warning",
                "truck_spike",
                f"Heavy truck spike: {recent_trucks} trucks in the last 10 minutes.",
            )

        hour = datetime.now().hour
        if 0 <= hour < 5:
            overnight = sum(
                1 for t in self._crossing_times if now - t <= 1800
            )
            if overnight >= OVERNIGHT_SPIKE:
                self.store.add_alert(
                    "warning",
                    "overnight_volume",
                    f"Unusual overnight volume: {overnight} vehicles in 30 minutes.",
                )

        if self._camera_status == "blur":
            self.store.add_alert(
                "critical",
                "camera_blur",
                "Camera image appears blurred or out of focus.",
            )
        if self._last_frame_at and (now - self._last_frame_at) > 20 and self._running:
            self.store.add_alert(
                "critical",
                "camera_offline",
                "Camera stream stalled — no recent frames.",
            )

    def _detect_conflicts(
        self,
        detections: sv.Detections,
        width: int,
        height: int,
    ) -> None:
        if detections.tracker_id is None or detections.class_id is None:
            return
        now = time.time()
        if now < self._conflict_cooldown_until:
            return

        peds_in = False
        vehs_in = False
        for i, class_id in enumerate(detections.class_id):
            x1, y1, x2, y2 = detections.xyxy[i]
            cx, cy = float((x1 + x2) / 2), float((y1 + y2) / 2)
            if not self._in_crosswalk(cx, cy, width, height):
                continue
            cid = int(class_id)
            if cid == 0 or cid == 1:
                peds_in = True
            elif cid in ROAD_VEHICLE_IDS:
                vehs_in = True
        if peds_in and vehs_in:
            self._near_miss_count += 1
            self._conflict_cooldown_until = now + 3.0
            self.store.add_alert(
                "warning",
                "near_miss",
                "Possible near-miss: vehicle and vulnerable road user in crosswalk zone.",
            )

    def _queue_count(self, detections: sv.Detections, height: int) -> int:
        if detections.class_id is None or len(detections) == 0:
            return 0
        y_min = height * QUEUE_Y_RATIO
        count = 0
        for i, class_id in enumerate(detections.class_id):
            if int(class_id) not in ROAD_VEHICLE_IDS:
                continue
            _, y1, _, y2 = detections.xyxy[i]
            cy = float((y1 + y2) / 2)
            if cy >= y_min:
                count += 1
        return count

    def _vehicles_per_minute(self) -> float:
        now = time.time()
        recent = [t for t in self._crossing_times if now - t <= 60]
        return float(len(recent))

    def _congestion_score(self, vpm: float, queue: int) -> int:
        # 0–100 planning score
        score = min(100, int(vpm * 8 + queue * 12))
        return score

    def _peak_hour(self, hourly: dict[str, int]) -> dict:
        if not hourly or max(hourly.values()) == 0:
            return {"hour": None, "label": None, "count": 0}
        hour = max(hourly.items(), key=lambda item: item[1])[0]
        h = int(hour)
        return {
            "hour": hour,
            "label": f"{h:02d}:00–{(h + 1) % 24:02d}:00",
            "count": int(hourly[hour]),
        }

    def _draw_overlays(self, frame: np.ndarray, width: int, height: int) -> np.ndarray:
        # Crosswalk conflict zone (near-miss only)
        x1 = int(CROSSWALK["x1"] * width)
        y1 = int(CROSSWALK["y1"] * height)
        x2 = int(CROSSWALK["x2"] * width)
        y2 = int(CROSSWALK["y2"] * height)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 255), 2)
        cv2.putText(
            frame,
            "Conflict zone",
            (x1 + 6, y1 - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 200, 255),
            1,
            cv2.LINE_AA,
        )
        return frame

    def _draw_hud(self, frame: np.ndarray, stats_snapshot: dict) -> np.ndarray:
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (460, 155), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.45, frame, 0.55, 0)
        cong = stats_snapshot.get("congestion", {})
        approaches = stats_snapshot.get("approaches", {})
        cv2.putText(
            frame,
            f"Intersection vehicles: {stats_snapshot.get('total', 0)}  Ped: {stats_snapshot.get('pedestrians', 0)}",
            (20, 38),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"In zone now: {stats_snapshot.get('vehicles_in_intersection', 0)}  Congestion: {cong.get('score', 0)}  VPM: {cong.get('vehicles_per_minute', 0):.1f}",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (180, 220, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"Toward: {approaches.get('toward_camera', 0)}  Away: {approaches.get('away_from_camera', 0)}  Side: {approaches.get('side_street', 0)}",
            (20, 102),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 255, 200),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"Camera: {stats_snapshot.get('camera_health', {}).get('status', 'n/a')}",
            (20, 134),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 255, 200),
            2,
            cv2.LINE_AA,
        )
        return frame

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        self._ensure_zones(width, height)
        self._update_camera_health(frame)

        results = self.model(
            frame,
            conf=CONFIDENCE,
            imgsz=INFER_IMGSZ,
            classes=list(DETECT_CLASS_IDS),
            verbose=False,
        )[0]
        detections = sv.Detections.from_ultralytics(results)
        detections = self._filter_detections(detections)
        detections = self.tracker.update_with_detections(detections)
        self._update_motion(detections)
        self._update_track_ages(detections)

        vehicle_mask = (
            np.isin(detections.class_id, list(ROAD_VEHICLE_IDS))
            if detections.class_id is not None and len(detections)
            else np.array([], dtype=bool)
        )

        self._count_intersection_entries(detections)
        self._detect_conflicts(detections, width, height)
        queue = self._queue_count(detections, height)
        self._evaluate_alerts()

        labels = []
        in_frame = _empty_type_counts()
        peds = 0
        if detections.tracker_id is not None and len(detections) > 0:
            for confidence, class_id, tracker_id in zip(
                detections.confidence,
                detections.class_id,
                detections.tracker_id,
            ):
                name = self._class_name(int(class_id))
                in_frame[name] = in_frame.get(name, 0) + 1
                if int(class_id) == 0:
                    peds += 1
                band = self._speed_band_for(int(tracker_id))
                counted = " *" if int(tracker_id) in self._counted_ids else ""
                labels.append(
                    f"#{int(tracker_id)} {name}{counted} {band} {float(confidence):.2f}"
                )

        annotated = frame.copy()
        annotated = self._draw_overlays(annotated, width, height)
        if self.intersection_zone is not None and self.intersection_annotator is not None:
            annotated = self.intersection_annotator.annotate(annotated)
            cv2.putText(
                annotated,
                "Intersection count zone",
                (20, height - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (80, 220, 120),
                2,
                cv2.LINE_AA,
            )
        annotated = self.trace_annotator.annotate(scene=annotated, detections=detections)
        annotated = self.box_annotator.annotate(scene=annotated, detections=detections)
        if labels:
            annotated = self.label_annotator.annotate(
                scene=annotated, detections=detections, labels=labels
            )

        with self._lock:
            self._vehicles_in_frame = int(vehicle_mask.sum()) if len(vehicle_mask) else 0
            self._pedestrians_in_frame = peds
            self._in_frame_by_type = in_frame
            self._queue_length = queue
            snap = self._stats_unlocked()

        annotated = self._draw_hud(annotated, snap)
        return annotated

    def _encode_jpeg(self, frame: np.ndarray) -> bytes:
        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if not ok:
            raise RuntimeError("Failed to encode JPEG frame")
        return buffer.tobytes()

    def _loop(self) -> None:
        self._status = "connecting"
        cap = None
        try:
            source_target, is_local_file = self._resolve_input_source()
            if is_local_file:
                self._input_source = "local_file"
                self._source_label = Path(source_target).name
            else:
                self._input_source = "camera_stream"
                self._source_label = self.resolver.alias
                self.resolver.start_background_refresh()

            cap = cv2.VideoCapture(source_target)
            if not cap.isOpened():
                raise RuntimeError(f"Could not open source: {source_target}")
            self._status = "running"
            self._error = None
            fail_count = 0
            if self._session_started_at is None:
                self._session_started_at = (
                    datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
                )
            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    if is_local_file:
                        if self._local_video_loop:
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            continue
                        self.store.add_alert(
                            "info",
                            "video_complete",
                            "Local video finished. Start again or enable LOCAL_VIDEO_LOOP.",
                        )
                        self._running = False
                        break

                    fail_count += 1
                    if fail_count >= 30:
                        self.store.add_alert(
                            "critical",
                            "camera_offline",
                            "Camera stream unavailable — reconnecting.",
                        )
                        url = self.resolver.get_url(force=True)
                        cap.release()
                        cap = cv2.VideoCapture(url)
                        fail_count = 0
                    continue
                fail_count = 0
                annotated = self.process_frame(frame)
                jpeg = self._encode_jpeg(annotated)
                with self._lock:
                    self._latest_jpeg = jpeg
        except Exception as exc:
            self._error = str(exc)
            self._status = "error"
            self.store.add_alert("critical", "engine_error", str(exc))
        finally:
            if cap is not None:
                cap.release()
            if self._running and self._status != "error":
                self._status = "stopped"
            self._running = False

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._error = None
            self._status = "starting"
            self._thread = threading.Thread(target=self._loop, name="car-counter", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        with self._lock:
            if self._status != "error":
                self._status = "stopped"

    def reset(self) -> None:
        with self._lock:
            if self._frame_size is not None:
                width, height = self._frame_size
                self._frame_size = None
                self._ensure_zones(width, height)
            else:
                self.intersection_zone = None
                self.intersection_annotator = None
            self.tracker = sv.ByteTrack()
            self._by_type = _empty_type_counts()
            self._in_frame_by_type = _empty_type_counts()
            self._counted_ids = set()
            self._track_age = {}
            self._inside_prev = {}
            self._recent_count_events.clear()
            self._unique_vehicle_count = 0
            self._vehicles_in_intersection = 0
            self._approaches = {
                "toward_camera": 0,
                "away_from_camera": 0,
                "side_street": 0,
            }
            self._hourly = _empty_hourly()
            self._hourly_heavy = _empty_hourly()
            self._hourly_ped = _empty_hourly()
            self._speed_bands = {"slow": 0, "normal": 0, "fast": 0}
            self._session_started_at = None
            self._last_event_at = None
            self._vehicles_in_frame = 0
            self._pedestrians_in_frame = 0
            self._queue_length = 0
            self._crossing_times.clear()
            self._recent_truck_times.clear()
            self._prev_centroid.clear()
            self._motion.clear()
            self._near_miss_count = 0
            self._school_counts = {"vehicles": 0, "pedestrians": 0, "bicycles": 0}

    def _stats_unlocked(self) -> dict:
        total_vehicles = int(self._unique_vehicle_count)
        class_sum = sum(
            self._by_type.get(k, 0) for k in ("car", "motorcycle", "bus", "truck")
        )
        if class_sum != total_vehicles:
            total_vehicles = class_sum
            self._unique_vehicle_count = class_sum
        pedestrians = int(self._by_type.get("pedestrian", 0))
        heavy_trucks = int(self._by_type.get("truck", 0))
        heavy_vehicles = heavy_trucks + int(self._by_type.get("bus", 0))
        vpm = self._vehicles_per_minute()
        queue = self._queue_length
        score = self._congestion_score(vpm, queue)
        offline = bool(
            self._last_frame_at and (time.time() - self._last_frame_at) > 15 and self._running
        )
        cam_status = "offline" if offline else self._camera_status

        return {
            "status": self._status,
            "error": self._error,
            "running": self._running,
            "counting_mode": "intersection_zone_entry",
            "in_count": int(self._approaches.get("toward_camera", 0)),
            "out_count": int(self._approaches.get("away_from_camera", 0)),
            "side_street_count": int(self._approaches.get("side_street", 0)),
            "approaches": dict(self._approaches),
            "total": int(total_vehicles),
            "vehicles_in_intersection": int(self._vehicles_in_intersection),
            "pedestrians": pedestrians,
            "bicycles": int(self._by_type.get("bicycle", 0)),
            "vehicles_in_frame": int(self._vehicles_in_frame),
            "pedestrians_in_frame": int(self._pedestrians_in_frame),
            "alias": self._source_label,
            "input_source": self._input_source,
            "source_config": self._source_config_unlocked(),
            "corridor": CORRIDOR_NAME,
            "by_type": dict(self._by_type),
            "in_frame_by_type": dict(self._in_frame_by_type),
            "heavy_trucks": heavy_trucks,
            "heavy_vehicles": heavy_vehicles,
            "hourly": dict(self._hourly),
            "hourly_heavy": dict(self._hourly_heavy),
            "hourly_pedestrians": dict(self._hourly_ped),
            "peak_hour": self._peak_hour(self._hourly),
            "peak_heavy_hour": self._peak_hour(self._hourly_heavy),
            "session_started_at": self._session_started_at,
            "last_event_at": self._last_event_at,
            "speed_bands": dict(self._speed_bands),
            "count_quality": {
                "min_track_age": MIN_TRACK_AGE,
                "min_speed_px": MIN_COUNT_SPEED_PX,
                "dedup_seconds": DEDUP_SECONDS,
                "mode": "intersection_polygon_entry",
            },
            "congestion": {
                "score": score,
                "level": (
                    "severe"
                    if score >= 75
                    else "high"
                    if score >= 50
                    else "moderate"
                    if score >= 25
                    else "low"
                ),
                "vehicles_per_minute": round(vpm, 2),
                "queue_length": int(queue),
            },
            "conflicts": {
                "near_miss_count": int(self._near_miss_count),
                "zone": CROSSWALK,
            },
            "camera_health": {
                "status": cam_status,
                "blur_score": round(self._blur_score, 1),
                "brightness": round(self._brightness, 1),
                "last_frame_age_sec": (
                    None
                    if self._last_frame_at is None
                    else round(time.time() - self._last_frame_at, 1)
                ),
            },
            "school_zone": {
                "windows": [
                    f"{a:02d}:00-{b:02d}:00" for a, b in self._school_windows
                ],
                "counts": dict(self._school_counts),
            },
            "freight_corridor": {
                "name": CORRIDOR_NAME,
                "truck_share": (
                    round(heavy_trucks / total_vehicles, 3) if total_vehicles else 0.0
                ),
                "heavy_trucks": heavy_trucks,
                "total_vehicles": int(total_vehicles),
            },
        }

    def get_stats(self) -> dict:
        with self._lock:
            return self._stats_unlocked()

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def public_stats(self) -> dict:
        full = self.get_stats()
        return {
            "alias": full.get("alias"),
            "corridor": full.get("corridor"),
            "total": full.get("total"),
            "pedestrians": full.get("pedestrians"),
            "heavy_trucks": full.get("heavy_trucks"),
            "congestion": {
                "score": full.get("congestion", {}).get("score"),
                "level": full.get("congestion", {}).get("level"),
            },
            "peak_hour": full.get("peak_hour"),
            "camera_health": {
                "status": full.get("camera_health", {}).get("status"),
            },
            "status": full.get("status"),
            "running": full.get("running"),
        }
