"""Digital Twin — self-health monitoring, provider status, tool diagnostics."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import logging
from pathlib import Path

log = logging.getLogger("kai_prime.digital_twin")


class DigitalTwin:
    """Maintains a real-time model of Kai's own health and capabilities."""

    def __init__(self, workspace: Path, provider_fn=None, tools_fn=None):
        self._workspace = workspace
        self._data_file = workspace / "kai_prime_data" / "digital_twin.json"
        self._get_provider = provider_fn
        self._get_tools = tools_fn
        self._running = False
        self._cache: dict = {
            "provider": "unknown",
            "tools_online": 0,
            "tools_total": 0,
            "uptime": time.time(),
            "last_check": 0,
            "health_history": [],
        }

    def start(self):
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._health_loop, daemon=True)
        t.start()
        log.info("Digital Twin started")

    def _health_loop(self):
        while self._running:
            try:
                self._check_all()
            except Exception:
                pass
            time.sleep(300)

    def _check_all(self):
        now = time.time()
        checks = {}

        # Provider check
        if self._get_provider:
            try:
                p = self._get_provider()
                checks["provider"] = {"status": "ok", "detail": p}
                self._cache["provider"] = p
            except Exception as e:
                checks["provider"] = {"status": "error", "detail": str(e)}

        # Tools check
        if self._get_tools:
            try:
                tools = self._get_tools()
                checks["tools"] = {"status": "ok", "detail": f"{len(tools)} tools registered"}
                self._cache["tools_total"] = len(tools)
            except Exception as e:
                checks["tools"] = {"status": "error", "detail": str(e)}

        # Disk space
        try:
            usage = shutil.disk_usage(self._workspace)
            gb_free = usage.free / (1024 ** 3)
            checks["disk"] = {"status": "ok" if gb_free > 1 else "warning", "detail": f"{gb_free:.1f} GB free"}
        except Exception as e:
            checks["disk"] = {"status": "error", "detail": str(e)}

        # CPU + RAM
        try:
            cpu = subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average | "
                 "Select -ExpandProperty Average"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout.strip()
            ram = subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_OperatingSystem | "
                 "Select @{N='Pct';E={[math]::Round(($_.TotalVisibleMemorySize - $_.FreePhysicalMemory) / "
                 "$_.TotalVisibleMemorySize * 100)}} | Select -ExpandProperty Pct"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout.strip()
            checks["system"] = {"status": "ok", "detail": f"CPU: {cpu or '?'}%, RAM: {ram or '?'}%"}
        except Exception as e:
            checks["system"] = {"status": "error", "detail": str(e)}

        self._cache["last_check"] = now
        self._cache["health_history"] = list(self._cache.get("health_history", []))
        self._cache["health_history"].append({
            "time": now,
            "checks": {k: v["status"] for k, v in checks.items()},
        })
        self._cache["health_history"] = self._cache["health_history"][-50:]

        self._save()

    def _save(self):
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            save_data = {
                "provider": self._cache.get("provider"),
                "tools_total": self._cache.get("tools_total"),
                "uptime": self._cache.get("uptime"),
                "last_check": self._cache.get("last_check"),
                "health_history": self._cache.get("health_history", [])[-20:],
            }
            self._data_file.write_text(json.dumps(save_data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def status(self) -> dict:
        uptime_secs = time.time() - self._cache.get("uptime", time.time())
        hours, rem = divmod(int(uptime_secs), 3600)
        minutes = rem // 60

        history = self._cache.get("health_history", [])
        latest_checks = history[-1]["checks"] if history else {}
        all_ok = all(s == "ok" for s in latest_checks.values()) if latest_checks else False

        return {
            "status": "healthy" if all_ok else "degraded",
            "provider": self._cache.get("provider", "unknown"),
            "tools": self._cache.get("tools_online", 0),
            "total_tools": self._cache.get("tools_total", 0),
            "uptime": f"{hours}h {minutes}m",
            "last_check": "just now" if time.time() - self._cache.get("last_check", 0) < 120 else f"{int(time.time() - self._cache.get('last_check', 0)) // 60}m ago",
            "subsystems": latest_checks,
            "health_history_count": len(history),
        }

    def run_check(self) -> dict:
        """Force an immediate health check."""
        self._check_all()
        return self.status()

    def stop(self):
        self._running = False
