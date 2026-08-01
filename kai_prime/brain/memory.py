"""Memory system — summary buffer + entity memory + FTS5 cross-session search."""
from __future__ import annotations
import json, logging, threading, time
from pathlib import Path
from kai_prime.config import MEMORY_DIR, MAX_CONTEXT_TOKENS, KEEP_RECENT_TURNS

log = logging.getLogger("kai_prime.memory")


class Memory:
    """Summary buffer: recent turns verbatim, older turns compressed to summary."""
    def __init__(self):
        self._path = MEMORY_DIR / "conversation_memory.json"
        self._lock = threading.Lock()
        self.summary: str = ""
        self.recent: list[dict] = []
        self.entities: dict[str, str] = {}
        self._search = None
        self._load()
        self._init_search()

    def _init_search(self):
        try:
            from kai_prime.brain.memory_search import MemorySearch
            self._search = MemorySearch(Path(str(self._path.parent.parent)))
        except Exception as e:
            log.warning("MemorySearch not loaded: %s", e)

    def add(self, role: str, content: str):
        with self._lock:
            self.recent.append({"role": role, "content": content, "ts": time.time()})
            if len(self.recent) > 100:
                self.recent = self.recent[-100:]
            self._save()

    def store_turn(self, user_input: str, response: str, session_id: str = "current", tags: list[str] | None = None):
        if self._search:
            try:
                from kai_prime.brain.memory_search import MemoryFragment
                import uuid
                frag = MemoryFragment(
                    id=str(uuid.uuid4())[:12],
                    session_id=session_id,
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    user_input=user_input[:2000],
                    kai_response=response[:2000],
                    tags=tags or [],
                )
                self._search.store(frag)
            except Exception as e:
                log.warning("Failed to store turn in FTS5: %s", e)

    def search_similar(self, query: str, limit: int = 5) -> list[dict]:
        if self._search:
            try:
                return self._search.search(query, limit=limit)
            except Exception as e:
                log.warning("FTS5 search failed: %s", e)
        return []

    def find_similar_conversations(self, context: str, limit: int = 5) -> list[dict]:
        if self._search:
            try:
                return self._search.find_similar(context, limit=limit)
            except Exception:
                pass
        return []

    def get_context(self, max_tokens: int = MAX_CONTEXT_TOKENS) -> list[dict]:
        with self._lock:
            ctx = []
            if self.summary:
                ctx.append({"role": "system", "content": f"Earlier context: {self.summary}"})
            entity_ctx = self._build_entity_context()
            if entity_ctx:
                ctx.append({"role": "system", "content": entity_ctx})
            recent = self.recent[-KEEP_RECENT_TURNS:]
            ctx.extend([{"role": m["role"], "content": m["content"]} for m in recent])
            return ctx

    def get_recall_context(self, user_input: str, max_results: int = 3) -> str:
        results = self.search_similar(user_input, limit=max_results)
        if not results:
            return ""
        parts = ["[RELEVANT PAST CONVERSATIONS]"]
        for r in results:
            ts = r.get("timestamp", "")[:10]
            ui = r.get("user_input", "")[:150]
            resp = r.get("kai_response", "")[:200]
            parts.append(f"  [{ts}] User: {ui}")
            parts.append(f"  [{ts}] Kai: {resp}")
        return "\n".join(parts)

    def compress(self, summarize_fn) -> bool:
        with self._lock:
            if len(self.recent) <= KEEP_RECENT_TURNS + 2:
                return False
            to_compress = self.recent[:-KEEP_RECENT_TURNS]
            self.recent = self.recent[-KEEP_RECENT_TURNS:]
            lines = []
            for m in to_compress:
                prefix = "User" if m["role"] == "user" else "Kai"
                lines.append(f"{prefix}: {m['content'][:200]}")
            old = self.summary + "\n" if self.summary else ""
            self.summary = (summarize_fn(old + "\n".join(lines)) or "")[:4000]
            self._save()
            return True

    def _build_entity_context(self) -> str:
        if not self.entities:
            return ""
        lines = [f"- {k}: {v}" for k, v in self.entities.items()]
        return "Known context:\n" + "\n".join(lines)

    def update_entities(self, key: str, value: str):
        with self._lock:
            self.entities[key] = value
            self._save()

    def recent_failures(self, limit: int = 5) -> list[dict]:
        with self._lock:
            return [m for m in self.recent if m.get("role") == "system" and "FAIL" in m.get("content", "").upper()][-limit:]

    def _save(self):
        try:
            data = {"summary": self.summary, "recent": self.recent[-KEEP_RECENT_TURNS:], "entities": self.entities}
            self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save memory: %s", e)

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self.summary = data.get("summary", "")
                self.recent = data.get("recent", [])
                self.entities = data.get("entities", {})
        except Exception as e:
            log.warning("Failed to load memory: %s", e)

    def seed_from_session(self, user_input: str, response: str):
        if user_input and response:
            self.recent.append({"role": "user", "content": user_input, "ts": time.time()})
            self.recent.append({"role": "assistant", "content": response, "ts": time.time()})
            self.store_turn(user_input, response)
            self._save()

    def get_search_stats(self) -> dict:
        if self._search:
            try:
                return {"fts5_count": self._search.count()}
            except Exception:
                pass
        return {"fts5_count": 0}


