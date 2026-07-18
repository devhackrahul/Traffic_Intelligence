"""SQLite persistence for traffic events, incidents, studies, and alerts."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.getenv("TRAFFIC_DB", Path(__file__).parent / "data" / "traffic.db"))


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class TrafficStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS crossings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        hour TEXT NOT NULL,
                        class_name TEXT NOT NULL,
                        tracker_id INTEGER,
                        speed_band TEXT,
                        is_heavy INTEGER DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS incidents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        note TEXT,
                        source TEXT DEFAULT 'manual'
                    );
                    CREATE TABLE IF NOT EXISTS studies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        phase TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        snapshot_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        level TEXT NOT NULL,
                        code TEXT NOT NULL,
                        message TEXT NOT NULL,
                        acknowledged INTEGER DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS daily_rollups (
                        day TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def add_crossing(
        self,
        class_name: str,
        tracker_id: int,
        speed_band: str,
        is_heavy: bool,
    ) -> None:
        now = datetime.now(timezone.utc).astimezone()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """
                    INSERT INTO crossings (ts, hour, class_name, tracker_id, speed_band, is_heavy)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now.isoformat(timespec="seconds"),
                        f"{now.hour:02d}",
                        class_name,
                        tracker_id,
                        speed_band,
                        1 if is_heavy else 0,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def add_incident(self, kind: str, note: str = "", source: str = "manual") -> dict:
        ts = _now()
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "INSERT INTO incidents (ts, kind, note, source) VALUES (?, ?, ?, ?)",
                    (ts, kind, note, source),
                )
                conn.commit()
                return {
                    "id": cur.lastrowid,
                    "ts": ts,
                    "kind": kind,
                    "note": note,
                    "source": source,
                }
            finally:
                conn.close()

    def list_incidents(self, limit: int = 100) -> list[dict]:
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM incidents ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def save_study(self, name: str, phase: str, snapshot: dict) -> dict:
        ts = _now()
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO studies (name, phase, created_at, snapshot_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, phase, ts, json.dumps(snapshot)),
                )
                conn.commit()
                return {
                    "id": cur.lastrowid,
                    "name": name,
                    "phase": phase,
                    "created_at": ts,
                }
            finally:
                conn.close()

    def list_studies(self) -> list[dict]:
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    "SELECT id, name, phase, created_at, snapshot_json FROM studies ORDER BY id DESC"
                ).fetchall()
                out = []
                for r in rows:
                    item = dict(r)
                    item["snapshot"] = json.loads(item.pop("snapshot_json"))
                    out.append(item)
                return out
            finally:
                conn.close()

    def compare_study(self, name: str) -> dict:
        studies = [s for s in self.list_studies() if s["name"] == name]
        before = next((s for s in studies if s["phase"] == "before"), None)
        after = next((s for s in studies if s["phase"] == "after"), None)
        if not before or not after:
            return {"name": name, "complete": False, "before": before, "after": after}

        b = before["snapshot"].get("by_type", {})
        a = after["snapshot"].get("by_type", {})
        keys = sorted(set(b) | set(a))
        delta = {k: int(a.get(k, 0)) - int(b.get(k, 0)) for k in keys}
        return {
            "name": name,
            "complete": True,
            "before": before,
            "after": after,
            "delta_by_type": delta,
            "delta_total": int(after["snapshot"].get("total", 0))
            - int(before["snapshot"].get("total", 0)),
            "delta_heavy_trucks": int(after["snapshot"].get("heavy_trucks", 0))
            - int(before["snapshot"].get("heavy_trucks", 0)),
        }

    def add_alert(self, level: str, code: str, message: str) -> Optional[dict]:
        # Deduplicate same code within last few minutes
        with self._lock:
            conn = self._conn()
            try:
                recent = conn.execute(
                    """
                    SELECT id FROM alerts
                    WHERE code = ? AND acknowledged = 0
                    ORDER BY id DESC LIMIT 1
                    """,
                    (code,),
                ).fetchone()
                if recent:
                    return None
                ts = _now()
                cur = conn.execute(
                    "INSERT INTO alerts (ts, level, code, message) VALUES (?, ?, ?, ?)",
                    (ts, level, code, message),
                )
                conn.commit()
                return {
                    "id": cur.lastrowid,
                    "ts": ts,
                    "level": level,
                    "code": code,
                    "message": message,
                    "acknowledged": 0,
                }
            finally:
                conn.close()

    def list_alerts(self, include_acked: bool = False, limit: int = 50) -> list[dict]:
        with self._lock:
            conn = self._conn()
            try:
                if include_acked:
                    rows = conn.execute(
                        "SELECT * FROM alerts ORDER BY id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM alerts WHERE acknowledged = 0
                        ORDER BY id DESC LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def ack_alert(self, alert_id: int) -> bool:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "UPDATE alerts SET acknowledged = 1 WHERE id = ?",
                    (alert_id,),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def crossings_summary(self) -> dict[str, Any]:
        with self._lock:
            conn = self._conn()
            try:
                by_type: dict[str, int] = {}
                for row in conn.execute(
                    "SELECT class_name, COUNT(*) AS c FROM crossings GROUP BY class_name"
                ):
                    by_type[row["class_name"]] = int(row["c"])
                hourly: dict[str, int] = {f"{h:02d}": 0 for h in range(24)}
                for row in conn.execute(
                    "SELECT hour, COUNT(*) AS c FROM crossings GROUP BY hour"
                ):
                    hourly[row["hour"]] = int(row["c"])
                heavy = conn.execute(
                    "SELECT COUNT(*) AS c FROM crossings WHERE is_heavy = 1"
                ).fetchone()["c"]
                speed = {"slow": 0, "normal": 0, "fast": 0}
                for row in conn.execute(
                    "SELECT speed_band, COUNT(*) AS c FROM crossings GROUP BY speed_band"
                ):
                    band = row["speed_band"] or "normal"
                    if band in speed:
                        speed[band] = int(row["c"])
                total = sum(by_type.values())
                return {
                    "total": total,
                    "by_type": by_type,
                    "hourly": hourly,
                    "heavy_trucks": int(by_type.get("truck", 0)),
                    "heavy_vehicles": int(heavy),
                    "speed_bands": speed,
                }
            finally:
                conn.close()

    def save_daily_rollup(self, day: str, payload: dict) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """
                    INSERT INTO daily_rollups (day, payload_json) VALUES (?, ?)
                    ON CONFLICT(day) DO UPDATE SET payload_json = excluded.payload_json
                    """,
                    (day, json.dumps(payload)),
                )
                conn.commit()
            finally:
                conn.close()
