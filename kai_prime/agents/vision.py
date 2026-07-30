"""Vision agent — webcam motion/presence/scene analysis + screenshot OCR."""
from __future__ import annotations
import logging, platform, subprocess, tempfile, time
from pathlib import Path

log = logging.getLogger("kai_prime.vision")


class VisionAgent:
    """Webcam analysis (motion, face, scene) and screenshot OCR."""

    def __init__(self):
        self._cv2 = None
        self._mss = None
        self._pyautogui = None
        self._init_cv2()
        self._init_capture()

    def _init_cv2(self):
        try:
            import cv2
            self._cv2 = cv2
        except ImportError:
            log.info("OpenCV not available — webcam vision disabled")

    def _init_capture(self):
        try:
            import mss
            self._mss = mss
        except ImportError:
            pass
        try:
            import pyautogui
            self._pyautogui = pyautogui
        except ImportError:
            pass

    @property
    def webcam_available(self) -> bool:
        return self._cv2 is not None

    @property
    def screenshot_available(self) -> bool:
        return self._mss is not None or self._pyautogui is not None

    # ── Webcam ───────────────────────────────────────────────────────────────

    def capture_webcam(self) -> str:
        if not self.webcam_available:
            return "Webcam not available (install opencv-python)"
        cap = self._cv2.VideoCapture(0)
        if not cap.isOpened():
            return "Could not open webcam"
        try:
            ret, frame = cap.read()
            if not ret:
                return "Could not read frame"
            path = Path(tempfile.gettempdir()) / f"kai_webcam_{int(time.time())}.jpg"
            self._cv2.imwrite(str(path), frame)
            return f"Webcam captured: {path}"
        finally:
            cap.release()

    def analyze_webcam(self, duration: float = 2.0) -> dict:
        if not self.webcam_available:
            return {"error": "webcam not available"}
        cap = self._cv2.VideoCapture(0)
        if not cap.isOpened():
            return {"error": "could not open webcam"}
        try:
            cv2 = self._cv2
            prev = None
            motion_frames = 0
            total_frames = 0
            faces_total = 0
            start = time.time()
            face_cascade = None
            try:
                face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            except Exception:
                pass
            while time.time() - start < duration:
                ret, frame = cap.read()
                if not ret:
                    break
                total_frames += 1
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)
                if prev is not None:
                    diff = cv2.absdiff(prev, gray)
                    thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
                    thresh = cv2.dilate(thresh, None, iterations=2)
                    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if any(cv2.contourArea(c) > 500 for c in contours):
                        motion_frames += 1
                prev = gray
                if face_cascade is not None:
                    orig = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(orig, 1.3, 5)
                    faces_total += len(faces)
            motion_level = motion_frames / max(total_frames, 1)
            avg_faces = faces_total / max(total_frames, 1)
            brightness = 0
            if total_frames > 0:
                cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if ret:
                    brightness = float(self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2GRAY).mean())
            scene = self._describe_scene(motion_level, avg_faces, brightness)
            return {
                "motion_level": round(motion_level, 2),
                "faces_detected": round(avg_faces, 1),
                "brightness": round(brightness, 0),
                "scene": scene,
                "total_frames": total_frames,
            }
        finally:
            cap.release()

    @staticmethod
    def _describe_scene(motion: float, faces: float, brightness: float) -> str:
        parts = []
        if faces >= 0.5:
            parts.append("Someone is here")
        elif faces > 0:
            parts.append("Brief presence detected")
        if motion > 0.5:
            parts.append("Significant movement")
        elif motion > 0.1:
            parts.append("Some movement")
        else:
            parts.append("Still")
        if brightness < 50:
            parts.append("It's dark")
        elif brightness > 200:
            parts.append("Very bright")
        else:
            parts.append("Normal lighting")
        return ". ".join(parts) + "."

    # ── Screenshots ──────────────────────────────────────────────────────────

    def take_screenshot(self) -> str:
        if self._mss:
            return self._screenshot_mss()
        if self._pyautogui:
            return self._screenshot_pyautogui()
        if platform.system() == "Windows":
            return self._screenshot_powershell()
        return "No screenshot backend available"

    def _screenshot_mss(self) -> str:
        try:
            with self._mss.mss() as sct:
                shot = sct.grab(sct.monitors[0])
                path = Path(tempfile.gettempdir()) / f"kai_screen_{int(time.time())}.png"
                self._mss.tools.to_png(shot.rgb, shot.size, output=str(path))
                return f"Screenshot saved: {path}"
        except Exception as e:
            return f"Screenshot failed: {e}"

    def _screenshot_pyautogui(self) -> str:
        try:
            shot = self._pyautogui.screenshot()
            path = Path(tempfile.gettempdir()) / f"kai_screen_{int(time.time())}.png"
            shot.save(str(path))
            return f"Screenshot saved: {path}"
        except Exception as e:
            return f"Screenshot failed: {e}"

    def _screenshot_powershell(self) -> str:
        try:
            path = Path(tempfile.gettempdir()) / f"kai_screen_{int(time.time())}.png"
            subprocess.run([
                "powershell", "-Command",
                f"Add-Type -AssemblyName System.Windows.Forms; "
                f"[System.Windows.Forms.Screen]::PrimaryScreen | ForEach-Object {{ "
                f"$bmp = New-Object System.Drawing.Bitmap($_.Bounds.Width, $_.Bounds.Height); "
                f"$gfx = [System.Drawing.Graphics]::FromImage($bmp); "
                f"$gfx.CopyFromScreen($_.Bounds.Location, [System.Drawing.Point]::Empty, $_.Bounds.Size); "
                f"$bmp.Save('{path}') }}"
            ], timeout=10, capture_output=True)
            if path.exists():
                return f"Screenshot saved: {path}"
            return "Screenshot failed (PowerShell)"
        except Exception as e:
            return f"Screenshot failed: {e}"

    def ocr_screenshot(self) -> str:
        if not self.screenshot_available:
            return "No screenshot backend"
        ss_result = self.take_screenshot()
        if "Screenshot saved:" not in ss_result:
            return ss_result
        ss_path = ss_result.split("Screenshot saved: ")[-1]
        try:
            import pytesseract
            from PIL import Image
            tess_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            import shutil
            found = shutil.which("tesseract")
            if found:
                pytesseract.pytesseract.tesseract_cmd = found
            else:
                for tp in tess_paths:
                    import os as _os
                    if _os.path.isfile(tp):
                        pytesseract.pytesseract.tesseract_cmd = tp
                        break
            img = Image.open(ss_path)
            text = pytesseract.image_to_string(img)
            return text[:5000] if text.strip() else "No text found in screenshot"
        except ImportError:
            return f"Screenshot captured but OCR unavailable (install pytesseract). Path: {ss_path}"
        except Exception as e:
            return f"OCR failed: {e}"

    def get_active_window(self) -> str:
        if platform.system() != "Windows":
            return "Active window detection only on Windows"
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or "Unknown window"
        except Exception:
            return "Could not detect active window"
