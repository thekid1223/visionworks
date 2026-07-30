"""Outcome Ledger — persistent success/failure tracking across sessions.

Records every tool call, intent handler run, and auto-fix attempt with
outcome (success/fail), category, and context. Provides success-rate queries
so Kai can learn which approaches work best over time.
"""
import json
import threading
import time
from pathlib import Path


class OutcomeLedger:

    _MAX_CALLS_PER_KEY = 200

    def __init__(self, workspace: Path):
        self._path = Path(workspace) / "kai_prime_data" / "kai_outcomes.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict = {"tools": {}, "intents": {}, "fixes": {}}
        self._load()

    def record_tool(self, name: str, outcome: str, category: str = "", context: str = ""):
        with self._lock:
            entry = {"ts": time.time(), "outcome": outcome, "category": category, "ctx": context[:120]}
            bucket = self._data.setdefault("tools", {}).setdefault(name, {"calls": [], "ok": 0, "fail": 0})
            bucket["calls"].append(entry)
            if len(bucket["calls"]) > self._MAX_CALLS_PER_KEY:
                bucket["calls"] = bucket["calls"][-self._MAX_CALLS_PER_KEY:]
            if outcome == "success":
                bucket["ok"] += 1
            else:
                bucket["fail"] += 1
            self._save()

    def record_intent(self, name: str, outcome: str, category: str = "", context: str = ""):
        with self._lock:
            entry = {"ts": time.time(), "outcome": outcome, "category": category, "ctx": context[:120]}
            bucket = self._data.setdefault("intents", {}).setdefault(name, {"calls": [], "ok": 0, "fail": 0})
            bucket["calls"].append(entry)
            if len(bucket["calls"]) > self._MAX_CALLS_PER_KEY:
                bucket["calls"] = bucket["calls"][-self._MAX_CALLS_PER_KEY:]
            if outcome == "success":
                bucket["ok"] += 1
            else:
                bucket["fail"] += 1
            self._save()

    def record_fix(self, error_pattern: str, fix_name: str, worked: bool):
        with self._lock:
            entry = {"ts": time.time(), "fix": fix_name, "worked": worked}
            bucket = self._data.setdefault("fixes", {}).setdefault(error_pattern, {"calls": [], "ok": 0, "fail": 0})
            bucket["calls"].append(entry)
            if len(bucket["calls"]) > self._MAX_CALLS_PER_KEY:
                bucket["calls"] = bucket["calls"][-self._MAX_CALLS_PER_KEY:]
            if worked:
                bucket["ok"] += 1
            else:
                bucket["fail"] += 1
            self._save()

    def tool_success_rate(self, name: str, window: int = 0) -> float:
        return self._rate(self._data.get("tools", {}).get(name), window)

    def intent_success_rate(self, name: str, window: int = 0) -> float:
        return self._rate(self._data.get("intents", {}).get(name), window)

    def fix_success_rate(self, error_pattern: str, fix_name: str) -> float:
        bucket = self._data.get("fixes", {}).get(error_pattern)
        if not bucket or not bucket["calls"]:
            return 0.0
        total = 0
        ok = 0
        for c in bucket["calls"]:
            if c.get("fix") == fix_name:
                total += 1
                if c.get("worked"):
                    ok += 1
        return ok / total if total else 0.0

    def best_fix_for(self, error_pattern: str) -> str | None:
        bucket = self._data.get("fixes", {}).get(error_pattern)
        if not bucket or not bucket["calls"]:
            return None
        fix_rates: dict[str, list[bool]] = {}
        for c in bucket["calls"]:
            fn = c.get("fix", "")
            fix_rates.setdefault(fn, []).append(c.get("worked", False))
        best_fn = None
        best_rate = 0.0
        for fn, results in fix_rates.items():
            rate = sum(results) / len(results)
            if rate > best_rate:
                best_rate = rate
                best_fn = fn
        return best_fn if best_fn else None

    def worst_intents(self, n: int = 5, min_calls: int = 3) -> list[tuple[str, float]]:
        results = []
        for name, bucket in self._data.get("intents", {}).items():
            total = bucket.get("ok", 0) + bucket.get("fail", 0)
            if total >= min_calls:
                rate = bucket["ok"] / total
                results.append((name, rate))
        results.sort(key=lambda x: x[1])
        return results[:n]

    def trending_down(self, n: int = 3) -> list[str]:
        down = []
        for kind in ("tools", "intents"):
            for name, bucket in self._data.get(kind, {}).items():
                calls = bucket.get("calls", [])
                if len(calls) < 8:
                    continue
                recent = calls[-5:]
                recent_ok = sum(1 for c in recent if c.get("outcome") == "success")
                recent_rate = recent_ok / len(recent)
                lifetime_ok = bucket.get("ok", 0)
                lifetime_total = lifetime_ok + bucket.get("fail", 0)
                lifetime_rate = lifetime_ok / lifetime_total if lifetime_total else 0
                if lifetime_rate > 0.3 and recent_rate < lifetime_rate * 0.6:
                    down.append(f"{kind[:-1]}:{name}")
        return down[:n]

    def summary(self) -> dict:
        tools = self._data.get("tools", {})
        intents = self._data.get("intents", {})
        fixes = self._data.get("fixes", {})
        tool_rates = {}
        for name, bucket in tools.items():
            total = bucket.get("ok", 0) + bucket.get("fail", 0)
            tool_rates[name] = round(bucket["ok"] / total, 2) if total else 0.0
        return {
            "tools_tracked": len(tools),
            "intents_tracked": len(intents),
            "fixes_tracked": len(fixes),
            "tool_rates": tool_rates,
            "trending_down": self.trending_down(),
        }

    def _load(self):
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {"tools": {}, "intents": {}, "fixes": {}}

    def _save(self):
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    @staticmethod
    def _rate(bucket: dict | None, window: int) -> float:
        if not bucket:
            return 0.0
        calls = bucket.get("calls", [])
        if window > 0:
            calls = calls[-window:]
        if not calls:
            return 0.0
        ok = sum(1 for c in calls if c.get("outcome") == "success")
        return ok / len(calls)
