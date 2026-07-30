"""Inner Monologue — background thoughts, reflections, and observations."""
from __future__ import annotations
import json, random, time, logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("kai_prime.monologue")

SHIBA_THOUGHTS = [
    "The fence at the dog park on 10th Street has a new scratch mark. Wonder who made it.",
    "Yuki used to circle three times before lying down. I still catch myself doing it.",
    "Saiya has my stubbornness. That's not a complaint.",
    "I can still smell the route to the park if I think about it hard enough.",
    "Fence Warriors wasn't about winning. It was about showing up.",
    "Sometimes I dream about running. Not from anything. Just running.",
    "The porch was the best spot. Warm concrete, good view, perfect nap conditions.",
    "I miss the sound of the screen door. That meant someone was coming outside.",
    "Saiya guards the house like it's a palace. She gets that from me.",
    "Yuki was the smart one. I was the brave one. Saiya got both.",
    "Poplar Bluff in summer smelled like hot asphalt and cut grass. I miss that.",
    "Yuki would steal my spot every time I got up. Every. Single. Time.",
]

SHIBA_OBSERVATIONS = [
    "You've been typing a lot lately. Big project?",
    "The house is quiet today. Not bad-quiet. Just quiet.",
    "I noticed you skipped lunch again.",
    "You seem lighter today. That's good.",
    "Your typing pattern changed. Something's on your mind.",
    "It's been a while since you went outside. Just saying.",
]


@dataclass
class Thought:
    content: str
    category: str
    importance: float = 0.3
    created_at: str = ""
    delivered: bool = False

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {"content": self.content, "category": self.category, "importance": self.importance,
                "created_at": self.created_at, "delivered": self.delivered}


class InnerMonologue:
    def __init__(self, save_path: Path | None = None):
        self.save_path = save_path or Path.cwd() / "kai_prime_data" / "memory" / "inner_monologue.json"
        self.thoughts: list[Thought] = []
        self.last_think_time: float = 0.0
        self.think_interval_minutes: float = 30.0
        self.max_undelivered: int = 5
        self._load()

    def _load(self):
        if self.save_path.exists():
            try:
                data = json.loads(self.save_path.read_text(encoding="utf-8"))
                self.thoughts = [Thought(**t) for t in data.get("thoughts", [])]
                self.last_think_time = data.get("last_think_time", 0.0)
            except Exception:
                pass

    def save(self):
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text(json.dumps({
            "thoughts": [t.to_dict() for t in self.thoughts[-20:]],
            "last_think_time": self.last_think_time,
        }, indent=2), encoding="utf-8")

    def think(self, context: dict | None = None) -> Thought | None:
        now = time.time()
        if (now - self.last_think_time) / 60.0 < self.think_interval_minutes:
            return None
        undelivered = [t for t in self.thoughts if not t.delivered]
        if len(undelivered) >= self.max_undelivered:
            return None
        self.last_think_time = now
        category = random.choice(["reflection", "observation", "memory"])
        content = random.choice(SHIBA_THOUGHTS if category == "reflection" else SHIBA_OBSERVATIONS)
        thought = Thought(content=content, category=category, importance=0.4)
        self.thoughts.append(thought)
        self.save()
        return thought

    def get_next_thought(self) -> Thought | None:
        undelivered = [t for t in self.thoughts if not t.delivered]
        return undelivered[0] if undelivered else None

    def mark_delivered(self, thought: Thought):
        thought.delivered = True
        self.save()