class EntityMemory:
    """Key-value store for user facts, with per-key value history for disambiguation."""
    def __init__(self, path: Path | None = None):
        self._path = path or MEMORY_DIR / "entities.json"
        self._lock = threading.Lock()
        self._entities: dict[str, list[dict]] = {}
        self._load()

    def set(self, key: str, value: str):
        with self._lock:
            value = (value or "").strip()
            if not value:
                return
            hist = self._entities.get(key, [])
            for i, rec in enumerate(hist):
                if rec["value"].lower() == value.lower():
                    rec["count"] += 1
                    rec["ts"] = time.time()
                    if i > 0:
                        hist.pop(i)
                        hist.insert(0, rec)
                    self._save()
                    return
            hist.insert(0, {"value": value, "ts": time.time(), "count": 1})
            self._entities[key] = hist[:10]
            self._save()

    def get(self, key: str) -> str:
        hist = self._entities.get(key) or []
        return hist[0]["value"] if hist else ""

    def get_history(self, key: str) -> list[dict]:
        return list(self._entities.get(key) or [])

    def extract_and_store(self, text: str):
        import re
        patterns = {
            "user_name": r"(?:my name is|call me|i'm|im)\s+([A-Za-z]{2,20})",
            "project": r"(?:working on|building|coding|project)\s+(.{5,50})",
            "preference": r"(?:i prefer|i like|i want|i need)\s+(.{3,80})",
        }
        for key, pat in patterns.items():
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip().rstrip(".,;:!?")
                if len(val) > 3 and val.lower() not in ("just", "really", "going", "trying", "looking"):
                    self.set(key, val)

    def get_all(self) -> dict[str, str]:
        with self._lock:
            return {k: (v[0]["value"] if v else "") for k, v in self._entities.items()}

    def get_context_string(self) -> str:
        with self._lock:
            if not self._entities:
                return ""
            lines = []
            for key, hist in self._entities.items():
                if not hist:
                    continue
                current = hist[0]["value"]
                distinct = {r["value"].lower() for r in hist}
                if len(distinct) > 1:
                    others = []
                    seen = set()
                    for r in hist:
                        low = r["value"].lower()
                        if low != current.lower() and low not in seen:
                            seen.add(low)
                            others.append(r["value"])
                    lines.append(f"- {key}: {current} (also known as: {', '.join(others)} — ask which is correct)")
                else:
                    lines.append(f"- {key}: {current}")
            return "\n".join(lines)

    def _save(self):
        try:
            self._path.write_text(json.dumps(self._entities, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save entities: %s", e)

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                migrated = {}
                for k, v in data.items():
                    if isinstance(v, list):
                        migrated[k] = v
                    elif isinstance(v, str):
                        migrated[k] = [{"value": v, "ts": time.time(), "count": 1}]
                    else:
                        migrated[k] = []
                self._entities = migrated
        except Exception as e:
            log.warning("Failed to load entities: %s", e)
