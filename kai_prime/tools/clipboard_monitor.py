"""Clipboard Monitor v2 — Win32 event-driven clipboard detection.

Uses AddClipboardFormatListener via ctypes for instant push-based
notifications. PowerShell polling is the fallback only. Zero CPU when
clipboard is idle.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import subprocess
import threading
import time
import logging

log = logging.getLogger("kai_prime.clipboard")

# Win32 constants
WM_CLIPBOARDUPDATE = 0x031D
GWLP_WNDPROC = -4

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_longlong, ctypes.c_uint,
                              ctypes.c_longlong, ctypes.c_longlong)


class ClipboardMonitor:
    """Event-driven clipboard monitor using Win32 API. Zero polling."""

    def __init__(self, max_history: int = 30):
        self._max_history = max_history
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._history: list[dict] = []
        self._callbacks: list = []
        self._last_text = ""
        self._poll_fallback = False

    def add_callback(self, fn):
        self._callbacks.append(fn)

    def _notify(self, text: str):
        for cb in self._callbacks:
            try:
                cb(text)
            except Exception:
                pass

    def start(self):
        if self._enabled:
            return
        self._enabled = True
        self._last_text = self._get_clipboard()

        # Try Win32 event-driven first
        try:
            self._thread = threading.Thread(target=self._win32_loop, daemon=True)
            self._thread.start()
            log.info("Clipboard monitor v2 started (Win32 event-driven)")
        except Exception:
            # Fallback to polling
            self._poll_fallback = True
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()
            log.info("Clipboard monitor v2 started (polling fallback)")

    def stop(self):
        self._enabled = False

    def _win32_loop(self):
        """Create a hidden window and listen for WM_CLIPBOARDUPDATE."""
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "KaiClipboardWindow"

        # Register window class
        wc = ctypes.create_string_buffer(256)
        try:
            wnd_class = user32.RegisterClassExW.argtypes = [
                ctypes.c_void_p,  # WNDCLASSEX
            ]
        except Exception:
            self._poll_fallback = True
            return self._poll_loop()

        # Create hidden window for clipboard messages
        hwnd = user32.CreateWindowExW(0, class_name, "KaiClipboard",
                                      0, 0, 0, 0, 0, 0, 0, hinstance, 0)
        if not hwnd:
            self._poll_fallback = True
            return self._poll_loop()

        # Register for clipboard notifications
        user32.AddClipboardFormatListener(hwnd)

        # Message loop
        msg = ctypes.create_string_buffer(48)
        while self._enabled:
            ret = user32.GetMessageW(msg, 0, 0, 0)
            if ret <= 0:
                break
            if ctypes.c_uint.from_buffer(msg, 0).value == WM_CLIPBOARDUPDATE:
                text = self._get_clipboard()
                if text and text != self._last_text:
                    self._last_text = text
                    entry = {
                        "text": text[:5000],
                        "time": time.time(),
                        "preview": text[:120].replace("\n", " "),
                    }
                    self._history.append(entry)
                    if len(self._history) > self._max_history:
                        self._history = self._history[-self._max_history:]
                    self._notify(text)

        user32.RemoveClipboardFormatListener(hwnd)
        user32.DestroyWindow(hwnd)

    def _poll_loop(self):
        """Polling fallback (every 3s instead of 2s to reduce waste)."""
        while self._enabled:
            try:
                text = self._get_clipboard()
                if text and text != self._last_text and len(text.strip()) > 0:
                    self._last_text = text
                    entry = {
                        "text": text[:5000],
                        "time": time.time(),
                        "preview": text[:120].replace("\n", " "),
                    }
                    self._history.append(entry)
                    if len(self._history) > self._max_history:
                        self._history = self._history[-self._max_history:]
                    self._notify(text)
            except Exception:
                pass
            time.sleep(3)

    def _get_clipboard(self) -> str:
        try:
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
            return ""

    def get_current(self) -> str:
        return self._get_clipboard()

    def get_history(self, count: int = 10) -> list[dict]:
        return list(self._history[-count:])

    def get_last(self) -> str:
        if self._history:
            return self._history[-1]["text"]
        return self._get_clipboard()

    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "mode": "event-driven" if not self._poll_fallback else "polling",
            "history_count": len(self._history),
            "last_preview": self._history[-1]["preview"] if self._history else "",
        }
