"""Session state — persists across restarts, detects crashes."""
from __future__ import annotations
import json, logging, threading, time
from pathlib import Path
from kai_prime.config import KAI_DATA

log = logging.getLogger("kai_prime.session")

class SessionState:
    def __init__(self):
        self.path = KAI_DATA / "session_state.json"
        self._lock = threading.RLock()
        self._state = self._load()
        self._is_restored = False

    def _default(self) -> dict:
        return {"version": 1, "clean_shutdown": True, "crash_count": 0,
                "session_count": 0, "last_start": None, "last_active": None,
                "operations": [], "errors": [],
                "last_user_input": None, "last_kai_response": None, "last_intent": None}

    def _load(self) -> dict:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("version") == 1:
                    return data
        except Exception as e:
            log.warning("Failed to load session state: %s", e)
        return self._default()

    def save(self):
        with self._lock:
            self._state["last_active"] = time.time()
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
                tmp.replace(self.path)
            except Exception as e:
                log.warning("Failed to save session state: %s", e)

    def mark_start(self):
        with self._lock:
            was_clean = self._state.get("clean_shutdown", True)
            if not was_clean:
                self._state["crash_count"] = self._state.get("crash_count", 0) + 1
            self._state["clean_shutdown"] = False
            self._state["last_start"] = time.time()
            self._state["session_count"] = self._state.get("session_count", 0) + 1
            self._is_restored = not was_clean
        self.save()

    def mark_shutdown(self):
        with self._lock:
            self._state["clean_shutdown"] = True
            self.save()

    def push_operation(self, op: str, status: str, error: str | None = None):
        with self._lock:
            ops = [o for o in self._state.get("operations", []) if o.get("op") != op]
            ops.append({"op": op, "status": status, "error": error, "timestamp": time.time()})
            ops.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            self._state["operations"] = ops[:20]
            self.save()

    def push_error(self, error: str, category: str = "unknown", tool: str = ""):
        with self._lock:
            errors = self._state.get("errors", [])
            key = error[:200]
            for e in errors:
                if e.get("message") == key:
                    e["count"] = e.get("count", 0) + 1
                    e["last_seen"] = time.time()
                    break
            else:
                errors.append({"message": key, "category": category, "count": 1, "last_seen": time.time(), "tool": tool})
            errors.sort(key=lambda x: x.get("last_seen", 0), reverse=True)
            self._state["errors"] = errors[:20]
            self.save()

    def update_context(self, user_input: str, response: str, intent: str):
        with self._lock:
            self._state["last_user_input"] = (user_input or "")[:500]
            self._state["last_kai_response"] = (response or "")[:500]
            self._state["last_intent"] = intent
            self.save()

    def get_previous_session(self) -> dict:
        with self._lock:
            was_crash = not self._state.get("clean_shutdown", True)
            ops = self._state.get("operations", [])
            pending = [o for o in ops if o.get("status") in ("running", "failed")]
            if not was_crash and not pending:
                return {}
            return {"was_crash": was_crash, "crash_count": self._state.get("crash_count", 0),
                    "last_intent": self._state.get("last_intent"),
                    "last_user_input": self._state.get("last_user_input"),
                    "pending_ops": pending}

    def is_restore(self) -> bool:
        return self._is_restored
