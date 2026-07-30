"""Lightweight Scheduler — cron-like background task automation."""
from __future__ import annotations

import json
import time
import threading
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("kai_prime.scheduler")


class Scheduler:
    """Simple recurring task scheduler with JSON persistence."""

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._data_file = workspace / "kai_prime_data" / "scheduler.json"
        self._tasks: list[dict] = []
        self._thread: threading.Thread | None = None
        self._running = False
        self._execute_fn: Callable | None = None
        self._load()

    def _load(self):
        try:
            if self._data_file.exists():
                self._tasks = json.loads(self._data_file.read_text(encoding="utf-8"))
        except Exception:
            self._tasks = []

    def _save(self):
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            self._data_file.write_text(json.dumps(self._tasks, indent=2), encoding="utf-8")
        except Exception:
            pass

    def set_execute_fn(self, fn: Callable):
        self._execute_fn = fn

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Scheduler started with %d tasks", len(self._tasks))

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            now = time.time()
            for task in self._tasks:
                if not task.get("enabled", True):
                    continue
                if now >= task.get("next_run", 0):
                    self._run_task(task)
            time.sleep(10)

    def _run_task(self, task: dict):
        name = task.get("name", "unnamed")
        log.info("Running scheduled task: %s", name)
        task["last_run"] = time.time()
        task["run_count"] = task.get("run_count", 0) + 1

        interval = task.get("interval_seconds", 3600)
        task["next_run"] = time.time() + interval

        if self._execute_fn:
            try:
                self._execute_fn(task.get("command", ""))
            except Exception as e:
                log.error("Task %s failed: %s", name, e)

        self._save()

    def add_task(self, name: str, command: str, interval_seconds: int = 3600,
                 enabled: bool = True, description: str = "") -> dict:
        """Add a recurring task. interval_seconds: how often to run."""
        task = {
            "name": name,
            "command": command,
            "interval_seconds": interval_seconds,
            "enabled": enabled,
            "description": description,
            "next_run": time.time() + interval_seconds,
            "last_run": 0,
            "run_count": 0,
            "created": time.time(),
        }
        self._tasks.append(task)
        self._save()
        return task

    def remove_task(self, name: str) -> bool:
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.get("name") != name]
        if len(self._tasks) < before:
            self._save()
            return True
        return False

    def toggle_task(self, name: str, enabled: bool) -> bool:
        for task in self._tasks:
            if task.get("name") == name:
                task["enabled"] = enabled
                if enabled:
                    task["next_run"] = time.time() + task.get("interval_seconds", 3600)
                self._save()
                return True
        return False

    def list_tasks(self) -> list[dict]:
        return [{
            "name": t.get("name"),
            "command": t.get("command", "")[:80],
            "interval": self._fmt_interval(t.get("interval_seconds", 3600)),
            "enabled": t.get("enabled", True),
            "run_count": t.get("run_count", 0),
            "next_run": self._fmt_next(t.get("next_run", 0)),
        } for t in self._tasks]

    def _fmt_interval(self, secs: int) -> str:
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h"
        return f"{secs // 86400}d"

    def _fmt_next(self, ts: float) -> str:
        if ts <= 0:
            return "never"
        diff = ts - time.time()
        if diff <= 0:
            return "now"
        if diff < 60:
            return f"in {int(diff)}s"
        if diff < 3600:
            return f"in {int(diff // 60)}m"
        return f"in {int(diff // 3600)}h"

    def status(self) -> dict:
        enabled = sum(1 for t in self._tasks if t.get("enabled", True))
        return {
            "total_tasks": len(self._tasks),
            "enabled": enabled,
            "running": self._running,
        }
