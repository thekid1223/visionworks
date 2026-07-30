"""Quick Capture — one-shot screen/clipboard grab for instant analysis."""
from __future__ import annotations

import subprocess
import threading
import time
import logging
from pathlib import Path

log = logging.getLogger("kai_prime.quick_capture")

TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


class QuickCapture:
    """Grab current screen or clipboard, extract text, return for analysis."""

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._capture_dir = workspace / "kai_prime_data" / "captures"
        self._capture_dir.mkdir(parents=True, exist_ok=True)

    def grab_screen(self, question: str = "") -> dict:
        """Take screenshot, OCR it, return text + path."""
        try:
            import pyautogui
            ts = int(time.time())
            path = self._capture_dir / f"quick_{ts}.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(str(path))

            ocr_text = self._ocr(str(path))
            context = self._get_active_window()

            # Clean old captures (keep last 15)
            files = sorted(self._capture_dir.glob("quick_*.png"))
            for f in files[:-15]:
                try:
                    f.unlink()
                except Exception:
                    pass

            return {
                "success": True,
                "path": str(path),
                "ocr_text": ocr_text[:3000],
                "context": context,
                "char_count": len(ocr_text),
                "question": question,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def grab_clipboard(self) -> dict:
        """Get current clipboard content."""
        try:
            r = subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-Command",
                 "Get-Clipboard -TextFormatOnly -ErrorAction SilentlyContinue"],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            text = r.stdout if r.returncode == 0 else ""
            return {
                "success": True,
                "text": text[:5000],
                "char_count": len(text),
                "preview": text[:200].replace("\n", " "),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def grab_both(self, question: str = "") -> dict:
        """Grab screen + clipboard simultaneously."""
        screen = self.grab_screen(question)
        clip = self.grab_clipboard()
        return {
            "screen": screen,
            "clipboard": clip,
            "question": question,
        }

    def _ocr(self, image_path: str) -> str:
        try:
            result = subprocess.run(
                [TESSERACT, image_path, "stdout", "-l", "eng"],
                capture_output=True, text=True, timeout=15,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def _get_active_window(self) -> dict:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "$p = Get-Process | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } | "
                 "Select-Object -Last 1; $p.MainWindowTitle + '|' + $p.ProcessName"],
                capture_output=True, text=True, timeout=2,
            )
            parts = r.stdout.strip().split("|")
            return {"title": parts[0], "process": parts[1]} if len(parts) == 2 else {}
        except Exception:
            return {}

    def status(self) -> dict:
        captures = list(self._capture_dir.glob("quick_*.png"))
        return {
            "capture_dir": str(self._capture_dir),
            "recent_captures": len(captures),
        }
