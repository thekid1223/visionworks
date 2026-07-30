"""CTOS Engine — device intelligence, network scanning, breach dossiers."""
from __future__ import annotations
import concurrent.futures, json, re, socket, subprocess, threading, time
from pathlib import Path
from kai_prime.config import KAI_DATA

_OUI_DB = {
    "b4:2e:99": "Intel", "34:f1:50": "Intel", "d8:31:34": "Intel",
    "18:a5:ff": "Intel", "e0:01:c7": "Huawei", "10:59:32": "Hon Hai",
    "2a:eb:c9": "Amazon", "94:bb:43": "Tenda", "00:1a:11": "Cisco",
    "00:0c:29": "VMware", "00:50:56": "VMware", "00:15:5d": "Hyper-V",
    "08:00:27": "VirtualBox", "ac:84:c6": "Huawei", "60:30:d4": "Xiaomi",
    "80:2a:a8": "Xiaomi", "ec:df:3a": "Espressif", "f4:5c:89": "Espressif",
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi",
    "00:1b:44": "Roku", "bc:6e:4a": "Apple", "f0:18:98": "Apple",
    "78:4f:43": "Apple", "ac:bc:32": "Apple", "38:c9:86": "Google",
    "8c:de:f9": "Google", "a4:77:33": "Google", "dc:0b:1c": "Amazon",
    "ac:63:be": "Amazon", "dc:44:6d": "Hikvision", "b4:a4:e3": "Dahua",
    "00:12:2b": "Synology", "00:21:2f": "Netgear", "14:cc:20": "TP-Link",
    "60:a4:4c": "TP-Link", "ec:17:66": "ASUS", "10:bf:48": "ASUS",
    "18:31:bf": "D-Link", "1c:5f:2b": "D-Link", "00:0e:8e": "Ubiquiti",
    "74:83:c2": "Ubiquiti", "68:72:51": "Aruba", "00:0b:86": "Meraki",
    "00:0b:09": "HP", "48:45:20": "HP", "a0:36:9f": "Canon", "3c:2c:99": "Epson",
    "00:04:f2": "Shenzhen", "8c:ae:4c": "Roku",
}

def _oui_vendor(mac: str) -> str:
    if not mac:
        return "Unknown"
    oui = mac[:8].lower().replace("-", ":")
    return _OUI_DB.get(oui, "Unknown")

def _device_type(vendor: str, hostname: str, ports: list) -> str:
    v = vendor.lower()
    port_nums = {p["port"] if isinstance(p, dict) else p for p in ports}
    if any(p in port_nums for p in [554, 8554]):
        return "camera"
    if any(p in port_nums for p in [80, 443, 8080]):
        if any(n in v for n in ("cisco", "ubiquiti", "meraki")):
            return "network"
        return "server"
    if any(n in v for n in ("apple", "samsung", "google", "xiaomi")):
        return "phone"
    if any(n in v for n in ("raspberry", "espressif")):
        return "iot"
    if any(n in v for n in ("vmware", "hyper-v", "virtualbox")):
        return "server"
    if any(n in v for n in ("cisco", "netgear", "tp-link", "d-link", "ubiquiti")):
        return "network"
    if any(n in v for n in ("canon", "epson", "hp")):
        return "printer"
    return "pc"

def _guess_os(ttl: int) -> str:
    if ttl <= 64:
        return "Linux/Unix"
    elif ttl <= 128:
        return "Windows"
    elif ttl <= 255:
        return "Network Device"
    return "Unknown"


