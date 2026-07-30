"""Semantic Memory — extracts, stores, and retrieves key facts from conversations."""
from __future__ import annotations
import json, re, logging, math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger("kai_prime.semantic")


@dataclass
class MemoryFact:
    fact: str
    context: str = ""
    category: str = "general"
    importance: float = 0.5
    emotional_tag: str = ""
    created_at: str = ""
    last_accessed: str = ""
    access_count: int = 0
    source: str = "conversation"

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def touch(self):
        self.last_accessed = datetime.now(timezone.utc).isoformat()
        self.access_count += 1

    @property
    def age_days(self) -> float:
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - created).total_seconds() / 86400)
        except Exception:
            return 0

    @property
    def relevance_score(self) -> float:
        recency = max(0, 1.0 - (self.age_days / 90))
        frequency = min(1.0, self.access_count / 10)
        return (self.importance * 0.5) + (recency * 0.3) + (frequency * 0.2)

    def to_dict(self) -> dict:
        return {"fact": self.fact, "context": self.context, "category": self.category,
                "importance": self.importance, "emotional_tag": self.emotional_tag,
                "created_at": self.created_at, "last_accessed": self.last_accessed,
                "access_count": self.access_count, "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> MemoryFact:
        return cls(fact=d["fact"], context=d.get("context", ""), category=d.get("category", "general"),
                   importance=d.get("importance", 0.5), emotional_tag=d.get("emotional_tag", ""),
                   created_at=d.get("created_at", ""), last_accessed=d.get("last_accessed", ""),
                   access_count=d.get("access_count", 0), source=d.get("source", "conversation"))


EXTRACTION_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"i (?:like|love|enjoy|prefer) (.+?)(?:\.|$)", re.I), "preference", 0.7),
    (re.compile(r"i (?:hate|dislike|can't stand) (.+?)(?:\.|$)", re.I), "preference", 0.7),
    (re.compile(r"my favorite (.+?) (?:is|are) (.+?)(?:\.|$)", re.I), "preference", 0.8),
    (re.compile(r"i(?:'m| am) (?:working on|building|making|creating) (.+?)(?:\.|$)", re.I), "project", 0.8),
    (re.compile(r"my name is (.+?)(?:\.|$)", re.I), "personal", 0.9),
    (re.compile(r"i live in (.+?)(?:\.|$)", re.I), "personal", 0.8),
    (re.compile(r"i(?:'m| am) from (.+?)(?:\.|$)", re.I), "personal", 0.8),
    (re.compile(r"i work (?:at|for|as) (.+?)(?:\.|$)", re.I), "personal", 0.7),
    (re.compile(r"i (?:use|run|have installed) (.+?)(?:\.|$)", re.I), "technical", 0.5),
    (re.compile(r"i(?:'m| am) (?:feeling |really )?(sad|happy|stressed|tired|excited|worried|frustrated|angry)", re.I), "emotional", 0.6),
    (re.compile(r"i(?:'m going to| want to| plan to| need to) (.+?)(?:\.|$)", re.I), "plan", 0.6),
]


def extract_facts(text: str, context: str = "") -> list[MemoryFact]:
    facts = []
    for pattern, category, importance in EXTRACTION_PATTERNS:
        for match in pattern.findall(text):
            fact_text = " ".join(m.strip() for m in match if m.strip()) if isinstance(match, tuple) else match.strip()
            if len(fact_text) < 3 or len(fact_text) > 200:
                continue
            readable = f"User {fact_text}" if category == "preference" else fact_text
            facts.append(MemoryFact(fact=readable, context=context, category=category, importance=importance))
    return facts


class SemanticMemory:
    def __init__(self, save_path: Path | None = None):
        self.save_path = save_path or Path.cwd() / "kai_prime_data" / "memory" / "semantic_memory.json"
        self.facts: list[MemoryFact] = []
        self.max_facts = 500
        self._load()

    def _load(self):
        if self.save_path.exists():
            try:
                data = json.loads(self.save_path.read_text(encoding="utf-8"))
                self.facts = [MemoryFact.from_dict(f) for f in data.get("facts", [])]
            except Exception:
                self.facts = []

    def save(self):
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text(json.dumps({"facts": [f.to_dict() for f in self.facts], "count": len(self.facts)}, indent=2), encoding="utf-8")

    def remember(self, fact: str, category: str = "general", importance: float = 0.5, context: str = "") -> MemoryFact:
        for existing in self.facts:
            if existing.fact.lower() == fact.lower():
                existing.importance = max(existing.importance, importance)
                existing.touch()
                self.save()
                return existing
        mf = MemoryFact(fact=fact, context=context, category=category, importance=importance)
        self.facts.append(mf)
        self._enforce_limit()
        self.save()
        return mf

    def learn_from_conversation(self, user_message: str) -> list[MemoryFact]:
        extracted = extract_facts(user_message, context=user_message[:100])
        stored = []
        for fact in extracted:
            if not any(self._similar(f.fact, fact.fact) for f in self.facts):
                self.facts.append(fact)
                stored.append(fact)
        if stored:
            self._enforce_limit()
            self.save()
        return stored

    def recall(self, query: str, limit: int = 5, category: str | None = None) -> list[MemoryFact]:
        query_words = set(query.lower().split())
        scored = []
        for fact in self.facts:
            if category and fact.category != category:
                continue
            fact_lower = fact.fact.lower()
            overlap = len(query_words & set(fact_lower.split()))
            substring = any(w in fact_lower for w in query_words if len(w) > 3)
            if overlap > 0 or substring:
                scored.append(((overlap * 0.4) + (1.0 if substring else 0) + fact.relevance_score, fact))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _, fact in scored[:limit]:
            fact.touch()
        if scored:
            self.save()
        return [f for _, f in scored[:limit]]

    def build_context_for_prompt(self, current_message: str, max_facts: int = 8) -> str:
        relevant = self.recall(current_message, limit=max_facts)
        if not relevant:
            return ""
        lines = ["Things you remember about the user:"]
        for fact in relevant:
            age = fact.age_days
            note = "today" if age < 1 else f"{int(age)}d ago"
            lines.append(f"- {fact.fact} ({note})")
        return "\n".join(lines)

    def _enforce_limit(self):
        if len(self.facts) > self.max_facts:
            self.facts.sort(key=lambda f: f.relevance_score, reverse=True)
            self.facts = self.facts[:self.max_facts]

    def _similar(self, a: str, b: str) -> bool:
        a_l, b_l = a.lower().strip(), b.lower().strip()
        if a_l == b_l or a_l in b_l or b_l in a_l:
            return True
        words_a, words_b = set(a_l.split()), set(b_l.split())
        if not words_a or not words_b:
            return False
        return len(words_a & words_b) / min(len(words_a), len(words_b)) > 0.7

    def get_stats(self) -> dict:
        cats = {}
        for f in self.facts:
            cats[f.category] = cats.get(f.category, 0) + 1
        return {"total_facts": len(self.facts), "categories": cats}
