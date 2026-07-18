"""Resolve and refresh IPCamLive HLS stream URLs."""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

import requests

ALIAS = os.getenv("IPCAM_ALIAS", "ffm0")
STATE_URL = "https://ipcamlive.com/player/getcamerastreamstate.php"
REFRESH_SECONDS = int(os.getenv("STREAM_URL_REFRESH_SECONDS", "60"))


class StreamResolver:
    """Keeps a fresh HLS URL for an IPCamLive camera alias."""

    def __init__(self, alias: str = ALIAS, refresh_seconds: int = REFRESH_SECONDS):
        self.alias = alias
        self.refresh_seconds = refresh_seconds
        self._url: Optional[str] = None
        self._lock = threading.Lock()
        self._last_fetch = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def fetch_url(self) -> str:
        response = requests.get(STATE_URL, params={"alias": self.alias}, timeout=15)
        response.raise_for_status()
        data = response.json()
        details = data.get("details") or {}
        if str(details.get("streamavailable", "0")) != "1":
            raise RuntimeError(f"Camera '{self.alias}' stream is not available")

        address = (details.get("address") or "").rstrip("/") + "/"
        stream_id = details.get("streamid")
        if not stream_id:
            raise RuntimeError(f"No streamid returned for alias '{self.alias}'")

        url = f"{address}streams/{stream_id}/stream.m3u8"
        with self._lock:
            self._url = url
            self._last_fetch = time.time()
        return url

    def get_url(self, force: bool = False) -> str:
        with self._lock:
            stale = (time.time() - self._last_fetch) >= self.refresh_seconds
            if force or not self._url or stale:
                pass
            else:
                return self._url
        return self.fetch_url()

    def start_background_refresh(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def _loop() -> None:
            while not self._stop.wait(self.refresh_seconds):
                try:
                    self.fetch_url()
                except Exception:
                    # Keep last known URL; next read will retry.
                    pass

        self._thread = threading.Thread(target=_loop, name="stream-url-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
