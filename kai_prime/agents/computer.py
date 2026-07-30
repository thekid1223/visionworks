"""Computer agent — orchestrates browser + desktop + screen for autonomous tasks."""
from __future__ import annotations
import json, subprocess, re
from pathlib import Path

class ComputerAgent:
    def __init__(self, workspace: Path | None = None):
        self.workspace = workspace or Path.cwd()
        self._desktop = None
        self._voice = None

    def _get_desktop(self):
        if self._desktop is None:
            from kai_prime.agents.desktop import DesktopAgent
            self._desktop = DesktopAgent()
        return self._desktop

    def _get_voice(self):
        if self._voice is None:
            from kai_prime.agents.voice import VoiceAgent
            self._voice = VoiceAgent()
        return self._voice

    def open_browser(self, url: str = "") -> str:
        try:
            import webbrowser
            if url:
                webbrowser.open(url)
                return f"Opened {url} in browser"
            webbrowser.open("about:blank")
            return "Opened browser"
        except Exception as e:
            return f"Failed to open browser: {e}"

    def open_app(self, app: str) -> str:
        desktop = self._get_desktop()
        return desktop.open_app(app)

    def screenshot(self) -> str:
        desktop = self._get_desktop()
        return desktop.screenshot()

    def type_and_enter(self, text: str) -> str:
        desktop = self._get_desktop()
        result = desktop.type_text(text)
        desktop.hotkey("enter")
        return result + " + Enter"

    def search_web(self, query: str) -> str:
        desktop = self._get_desktop()
        desktop.hotkey("ctrl", "l")
        import time; time.sleep(0.3)
        desktop.type_text(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        desktop.hotkey("enter")
        return f"Searching for: {query}"

    def get_system_info(self) -> dict | str:
        try:
            import psutil, platform
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
            return {"os": platform.system(), "os_version": platform.version(),
                    "hostname": platform.node(), "cpu_percent": cpu,
                    "ram_total_gb": round(mem.total / (1024**3), 1),
                    "ram_used_gb": round(mem.used / (1024**3), 1),
                    "ram_percent": mem.percent,
                    "disk_percent": disk.percent,
                    "disk_free_gb": round(disk.free / (1024**3), 1)}
        except ImportError:
            return {"error": "psutil not installed"}
        except Exception as e:
            return {"error": str(e)}

    def list_processes(self, top_n: int = 10) -> list | str:
        try:
            import psutil
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    info = p.info
                    procs.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            procs.sort(key=lambda x: x.get('cpu_percent', 0) or 0, reverse=True)
            return procs[:top_n]
        except ImportError:
            return ["psutil not installed"]

    def speak(self, text: str) -> str:
        voice = self._get_voice()
        if voice.speak(text):
            return "Speaking..."
        return "TTS not available"

    def stop_speaking(self) -> str:
        self._get_voice().stop()
        return "Stopped speaking"
