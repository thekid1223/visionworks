"""Proactive Watcher — monitors idle time, battery, downloads, clipboard, and speaks up."""
from __future__ import annotations
import platform, threading, time, logging
from collections import deque
from datetime import datetime
from pathlib import Path

log = logging.getLogger("kai_prime.watcher")


class Watcher:
    def __init__(self, workspace: Path | None = None, speak_fn=None):
        self.workspace = workspace or Path.cwd()
        self._speak_fn = speak_fn
        self._running = False
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._events = deque(maxlen=120)
        self._last_clipboard = ""
        self._last_download_count = 0
        self._last_idle_notice = 0.0
        self._greeted_today = False
        self._callbacks: list = []
        self._lock = threading.Lock()

    def on_event(self, callback):
        self._callbacks.append(callback)

    def _emit(self, event_type: str, message: str, speak: bool = True):
        event = {"type": event_type, "message": message, "timestamp": time.time()}
        self._events.append(event)
        for cb in self._callbacks:
            try:
                cb(event_type, message)
            except Exception:
                pass
        if speak and self._speak_fn:
            try:
                self._speak_fn(message)
            except Exception:
                pass

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop = threading.Event()
            watchers = [self._watch_idle, self._watch_downloads, self._watch_clipboard, self._watch_battery, self._watch_time]
            for fn in watchers:
                t = threading.Thread(target=fn, daemon=True)
                t.start()
                self._threads.append(t)
            log.info("Watcher started")

    def stop(self):
        self._running = False
        self._stop.set()

    def recent_events(self, limit: int = 20) -> list[dict]:
        return list(self._events)[-limit:]

    def _wait(self, seconds: float) -> bool:
        self._stop.wait(seconds)
        return not self._running

    def _watch_idle(self):
        while self._running:
            if self._wait(60):
                return
            try:
                idle = self._get_idle_time()
                if idle and idle > 600 and time.time() - self._last_idle_notice > 1800:
                    self._last_idle_notice = time.time()
                    mins = int(idle / 60)
                    self._emit("idle", f"You've been idle for {mins} minutes.", speak=False)
            except Exception:
                pass

    def _get_idle_time(self) -> float | None:
        try:
            if platform.system() == "Windows":
                import ctypes
                class LASTINPUTINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
                lii = LASTINPUTINFO()
                lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
                if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                    return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
        except Exception:
            pass
        return None

    def _watch_downloads(self):
        downloads = Path.home() / "Downloads"
        if not downloads.exists():
            return
        try:
            self._last_download_count = len(list(downloads.iterdir()))
        except Exception:
            return
        while self._running:
            if self._wait(15):
                return
            try:
                current = len(list(downloads.iterdir()))
                if current > self._last_download_count:
                    self._last_download_count = current
                    files = sorted(downloads.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
                    newest = files[0].name if files else "something"
                    self._emit("download", f"New file in Downloads: {newest}", speak=False)
            except Exception:
                pass

    def _watch_clipboard(self):
        while self._running:
            if self._wait(3):
                return
            try:
                cb = self._get_clipboard()
                if cb and cb != self._last_clipboard and 10 < len(cb) < 200:
                    self._last_clipboard = cb
                    self._emit("clipboard", f"Copied: {cb[:80]}", speak=False)
            except Exception:
                pass

    def _get_clipboard(self) -> str:
        try:
            if platform.system() == "Windows":
                import win32clipboard, win32con
                win32clipboard.OpenClipboard()
                try:
                    data = win32clipboard.GetClipboardData(win32con.CF_TEXT)
                    return data.decode("utf-8", errors="replace").strip()
                except TypeError:
                    return ""
                finally:
                    win32clipboard.CloseClipboard()
        except Exception:
            pass
        return ""

    def _watch_battery(self):
        while self._running:
            if self._wait(120):
                return
            try:
                level = self._get_battery()
                if level is not None and level <= 15 and level > 0:
                    self._emit("battery", f"Battery at {level}%.")
            except Exception:
                pass

    def _get_battery(self) -> int | None:
        try:
            if platform.system() == "Windows":
                import ctypes
                class SYSTEM_POWER_STATUS(ctypes.Structure):
                    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                                ("BatteryLifePercent", ctypes.c_byte), ("Reserved1", ctypes.c_byte),
                                ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
                sps = SYSTEM_POWER_STATUS()
                if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
                    if sps.BatteryLifePercent != 255:
                        return sps.BatteryLifePercent
        except Exception:
            pass
        return None

    def _watch_time(self):
        while self._running:
            if self._wait(300):
                return
            now = datetime.now()
            if 8 <= now.hour < 9 and not self._greeted_today:
                self._greeted_today = True
                self._emit("greeting", "Good morning. I've been keeping watch.", speak=False)
            if now.hour == 0 and now.minute < 5:
                self._greeted_today = False
