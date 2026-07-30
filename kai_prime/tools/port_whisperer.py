"""Port Whisperer v2 — WMI event-driven USB/Serial/Bluetooth detection.

Uses Register-CimIndicationEvent for push-based device arrival/removal
notifications instead of polling. One PowerShell event subscription covers
all device types. Zero polling overhead.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import logging
from pathlib import Path

log = logging.getLogger("kai_prime.port_whisperer")

_WMI_SUBSCRIBE = r"""
$query = "SELECT * FROM __InstanceCreationEvent WITHIN 2 WHERE TargetInstance ISA 'Win32_PnPEntity'"
Register-CimIndicationEvent -Query $query -SourceIdentifier KaiDeviceDetected -Action {
    $d = $Event.SourceEventArgs.NewEvent.TargetInstance
    $class = $d.PNPClass
    if ($class -eq 'Ports' -or $class -eq 'Bluetooth' -or $class -eq 'USB') {
        Write-Output ("DEVICE:" + $d.Name + "|" + $class + "|" + $d.DeviceID + "|" + $d.Status)
    }
}
Start-Sleep -Seconds 99999
"""


class PortWhisperer:
    """Event-driven USB/Serial/Bluetooth device detection."""

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._data_file = workspace / "kai_prime_data" / "devices.json"
        self._thread: threading.Thread | None = None
        self._probe_thread: threading.Thread | None = None
        self._enabled = False
        self._known_devices: dict[str, dict] = {}
        self._callbacks: list = []
        self._load()

    def _load(self):
        try:
            if self._data_file.exists():
                self._known_devices = json.loads(self._data_file.read_text(encoding="utf-8"))
        except Exception:
            self._known_devices = {}

    def _save(self):
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            self._data_file.write_text(json.dumps(self._known_devices, indent=2), encoding="utf-8")
        except Exception:
            pass

    def add_callback(self, fn):
        self._callbacks.append(fn)

    def _notify(self, msg):
        for cb in self._callbacks:
            try:
                cb(msg)
            except Exception:
                pass

    def start(self):
        if self._enabled:
            return
        self._enabled = True
        # WMI event subscription (push-based)
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        # Initial probe + periodic refresh (once per 5 min as backup)
        self._probe_thread = threading.Thread(target=self._backup_poll, daemon=True)
        self._probe_thread.start()
        log.info("Port Whisperer v2 started (event-driven)")

    def stop(self):
        self._enabled = False

    def _event_loop(self):
        try:
            proc = subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-Command", _WMI_SUBSCRIBE],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                if not self._enabled:
                    break
                line = line.strip()
                if line.startswith("DEVICE:"):
                    self._handle_line(line)
        except Exception:
            # Fallback: use polling
            log.warning("WMI events failed, falling back to polling")
            self._polling_fallback()

    def _handle_line(self, line: str):
        try:
            parts = line.split("|", 3)
            if len(parts) >= 3:
                name, cls, dev_id = parts[0][7:], parts[1], parts[2]
                status = parts[3] if len(parts) > 3 else "OK"
                dtype = self._map_class(cls)
                key = dev_id or name
                if key and key not in self._known_devices:
                    self._known_devices[key] = {
                        "name": name, "type": dtype,
                        "serial": dev_id, "status": status,
                    }
                    self._save()
                    self._notify(f"New {dtype} device: {name}")
        except Exception:
            pass

    def _map_class(self, cls: str) -> str:
        cls_l = cls.lower()
        if "bluetooth" in cls_l:
            return "bluetooth"
        if "usb" in cls_l or "ports" in cls_l:
            return "usb"
        if "serial" in cls_l or "com" in cls_l:
            return "serial"
        return cls_l

    def _backup_poll(self):
        while self._enabled:
            try:
                time.sleep(300)
                self._probe_all()
            except Exception:
                pass

    def _polling_fallback(self):
        while self._enabled:
            try:
                self._probe_all()
            except Exception:
                pass
            time.sleep(15)

    def _probe_all(self):
        """Single consolidated PowerShell query for all device types."""
        try:
            r = subprocess.run(["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-Command", r"""
Get-PnpDevice -ErrorAction SilentlyContinue |
    Where-Object { $_.Class -in @('Ports','Bluetooth','USB') -and $_.Status -eq 'OK' } |
    Select-Object FriendlyName, Class, DeviceID, Status | ConvertTo-Json -Compress
"""], capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            if not r.stdout.strip():
                return
            import json as j
            data = j.loads(r.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = item.get("FriendlyName", "")
                cls = item.get("Class", "")
                dev_id = item.get("DeviceID", "")
                key = dev_id or name
                dtype = self._map_class(cls)
                if key and key not in self._known_devices:
                    self._known_devices[key] = {
                        "name": name, "type": dtype,
                        "serial": dev_id, "status": "OK",
                    }
                    self._save()
                    self._notify(f"New {dtype} device: {name}")
        except Exception:
            pass

    def get_devices(self) -> list[dict]:
        return list(self._known_devices.values())

    def get_by_type(self, dtype: str) -> list[dict]:
        return [d for d in self._known_devices.values() if d.get("type") == dtype]

    def status(self) -> dict:
        devices = list(self._known_devices.values())
        types = {}
        for d in devices:
            t = d.get("type", "unknown")
            types[t] = types.get(t, 0) + 1
        return {
            "enabled": self._enabled,
            "total_devices": len(devices),
            "by_type": types,
            "mode": "event-driven" if self._thread and self._thread.is_alive() else "polling",
        }
