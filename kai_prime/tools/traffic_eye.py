"""Traffic Eye v2 — passive network monitor with batch lookups & caching.
Zero PowerShell — uses psutil for all connection data.
"""

from __future__ import annotations
import logging, threading, time
import psutil

log = logging.getLogger("kai_prime.traffic_eye")


class TrafficEye:
    """Monitors network connections using psutil — no PowerShell needed."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._enabled = False
        self._known_connections: set[tuple] = set()
        self._live_buffer: list[dict] = []
        self._buffer_lock = threading.Lock()
        self._max_buffer = 200
        self._stats = {"connections_seen": 0, "new_connections": 0, "polls": 0, "disconnects": 0}
        self._proc_cache: dict[str, str] = {}
        self._proc_cache_ttl = 60.0
        self._last_proc_fetch = 0.0
        self._prev_connections: set[tuple] = set()
        self._idle_count = 0

    def start(self):
        if self._enabled:
            return
        self._enabled = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Traffic Eye v2 started (adaptive polling, psutil)")

    def stop(self):
        self._enabled = False

    def _loop(self):
        while self._enabled:
            try:
                now = time.time()
                self._poll_connections(now)
                if self._stats["new_connections"] > self._stats["polls"] * 0.1:
                    self._idle_count = max(0, self._idle_count - 2)
                else:
                    self._idle_count += 1
                interval = 1 if self._idle_count < 3 else (5 if self._idle_count < 10 else 10)
                time.sleep(interval)
            except Exception:
                time.sleep(3)

    def _poll_connections(self, now: float):
        self._stats["polls"] += 1
        try:
            conns = psutil.net_connections(kind="tcp")
        except Exception:
            return
        if not conns:
            return

        pids = {str(c.pid) for c in conns if c.pid and c.status == "ESTABLISHED"}
        proc_map = self._batch_get_process_names(pids, now)

        current: set[tuple] = set()
        for c in conns:
            if c.status != "ESTABLISHED" or not c.pid:
                continue
            local = f"{c.laddr.ip}:{c.laddr.port}"
            remote = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "?:?"
            pid = str(c.pid)
            proc_name = proc_map.get(pid, self._proc_cache.get(pid, ""))
            key = (local, remote, pid)
            current.add(key)
            self._stats["connections_seen"] += 1

            if key not in self._known_connections:
                self._known_connections.add(key)
                self._stats["new_connections"] += 1
                entry = {"local": local, "remote": remote, "process": proc_name, "pid": pid, "time": now}
                with self._buffer_lock:
                    self._live_buffer.append(entry)
                    if len(self._live_buffer) > self._max_buffer:
                        self._live_buffer = self._live_buffer[-self._max_buffer:]

        if self._prev_connections:
            gone = self._prev_connections - current
            self._stats["disconnects"] += len(gone)
        self._prev_connections = current

    def _batch_get_process_names(self, pids: set, now: float) -> dict[str, str]:
        if not pids:
            return {}
        if now - self._last_proc_fetch < self._proc_cache_ttl:
            return {p: self._proc_cache.get(p, "") for p in pids}
        result = {}
        for pid in pids:
            try:
                p = psutil.Process(int(pid))
                name = p.name()
                self._proc_cache[pid] = name
                result[pid] = name
            except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                pass
        self._last_proc_fetch = now
        return result

    def get_live(self) -> list[dict]:
        with self._buffer_lock:
            return list(self._live_buffer)

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "unique_pairs": len(self._known_connections),
            "enabled": self._enabled,
            "proc_cache_size": len(self._proc_cache),
            "poll_interval": "adaptive (1-10s)",
        }

    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "live_connections": len(self._live_buffer),
            "unique_pairs": len(self._known_connections),
            "stats": self._stats,
            "proc_cache_hot": len(self._proc_cache) > 0,
        }
