"""Ritual Engine v2 — frequency-based sequence miner with parameterized macros.

New pattern detection uses frequency analysis instead of sliding window:
  - Tracks n-gram frequencies (trigrams through hexgrams)
  - Auto-creates ritual when same sequence repeats 3+ times
  - Supports parameterized commands (e.g., "nmap {IP}" instead of exact match)
  - Steps remember which parts are parameters and auto-fill them on re-run
"""
from __future__ import annotations

import json
import re
import time
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

log = logging.getLogger("kai_prime.rituals")

_PARAM_PATTERNS = re.compile(r"(\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[a-z0-9.-]+\.[a-z]{2,}\b|\b[a-f0-9]{8,}\b|'.*?'|\".*?\")", re.IGNORECASE)


class RitualEngine:
    """Frequency-based pattern detector with parameterized macros."""

    def __init__(self, workspace: Path, execute_fn: Callable = None):
        self._workspace = workspace
        self._data_file = workspace / "kai_prime_data" / "rituals.json"
        self._freq_file = workspace / "kai_prime_data" / "ritual_frequencies.json"
        self._execute_fn = execute_fn
        self._recent: list[dict] = []
        self._max_history = 100
        self._rituals: dict[str, dict] = {}
        self._freq: dict[str, int] = Counter()
        self._load()

    def _load(self):
        try:
            if self._data_file.exists():
                self._rituals = json.loads(self._data_file.read_text(encoding="utf-8"))
        except Exception:
            self._rituals = {}
        try:
            if self._freq_file.exists():
                self._freq = Counter(json.loads(self._freq_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    def _save(self):
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            self._data_file.write_text(json.dumps(self._rituals, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _save_freq(self):
        try:
            self._freq_file.parent.mkdir(parents=True, exist_ok=True)
            self._freq_file.write_text(json.dumps(dict(self._freq)), encoding="utf-8")
        except Exception:
            pass

    def set_execute_fn(self, fn: Callable):
        self._execute_fn = fn

    def _parameterize(self, command: str) -> tuple[str, dict]:
        """Replace common parameters with {N} placeholders."""
        params = {}
        def _replacer(m):
            idx = len(params) + 1
            key = f"P{idx}"
            params[key] = m.group(0)
            return f"{{{key}}}"
        cmd = _PARAM_PATTERNS.sub(_replacer, command)
        return cmd, params

    def _fill_params(self, command: str, params: dict) -> str:
        for key, val in params.items():
            command = command.replace(f"{{{key}}}", val)
        return command

    def record(self, command: str, intent: str, result: str):
        """Record a command execution for pattern detection."""
        cmd_param, params = self._parameterize(command)
        entry = {
            "timestamp": time.time(),
            "command": command,
            "cmd_param": cmd_param,
            "params": params,
            "intent": intent,
            "result_preview": result[:100],
            "success": "error" not in result.lower()[:200],
        }
        self._recent.append(entry)
        if len(self._recent) > self._max_history:
            self._recent = self._recent[-self._max_history:]

        # Track n-gram frequencies (trigrams through hexgrams)
        if len(self._recent) >= 3:
            recent_list = self._recent[-30:]
            intents = [e["intent"] for e in recent_list]
            cmds = [e["cmd_param"] for e in recent_list]

            for n in [3, 4, 5]:
                for i in range(len(intents) - n + 1):
                    key = "||".join(intents[i:i+n])
                    self._freq[key] += 1

        self._save_freq()
        self._detect_from_frequencies()

    def _detect_from_frequencies(self):
        """Find frequent n-grams and create rituals."""
        for key, count in self._freq.most_common(10):
            if count >= 3 and count % 3 == 0:
                parts = key.split("||")
                if len(parts) >= 3:
                    name = " → ".join(parts)
                    name_clean = f"auto_{name.lower().replace(' ', '_')[:60]}"
                    if name_clean not in self._rituals:
                        steps = []
                        recent_list = self._recent[-30:]
                        for intent in parts:
                            matched = [e for e in recent_list if e["intent"] == intent]
                            if matched:
                                e = matched[-1]
                                steps.append({
                                    "command": e["cmd_param"],
                                    "intent": e["intent"],
                                    "params": e.get("params", {}),
                                })
                        if len(steps) == len(parts):
                            self._rituals[name_clean] = {
                                "steps": steps,
                                "uses": 0,
                                "created": time.time(),
                                "auto": True,
                                "frequency": count,
                            }
                            self._save()
                            log.info("Auto-created ritual: %s (%d steps, freq=%d)",
                                     name_clean, len(steps), count)

    def create_ritual(self, name: str, steps: list[dict]) -> str:
        """Manually create a ritual."""
        name_clean = name.lower().replace(" ", "_")[:60]
        if name_clean in self._rituals:
            return f"Ritual '{name_clean}' already exists."
        processed = []
        for s in steps:
            cmd_param, params = self._parameterize(s.get("command", ""))
            processed.append({
                "command": cmd_param,
                "intent": s.get("intent", ""),
                "params": params,
            })
        self._rituals[name_clean] = {
            "steps": processed,
            "uses": 0,
            "created": time.time(),
            "auto": False,
        }
        self._save()
        return f"Ritual '{name_clean}' saved ({len(steps)} steps)."

    def run_ritual(self, name: str, **kwargs) -> str:
        """Execute a ritual's steps in sequence."""
        ritual = self._rituals.get(name)
        if not ritual:
            return f"No ritual found: '{name}'. Use list_rituals to see available ones."
        if not self._execute_fn:
            return "No execution function available."
        steps = ritual["steps"]
        lines = [f"══ Ritual: {name} ({len(steps)} steps) ══"]
        success = 0
        fail = 0
        for i, step in enumerate(steps, 1):
            cmd = step.get("command", "")
            base_cmd = step.get("command", "")
            params = step.get("params", {})
            # Fill params from the first run's saved values
            cmd = self._fill_params(base_cmd, params)
            if not cmd:
                continue
            try:
                result = self._execute_fn(cmd)
                preview = str(result)[:200]
                ok = "error" not in preview.lower()[:100]
                lines.append(f"  [{i}/{len(steps)}] {cmd[:50]} → {'OK' if ok else 'FAIL'}")
                if ok:
                    success += 1
                else:
                    fail += 1
            except Exception as e:
                lines.append(f"  [{i}/{len(steps)}] {cmd[:50]} → ERROR: {e}")
                fail += 1
        ritual["uses"] = ritual.get("uses", 0) + 1
        self._save()
        lines.append(f"── {success} success, {fail} failed ──")
        return "\n".join(lines)

    def list_rituals(self) -> list[dict]:
        result = []
        for name, ritual in self._rituals.items():
            result.append({
                "name": name,
                "steps": len(ritual.get("steps", [])),
                "uses": ritual.get("uses", 0),
                "auto": ritual.get("auto", False),
                "frequency": ritual.get("frequency", 0),
            })
        return sorted(result, key=lambda x: (-x["uses"], x["name"]))

    def delete_ritual(self, name: str) -> str:
        if name in self._rituals:
            del self._rituals[name]
            self._save()
            return f"Ritual '{name}' deleted."
        return f"Ritual '{name}' not found."

    def suggest_ritual(self, command: str) -> str:
        cmd_p, _ = self._parameterize(command)
        for name, ritual in self._rituals.items():
            if name.startswith("auto_"):
                continue
            if name.lower() in command.lower() or command.lower() in name.lower():
                return f"I know a ritual for that: '{name}'. Say 'run ritual {name}' to execute."
        return ""

    def status(self) -> dict:
        return {
            "total_rituals": len(self._rituals),
            "auto_created": sum(1 for r in self._rituals.values() if r.get("auto")),
            "total_uses": sum(r.get("uses", 0) for r in self._rituals.values()),
            "patterns_tracked": len(self._freq),
            "history_size": len(self._recent),
            "mode": "frequency-based",
        }