class CTOSEngine:
    def __init__(self, workspace: Path | None = None):
        self.workspace = workspace or Path.cwd()
        self._db_path = KAI_DATA / "devices.json"
        self._devices: dict[str, dict] = self._load_db()
        self._scan_in_progress = False
        self._scan_done = False
        self._scan_count = 0

    def _load_db(self) -> dict:
        try:
            if self._db_path.exists():
                return json.loads(self._db_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_db(self):
        try:
            self._db_path.write_text(json.dumps(self._devices, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

    def upsert_device(self, ip: str, **kwargs):
        if ip not in self._devices:
            self._devices[ip] = {"ip": ip, "first_seen": time.time()}
        self._devices[ip].update(kwargs)
        self._devices[ip]["last_seen"] = time.time()
        self._save_db()

    def get_device(self, ip: str) -> dict | None:
        return self._devices.get(ip)

    def all_devices(self) -> list[dict]:
        return list(self._devices.values())

    def breach(self, ip: str) -> dict:
        device = self._devices.get(ip, {})
        if not device:
            enriched = self._enrich_device(ip)
            if enriched:
                device = enriched
        if not device:
            return {"ip": ip, "error": "Device not found and unreachable"}
        mac = device.get("mac", "")
        vendor = device.get("vendor", "")
        hostname = device.get("hostname", "")
        ports = device.get("ports", [])
        return {"ip": ip, "mac": mac, "vendor": vendor, "hostname": hostname,
                "os": device.get("os_guess", ""), "type": _device_type(vendor, hostname, ports),
                "ports": ports, "first_seen": device.get("first_seen", 0), "last_seen": device.get("last_seen", 0)}

    def _enrich_device(self, ip: str) -> dict | None:
        mac, vendor = "", ""
        hostname = ""
        ports = []
        try:
            arp = subprocess.run(["powershell", "-NoProfile", "-Command", f"arp -a | Select-String '{ip}'"],
                capture_output=True, text=True, timeout=3).stdout.strip()
            for line in arp.split("\n"):
                if ip in line:
                    cols = line.split()
                    if len(cols) >= 2:
                        mac = cols[1].strip()
                        vendor = _oui_vendor(mac)
                        break
        except Exception:
            pass
        try:
            nb = subprocess.run(["powershell", "-NoProfile", "-Command", f"nbtstat -A {ip} 2>$null | Select-String '<00>'"],
                capture_output=True, text=True, timeout=2).stdout.strip()
            for line in nb.split("\n"):
                if "<00>" in line and "UNIQUE" in line:
                    hostname = line.strip().split()[0]
                    break
        except Exception:
            pass
        common_ports = [(445, "SMB"), (139, "NetBIOS"), (80, "HTTP"), (443, "HTTPS"),
                        (3389, "RDP"), (22, "SSH"), (21, "FTP"), (8080, "HTTP-Alt"),
                        (5985, "WinRM"), (5900, "VNC"), (554, "RTSP")]
        def _check_port(port, svc):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.3)
                r = s.connect_ex((ip, port))
                s.close()
                if r == 0:
                    return {"port": port, "service": svc, "state": "open"}
            except Exception:
                pass
            return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = pool.map(lambda p: _check_port(*p), common_ports)
            ports = [r for r in results if r]
        os_guess = ""
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", f"ping -n 1 {ip} | Select-String 'TTL='"],
                capture_output=True, text=True, timeout=3).stdout.strip()
            m = re.search(r'TTL=(\d+)', r, re.I)
            if m:
                os_guess = _guess_os(int(m.group(1)))
        except Exception:
            pass
        device = {"mac": mac, "vendor": vendor, "hostname": hostname, "ports": ports, "os_guess": os_guess}
        self.upsert_device(ip, **device)
        return {"ip": ip, **device}

    def start_scan(self):
        if self._scan_in_progress:
            return
        self._scan_in_progress = True
        self._scan_done = False
        self._scan_count = 0
        threading.Thread(target=self._bg_scan, daemon=True).start()

    def _bg_scan(self):
        try:
            gw = self._get_gateway_ip()
            subnet = ".".join(gw.split(".")[:3]) if gw else ""
            if not subnet:
                return

            arp_raw = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5,
                                     encoding="utf-8", errors="replace").stdout
            ips = []
            for line in arp_raw.splitlines():
                stripped = line.strip()
                parts = stripped.split()
                if not parts:
                    continue
                candidate = parts[0]
                if candidate.startswith(subnet + ".") and candidate.count(".") == 3:
                    tail = candidate.split(".")[-1]
                    if tail.isdigit() and 1 <= int(tail) <= 254:
                        ips.append(candidate)

            ips = list(dict.fromkeys(ips))

            def _enrich(ip):
                return ip, self._enrich_device(ip)

            devices = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                futures = {pool.submit(_enrich, ip): ip for ip in ips}
                for f in concurrent.futures.as_completed(futures):
                    ip, d = f.result()
                    if d:
                        devices.append(d)
                    self._scan_count = len(devices)
        except Exception:
            pass
        finally:
            self._scan_in_progress = False
            self._scan_done = True

    def get_scan_status(self) -> dict:
        return {"running": self._scan_in_progress, "done": self._scan_done,
                "count": self._scan_count, "db_count": len(self._devices)}

    def _get_gateway_ip(self) -> str:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                "(Get-NetRoute -DestinationPrefix '0.0.0.0/0').NextHop | Select -First 1"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            if r.count(".") == 3:
                return r
        except Exception:
            pass
        return ""
