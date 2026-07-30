"""Knowledge Base — persistent TF-IDF knowledge store. Learns from every interaction."""
from __future__ import annotations
import json, logging, math, re, time
from collections import Counter
from pathlib import Path

log = logging.getLogger("kai_prime.knowledge")

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out", "off",
    "over", "under", "again", "then", "here", "there", "when", "where",
    "how", "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "because", "but", "and", "or", "if", "while",
    "this", "that", "these", "those", "it", "its", "i", "me", "my", "we",
    "our", "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "what", "which", "who", "whom", "about", "up", "get", "got",
    "like", "make", "made", "want", "know", "think", "see", "look", "come",
    "go", "take", "let", "say", "tell", "ask", "try", "leave", "call",
    "give", "use", "find", "need", "set", "put", "move", "work", "show",
    "turn", "run",
}


class KnowledgeBase:
    """TF-IDF knowledge base with typed entries and cosine similarity search."""

    def __init__(self, workspace: Path, max_entries: int = 10000):
        self.workspace = workspace
        self.path = workspace / "kai_prime_data" / "knowledge.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self._entries: list[dict] = []
        self._next_id = 0
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    self._entries.append(entry)
                    eid = entry.get("id", 0)
                    if eid > self._next_id:
                        self._next_id = eid
        except Exception as e:
            log.warning("Knowledge base load failed: %s", e)

    def _save(self):
        tmp = self.path.with_suffix(".jsonl.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                for entry in self._entries[-self.max_entries:]:
                    f.write(json.dumps(entry, default=str) + "\n")
            tmp.replace(self.path)
        except Exception as e:
            log.warning("Knowledge base save failed: %s", e)

    def add(self, entry_type: str, input_text: str, output_text: str, context: str = "", tags: list[str] | None = None):
        self._next_id += 1
        combined = f"{input_text} {output_text} {context}"
        entry = {
            "id": self._next_id, "type": entry_type,
            "timestamp": time.time(),
            "input": input_text[:2000], "output": output_text[:2000],
            "context": context[:1000], "tags": tags or [],
            "keywords": self._extract_keywords(combined),
        }
        self._entries.append(entry)
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]
        self._save()

    def add_chat(self, user_input: str, reply: str, context: str = ""):
        self.add("chat", user_input, reply, context, ["chat"])

    def add_scan(self, scan_type: str, target: str, result: str):
        self.add("scan", f"{scan_type}: {target}", result, "", ["scan", scan_type])

    def add_command(self, command: str, result: str, success: bool):
        self.add("command" if success else "error", command, result, "", ["command"])

    def add_error(self, error_context: str, error_msg: str):
        self.add("error", error_context, error_msg, "", ["error"])

    def add_knowledge(self, topic: str, content: str):
        self.add("knowledge", topic, content, "", ["knowledge"])

    def search(self, query: str, top_n: int = 5) -> list[dict]:
        if not self._entries or not query.strip():
            return []
        query_kw = self._extract_keywords(query)
        if not query_kw:
            return []
        scored = []
        for entry in self._entries:
            score = self._similarity(query_kw, entry.get("keywords", {}))
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: -x[0])
        seen = set()
        results = []
        for score, entry in scored[:top_n * 2]:
            inp = entry.get("input", "")
            if inp in seen:
                continue
            seen.add(inp)
            entry["_score"] = round(score, 3)
            results.append(entry)
            if len(results) >= top_n:
                break
        return results

    def build_context(self, query: str, max_results: int = 3) -> str:
        results = self.search(query, top_n=max_results)
        if not results:
            return ""
        parts = ["[KNOWLEDGE BASE — past interactions relevant to this query]"]
        for r in results:
            rtype = r.get("type", "note")
            inp = r.get("input", "")[:200]
            out = r.get("output", "")[:300]
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.get("timestamp", 0)))
            parts.append(f"  [{ts}] ({rtype}): \"{inp}\" -> {out}")
        return "\n".join(parts)

    def stats(self) -> dict:
        types = Counter(e.get("type", "unknown") for e in self._entries)
        return {"total_entries": len(self._entries), "by_type": dict(types)}

    @staticmethod
    def _extract_keywords(text: str) -> dict[str, float]:
        text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
        words = text.split()
        filtered = [w for w in words if w not in STOPWORDS and len(w) > 2]
        total = len(filtered)
        if not total:
            return {}
        counts = Counter(filtered)
        return {word: count / total for word, count in counts.items()}

    @staticmethod
    def _similarity(v1: dict[str, float], v2: dict[str, float]) -> float:
        if not v1 or not v2:
            return 0.0
        common = set(v1) & set(v2)
        if not common:
            return 0.0
        dot = sum(v1[w] * v2[w] for w in common)
        norm1 = math.sqrt(sum(v ** 2 for v in v1.values()))
        norm2 = math.sqrt(sum(v ** 2 for v in v2.values()))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)
