"""Error Recovery — episode memory + pattern-based fix suggestion."""
from __future__ import annotations
import json, logging, re, threading
from pathlib import Path
from datetime import datetime, timezone
from kai_prime.config import MEMORY_DIR, MAX_EPISODES

log = logging.getLogger("kai_prime.error_recovery")

class EpisodeStore:
    def __init__(self, workspace: Path | None = None, max_episodes: int = MAX_EPISODES):
        self._path = MEMORY_DIR / "episodes.json"
        self._lock = threading.Lock()
        self._max = max_episodes
        self._episodes: list[dict] = []
        self._load()

    def record(self, summary: str, outcome: str, context: str = "", error: str = "", fix: str = "", intent: str = "") -> dict:
        ep = {"ts": datetime.now(timezone.utc).isoformat(), "summary": summary[:200], "outcome": outcome[:100],
              "context": context[:500], "error": error[:1000], "fix": fix[:500], "intent": intent}
        with self._lock:
            self._episodes.append(ep)
            if len(self._episodes) > self._max:
                self._episodes = self._episodes[-self._max:]
            self._save()
        return ep

    def recent(self, limit: int = 10, intent: str = "") -> list[dict]:
        with self._lock:
            eps = self._episodes
            if intent:
                eps = [e for e in eps if e.get("intent") == intent]
            return list(eps[-limit:])

    def failures(self, limit: int = 10) -> list[dict]:
        with self._lock:
            failed = [e for e in self._episodes if e.get("outcome", "").lower() in ("fail", "error", "timeout")]
            return list(failed[-limit:])

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._episodes = data.get("episodes", [])
        except Exception as e:
            log.warning("Failed to load episodes: %s", e)
            self._episodes = []

    def _save(self):
        try:
            self._path.write_text(json.dumps({"episodes": self._episodes[-self._max:]}, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save episodes: %s", e)


class ErrorFix:
    def __init__(self, workspace: Path | None = None):
        self._path = MEMORY_DIR / "error_fixes.json"
        self._lock = threading.Lock()
        self._patterns: list[dict] = []
        self._load()

    def learn(self, error_text: str, fix: str, tool: str = "", error_type: str = "generic") -> dict:
        pattern = self._make_pattern(error_text)
        if not pattern:
            return {"ok": False, "error": "Empty error text"}
        entry = {"pattern": pattern, "example": error_text[:300], "fix": fix[:500], "tool": tool,
                 "error_type": error_type, "ts": datetime.now(timezone.utc).isoformat(), "hit_count": 0}
        with self._lock:
            self._patterns.append(entry)
            self._save()
        return {"ok": True, "pattern": pattern}

    def suggest(self, error_text: str, top_n: int = 3) -> list[dict]:
        if not error_text:
            return []
        lowered = error_text.lower()
        matches: list[tuple[float, dict]] = []
        with self._lock:
            for entry in self._patterns:
                score = self._score_match(lowered, entry)
                if score > 0:
                    matches.append((score, entry))
        matches.sort(key=lambda x: -x[0])
        suggestions = []
        for score, entry in matches[:top_n]:
            suggestions.append({"fix": entry["fix"], "tool": entry.get("tool", ""), "confidence": round(score, 2)})
            entry["hit_count"] = entry.get("hit_count", 0) + 1
        if suggestions:
            with self._lock:
                self._save()
        return suggestions

    @staticmethod
    def _make_pattern(text: str) -> str:
        if not text.strip():
            return ""
        t = text.strip()[:200]
        t = re.sub(r"'[^']*'", "'<val>'", t)
        t = re.sub(r'"[^"]*"', '"<val>"', t)
        t = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<ip>", t)
        t = re.sub(r"\b\d{4,}\b", "<num>", t)
        return t[:200]

    def _score_match(self, lowered: str, entry: dict) -> float:
        example = entry.get("example", "").lower()
        if not example:
            return 0.0
        con_words = set(re.findall(r"\w+", lowered))
        pat_words = set(re.findall(r"\w+", example))
        if con_words and pat_words:
            return len(con_words & pat_words) / max(len(con_words), len(pat_words))
        return 0.0

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._patterns = data.get("patterns", [])
        except Exception as e:
            log.warning("Failed to load error patterns: %s", e)
            self._patterns = []

    def _save(self):
        try:
            self._path.write_text(json.dumps({"patterns": self._patterns}, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save error patterns: %s", e)
