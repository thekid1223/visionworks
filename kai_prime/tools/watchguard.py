"""Watchguard — monitors lock screen, screensaver, and idle state."""
from __future__ import annotations

import subprocess
import threading
import time
import logging

log = logging.getLogger("kai_prime.watchguard")


class Watchguard:
    """Detects screen lock/unlock, screensaver, and prolonged idle."""

    def __init__(self, notify_fn=None):
        self._notify = notify_fn
        self._thread: threading.Thread | None = None
        self._enabled = False
        self._was_locked = False
        self._idle_start = 0.0
        self._idle_notified = False
        self._lock_count = 0
        self._unlock_count = 0
        self._last_lock_time = 0.0
        self._last_unlock_time = 0.0

    def start(self):
        if self._enabled:
            return
        self._enabled = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Watchguard started")

    def stop(self):
        self._enabled = False

    def _loop(self):
        while self._enabled:
            try:
                self._check_lock_state()
                self._check_idle()
            except Exception:
                pass
            time.sleep(5)

    def _check_lock_state(self):
        locked = self._is_locked()
        if locked and not self._was_locked:
            self._was_locked = True
            self._lock_count += 1
            self._last_lock_time = time.time()
            self._idle_start = 0.0
            self._idle_notified = False
            log.info("Screen locked")
        elif not locked and self._was_locked:
            self._was_locked = False
            self._unlock_count += 1
            self._last_unlock_time = time.time()
            log.info("Screen unlocked")

    def _is_locked(self) -> bool:
        try:
            import ctypes
            # Check if LogonUI.exe is running using CreateToolhelp32Snapshot
            kernel32 = ctypes.windll.kernel32
            CREATE_SNAPSHOT = 0x00000002  # TH32CS_SNAPPROCESS
            snap = kernel32.CreateToolhelp32Snapshot(CREATE_SNAPSHOT, 0)
            if snap == -1:
                return False
            try:
                from ctypes import wintypes
                class PROCESSENTRY32(ctypes.Structure):
                    _fields_ = [
                        ("dwSize", wintypes.DWORD),
                        ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260),
                    ]
                pe = PROCESSENTRY32()
                pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
                if kernel32.Process32First(snap, ctypes.byref(pe)):
                    while True:
                        if pe.szExeFile.decode("utf-8", errors="replace").lower() == "logonui.exe":
                            return True
                        if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                            break
                return False
            finally:
                kernel32.CloseHandle(snap)
        except Exception:
            return False

    def _check_idle(self):
        idle_secs = self._get_idle_seconds()
        if idle_secs > 900 and not self._idle_notified:
            self._idle_notified = True
            log.info("Idle for %d seconds", idle_secs)

    def _get_idle_seconds(self) -> int:
        try:
            import ctypes
            from ctypes import wintypes
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                ticks = ctypes.windll.kernel32.GetTickCount()
                return (ticks - lii.dwTime) // 1000
            return 0
        except Exception:
            return 0

    def is_locked(self) -> bool:
        return self._was_locked

    def status(self) -> dict:
        return {
            "locked": self._was_locked,
            "enabled": self._enabled,
            "idle_seconds": self._get_idle_seconds(),
            "lock_count": self._lock_count,
            "unlock_count": self._unlock_count,
            "last_lock": self._last_lock_time,
            "last_unlock": self._last_unlock_time,
        }
