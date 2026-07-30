"""Desktop agent — mouse, keyboard, screenshots, window management."""
from __future__ import annotations
import io, json, subprocess, tempfile, os

def _has_pyautogui():
    try:
        import pyautogui
        return True
    except ImportError:
        return False

def _has_mss():
    try:
        import mss
        return True
    except ImportError:
        return False

class DesktopAgent:
    def __init__(self):
        self._pyautogui = None
        self._mss = None
        if _has_pyautogui():
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05
            self._pyautogui = pyautogui
        if _has_mss():
            import mss
            self._mss = mss

    @property
    def available(self) -> bool:
        return self._pyautogui is not None or self._mss is not None

    def screenshot(self, region: tuple | None = None) -> str:
        if self._mss:
            try:
                import numpy as np
                from PIL import Image
                with self._mss.mss() as sct:
                    monitor = sct.monitors[1]
                    if region:
                        monitor = {"top": region[1], "left": region[0], "width": region[2], "height": region[3]}
                    img = np.asarray(sct.grab(monitor))
                    pil_img = Image.fromarray(img[:, :, :3])
                    path = os.path.join(tempfile.gettempdir(), f"kai_screenshot_{os.getpid()}.png")
                    pil_img.save(path)
                    return f"Screenshot saved to {path} ({pil_img.size[0]}x{pil_img.size[1]})"
            except Exception as e:
                return f"Screenshot failed (mss): {e}"
        if self._pyautogui:
            try:
                path = os.path.join(tempfile.gettempdir(), f"kai_screenshot_{os.getpid()}.png")
                img = self._pyautogui.screenshot(region=region)
                img.save(path)
                return f"Screenshot saved to {path} ({img.size[0]}x{img.size[1]})"
            except Exception as e:
                return f"Screenshot failed (pyautogui): {e}"
        return "No screenshot library available. Install: pip install mss Pillow"

    def click(self, x: int, y: int, button: str = "left") -> str:
        if not self._pyautogui:
            return "pyautogui not installed"
        try:
            self._pyautogui.click(x, y, button=button)
            return f"Clicked ({x}, {y})"
        except Exception as e:
            return f"Click failed: {e}"

    def double_click(self, x: int, y: int) -> str:
        if not self._pyautogui:
            return "pyautogui not installed"
        try:
            self._pyautogui.doubleClick(x, y)
            return f"Double-clicked ({x}, {y})"
        except Exception as e:
            return f"Double-click failed: {e}"

    def type_text(self, text: str) -> str:
        if not self._pyautogui:
            return "pyautogui not installed"
        try:
            self._pyautogui.typewrite(text, interval=0.03)
            return f"Typed {len(text)} characters"
        except Exception as e:
            return f"Type failed: {e}"

    def hotkey(self, *keys: str) -> str:
        if not self._pyautogui:
            return "pyautogui not installed"
        try:
            self._pyautogui.hotkey(*keys)
            return f"Pressed: {'+'.join(keys)}"
        except Exception as e:
            return f"Hotkey failed: {e}"

    def move_mouse(self, x: int, y: int) -> str:
        if not self._pyautogui:
            return "pyautogui not installed"
        try:
            self._pyautogui.moveTo(x, y)
            return f"Mouse moved to ({x}, {y})"
        except Exception as e:
            return f"Move failed: {e}"

    def scroll(self, amount: int) -> str:
        if not self._pyautogui:
            return "pyautogui not installed"
        try:
            self._pyautogui.scroll(amount)
            return f"Scrolled {amount}"
        except Exception as e:
            return f"Scroll failed: {e}"

    def open_app(self, app: str) -> str:
        try:
            if self._pyautogui:
                subprocess.Popen([app], shell=True)
                return f"Launched {app}"
            return "pyautogui not installed"
        except Exception as e:
            return f"Launch failed: {e}"

    def get_mouse_position(self) -> str:
        if not self._pyautogui:
            return "pyautogui not installed"
        try:
            pos = self._pyautogui.position()
            return f"Mouse at ({pos.x}, {pos.y})"
        except Exception as e:
            return f"Position failed: {e}"

    def get_screen_size(self) -> str:
        if not self._pyautogui:
            return "pyautogui not installed"
        try:
            size = self._pyautogui.size()
            return f"Screen: {size.width}x{size.height}"
        except Exception as e:
            return f"Screen size failed: {e}"
