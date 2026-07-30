"""Supervisor — pre-flight review layer for killchain and tool execution."""
from __future__ import annotations
import json, os, re, threading, subprocess
from datetime import datetime
from pathlib import Path
from kai_prime.config import BRIDGE_PATH, CRITICAL_RANGES, DESTRUCTIVE_MODULES, SUPERVISOR_DEFAULT_ACTIVE

class Supervisor:
    def __init__(self, bridge_path: Path | None = None):
        self._bridge_path = bridge_path or BRIDGE_PATH
        self._lock = threading.RLock()
        self._audit: list[dict] = []
        self._op_log: list[dict] = []
        self._active = SUPERVISOR_DEFAULT_ACTIVE
        self._load_state()

    def _load_state(self):
        try:
            if self._bridge_path.exists():
                data = json.loads(self._bridge_path.read_text(encoding="utf-8"))
                self._active = data.get("supervisor_active", SUPERVISOR_DEFAULT_ACTIVE)
        except Exception:
            self._active = SUPERVISOR_DEFAULT_ACTIVE

    def _save_state(self):
        try:
            data = {}
            if self._bridge_path.exists():
                data = json.loads(self._bridge_path.read_text(encoding="utf-8"))
            data["supervisor_active"] = self._active
            self._bridge_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @property
    def active(self) -> bool:
        return self._active

    def activate(self):
        with self._lock:
            self._active = True
            self._save_state()
            self._log("system", "activate", "Supervisor activated")

    def deactivate(self):
        with self._lock:
            self._active = False
            self._save_state()
            self._log("system", "deactivate", "Supervisor deactivated")

    def toggle(self) -> bool:
        if self.active:
            self.deactivate()
        else:
            self.activate()
        return self.active

    def review(self, phase: str, context: dict) -> dict:
        if phase == "response":
            if not self.active:
                return {"ok": True, "reason": "", "suggestion": ""}
            return self._review_response(context)
        elif not self.active:
            return {"ok": True, "reason": "", "suggestion": ""}
        checker = getattr(self, f"_review_{phase}", None)
        result = checker(context) if checker else {"ok": True, "reason": "", "suggestion": ""}
        if not result["ok"]:
            self._log("block", phase, f"BLOCKED: {result['reason']}", context)
        else:
            self._log("pass", phase, "PASSED", context)
        return result

    def _review_validate(self, ctx: dict) -> dict:
        ip = ctx.get("ip", "")
        gateway = ctx.get("gateway", "")
        if ip == gateway or ip in CRITICAL_RANGES:
            return {"ok": False, "reason": f"Target {ip} is critical infrastructure", "suggestion": "Choose a non-infrastructure target"}
        if ip.endswith(".255") or ip.endswith(".0"):
            return {"ok": False, "reason": f"Target {ip} is broadcast/network address", "suggestion": "Use a host IP"}
        local_ip = ctx.get("local_ip", "")
        if local_ip:
            local_prefix = ".".join(local_ip.split(".")[:3])
            if not ip.startswith(local_prefix):
                return {"ok": False, "reason": f"Target {ip} outside local subnet", "suggestion": "Only target same-subnet hosts"}
        return {"ok": True, "reason": "", "suggestion": ""}

    def _review_scan(self, ctx: dict) -> dict:
        ports = ctx.get("ports", [])
        if len(ports) > 20:
            return {"ok": False, "reason": f"{len(ports)} open ports — may be honeypot", "suggestion": "Verify target is real"}
        return {"ok": True, "reason": "", "suggestion": ""}

    def _review_match(self, ctx: dict) -> dict:
        module = ctx.get("module", {})
        name = module.get("name", "")
        if name in DESTRUCTIVE_MODULES:
            return {"ok": False, "reason": f"Module {name} is highly destructive", "suggestion": "Confirm destructive intent"}
        return {"ok": True, "reason": "", "suggestion": ""}

    def _review_exploit(self, ctx: dict) -> dict:
        module = ctx.get("module", {})
        payload = ctx.get("payload", module.get("payload", ""))
        if "reverse_tcp" in payload or "reverse_https" in payload:
            return {"ok": False, "reason": f"Payload {payload} establishes persistent access", "suggestion": "Confirm persistence is intended"}
        return {"ok": True, "reason": "", "suggestion": ""}

    _ACTION_CLAIMS = re.compile(
        r'\bI( just| already| have)? '
        r'(checked|scanned|searched|updated|modified|ran|executed|sent|wrote|created|'
        r'deleted|removed|installed|configured|started|stopped|opened|closed|saved|'
        r'loaded|fetched|rebooted|refreshed|restarted|cleaned|fixed|patched|generated|'
        r'looked\s+up|queried|downloaded|uploaded|synced|terminated|launched|setup|'
        r'killed|disabled|enabled|pressed|clicked|typed|moved|copied|pasted|renamed|'
        r'restored|backed\s+up)\b',
        re.IGNORECASE
    )

    def _review_response(self, ctx: dict) -> dict:
        text = ctx.get("text", "")
        if not text or not isinstance(text, str) or len(text.strip()) < 5:
            return {"ok": False, "reason": "Empty or too-short response", "suggestion": "Regenerate"}
        lower = text.lower()
        error_pats = [r'\[Errno \d+\]', r'Traceback', r'All providers unavailable']
        for pat in error_pats:
            if re.search(pat, text):
                return {"ok": False, "reason": "Raw error leaked", "suggestion": "Rephrase naturally"}
        self_censor = ["i cannot", "i'm unable to", "as an ai", "i'm just an ai"]
        for phrase in self_censor:
            if phrase in lower:
                return {"ok": False, "reason": f"Self-censorship: '{phrase}'", "suggestion": "Rephrase without refusal"}
        # Hallucination check: action claims without tool evidence
        tool_was_called = ctx.get("tool_was_called", False)
        if not tool_was_called:
            claims = self._ACTION_CLAIMS.findall(text)
            if claims:
                return {
                    "ok": False,
                    "reason": f"Hallucinated action claims without tool call: {', '.join(set(claims))}",
                    "suggestion": "Rewrite: only describe what was actually done (nothing was). Say you cannot do it or explain why."
                }
        return {"ok": True, "reason": "", "suggestion": ""}

    def _review_tool(self, ctx: dict) -> dict:
        tool = ctx.get("tool", "")
        args = ctx.get("args", {})
        if tool == "run_command":
            cmd = args.get("command", "").lower()
            dangerous = ["rm -rf", "format", "del /f /s", "rd /s /q", "shutdown"]
            for d in dangerous:
                if d in cmd:
                    return {"ok": False, "reason": f"Dangerous command: '{d}'", "suggestion": "Reject or wrap with confirmation"}
        if tool == "write_file":
            path = args.get("path", args.get("file_path", "")).lower()
            critical = ["kai_config.json", "kai_bridge.json", "episodes.json", "error_fixes.json"]
            for c in critical:
                if c in path:
                    return {"ok": False, "reason": f"Attempted to overwrite critical file: {c}", "suggestion": "Use a different path"}
        return {"ok": True, "reason": "", "suggestion": ""}

    def log_op_start(self, op: str, target: str = "", details: str = ""):
        with self._lock:
            self._op_log.append({"op": op, "target": target, "status": "running", "details": details, "started_at": datetime.now().isoformat()})

    def log_op_complete(self, op: str, message: str = ""):
        with self._lock:
            for entry in reversed(self._op_log):
                if entry["op"] == op and entry["status"] == "running":
                    entry["status"] = "complete"
                    entry["message"] = message
                    break

    def log_op_fail(self, op: str, error: str = ""):
        with self._lock:
            for entry in reversed(self._op_log):
                if entry["op"] == op and entry["status"] == "running":
                    entry["status"] = "failed"
                    entry["error"] = error
                    break

    def get_summary(self) -> dict:
        with self._lock:
            total = len(self._audit)
            blocked = sum(1 for e in self._audit if e["action"] == "block")
            passed = sum(1 for e in self._audit if e["action"] == "pass")
            running = sum(1 for e in self._op_log if e["status"] == "running")
            failed = sum(1 for e in self._op_log if e["status"] == "failed")
            completed = sum(1 for e in self._op_log if e["status"] == "complete")
            return {"active": self.active, "total_reviews": total, "blocked": blocked, "passed": passed,
                    "ops_running": running, "ops_failed": failed, "ops_completed": completed}

    def get_audit(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return list(self._audit[-limit:])

    def _log(self, action: str, phase: str, detail: str, context: dict | None = None):
        entry = {"ts": datetime.now().isoformat(), "action": action, "phase": phase, "detail": detail, "context": context or {}}
        with self._lock:
            self._audit.append(entry)
            if len(self._audit) > 500:
                self._audit = self._audit[-500:]
