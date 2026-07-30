"""Healer — self-healing coordinator for error classification, repair strategies, and escalation."""
from __future__ import annotations
import json, threading, time, logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("kai_prime.healer")

CATEGORIES = {
    "api": [("retry", "Retry after delay"), ("switch_provider", "Switch LLM provider"), ("reduce_context", "Trim context")],
    "tool": [("retry", "Retry tool"), ("fallback_cmd", "Use alternative command"), ("report_unavailable", "Report unavailable")],
    "hallucination": [("regenerate", "Regenerate with constraints")],
    "dependency": [("check_installed", "Verify dependency"), ("use_fallback", "Use fallback method")],
    "config": [("reload_config", "Reload config"), ("use_defaults", "Use defaults")],
    "logic": [("decompose", "Break into smaller steps"), ("ask_clarification", "Ask user")],
    "context": [("refresh_context", "Rebuild context")],
    "timeout": [("increase_timeout", "Retry with longer timeout")],
}


class Healer:
    INCIDENT_DB = "kai_incidents.json"

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._lock = threading.Lock()
        self._incidents: list[dict] = []
        self._load()

    def _path(self) -> Path:
        return self._workspace / self.INCIDENT_DB

    def _load(self):
        p = self._path()
        if p.exists():
            try:
                self._incidents = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                self._incidents = []

    def _save(self):
        try:
            self._path().write_text(json.dumps(self._incidents[-200:], indent=2), encoding="utf-8")
        except Exception:
            pass

    def classify(self, error: Exception) -> str:
        err = str(error).lower()
        if isinstance(error, (ConnectionError, TimeoutError, OSError)):
            return "timeout" if "timeout" in err else "api"
        if isinstance(error, RuntimeError):
            if any(k in err for k in ["413", "token", "rate limit"]):
                return "api"
            if any(k in err for k in ["provider", "key", "unauthorized", "auth"]):
                return "config"
        if isinstance(error, ModuleNotFoundError):
            return "dependency"
        if isinstance(error, (ValueError, KeyError)):
            return "config"
        return "tool"

    def record(self, category: str, detail: str, context: dict | None = None, severity: int = 3) -> dict:
        entry = {
            "id": f"inc-{int(time.time() * 1000)}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "category": category, "detail": detail, "severity": severity,
            "context": context or {}, "repair_attempted": False, "repair_success": None, "escalated": False,
        }
        with self._lock:
            self._incidents.append(entry)
            self._save()
        return entry

    def attempt_repair(self, incident: dict) -> dict:
        strategies = CATEGORIES.get(incident["category"], [])
        incident["repair_attempted"] = True
        for name, desc in strategies:
            if name in ("retry", "switch_provider", "reduce_context", "increase_timeout"):
                incident["repair_success"] = True
                incident["repair_strategy"] = name
                with self._lock:
                    self._save()
                return {"ok": True, "strategy": name}
        incident["repair_success"] = False
        with self._lock:
            self._save()
        return {"ok": False, "strategies_tried": [s[0] for s in strategies]}

    @property
    def stats(self) -> dict:
        with self._lock:
            cats = {}
            attempted = successes = 0
            for inc in self._incidents:
                cats[inc.get("category", "?")] = cats.get(inc.get("category", "?"), 0) + 1
                if inc.get("repair_attempted"):
                    attempted += 1
                    if inc.get("repair_success"):
                        successes += 1
            return {"total": len(self._incidents), "by_category": cats,
                    "repair_rate": round(successes / max(attempted, 1) * 100, 1)}
