"""Relationship Model — learns who the user is over time."""
from __future__ import annotations
import json, re, logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("kai_prime.relationship")


@dataclass
class UserPreferences:
    formality: float = 0.3
    verbosity: float = 0.4
    humor: float = 0.6
    proactivity: float = 0.5
    interests: list[str] = field(default_factory=list)
    avoided_topics: list[str] = field(default_factory=list)
    preferred_name: str = ""
    morning_person: bool = False
    night_owl: bool = False
    active_projects: list[str] = field(default_factory=list)
    uses_emoji: bool = False
    uses_slang: bool = False
    average_message_length: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "formality": round(self.formality, 3), "verbosity": round(self.verbosity, 3),
            "humor": round(self.humor, 3), "proactivity": round(self.proactivity, 3),
            "interests": self.interests[-20:], "avoided_topics": self.avoided_topics,
            "preferred_name": self.preferred_name, "morning_person": self.morning_person,
            "night_owl": self.night_owl, "active_projects": self.active_projects[-10:],
            "uses_emoji": self.uses_emoji, "uses_slang": self.uses_slang,
            "average_message_length": round(self.average_message_length, 1),
        }.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict) -> UserPreferences:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class RelationshipModel:
    def __init__(self, save_path: Path | None = None):
        self.save_path = save_path or Path.cwd() / "kai_prime_data" / "memory" / "relationship.json"
        self.prefs = UserPreferences()
        self.interaction_count = 0
        self.first_interaction = ""
        self.last_interaction = ""
        self.shared_experiences: list[dict] = []
        self.inside_jokes: list[str] = []
        self._message_lengths: list[float] = []
        self._load()

    def _load(self):
        if self.save_path.exists():
            try:
                data = json.loads(self.save_path.read_text(encoding="utf-8"))
                self.prefs = UserPreferences.from_dict(data.get("preferences", {}))
                self.interaction_count = data.get("interaction_count", 0)
                self.first_interaction = data.get("first_interaction", "")
                self.last_interaction = data.get("last_interaction", "")
                self.shared_experiences = data.get("shared_experiences", [])
                self.inside_jokes = data.get("inside_jokes", [])
            except Exception:
                pass

    def save(self):
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text(json.dumps({
            "preferences": self.prefs.to_dict(), "interaction_count": self.interaction_count,
            "first_interaction": self.first_interaction, "last_interaction": self.last_interaction,
            "shared_experiences": self.shared_experiences[-50:], "inside_jokes": self.inside_jokes[-20:],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")

    def process_message(self, text: str):
        self.interaction_count += 1
        self.last_interaction = datetime.now(timezone.utc).isoformat()
        if not self.first_interaction:
            self.first_interaction = self.last_interaction

        words = text.split()
        wc = len(words)
        formal = sum(1 for s in ["please", "thank you", "could you", "would you"] if s in text.lower())
        casual = sum(1 for s in ["hey", "lol", "gonna", "wanna", "nah", "bruh"] if s in text.lower())
        slang = any(w in text.lower() for w in ["lol", "lmao", "bruh", "nah", "fr", "ngl"])

        self._message_lengths.append(wc)
        if len(self._message_lengths) > 100:
            self._message_lengths = self._message_lengths[-100:]
        if self._message_lengths:
            self.prefs.average_message_length = sum(self._message_lengths) / len(self._message_lengths)

        if formal > 0:
            self.prefs.formality = self.prefs.formality * 0.9 + 0.7 * 0.1
        elif casual > 0:
            self.prefs.formality = self.prefs.formality * 0.9 + 0.1 * 0.1
        if slang:
            self.prefs.uses_slang = True
        if wc > 30:
            self.prefs.verbosity = min(1.0, self.prefs.verbosity + 0.01)
        elif wc < 5:
            self.prefs.verbosity = max(0.0, self.prefs.verbosity - 0.01)

        hour = datetime.now().hour
        if 5 <= hour < 9:
            self.prefs.morning_person = True
        if hour >= 22 or hour < 3:
            self.prefs.night_owl = True

        name_match = re.search(r"(?:my name is|call me|i'm)\s+([A-Za-z]{2,20})", text, re.I)
        if name_match and not self.prefs.preferred_name:
            name = name_match.group(1).strip()
            if name.lower() not in {"just", "really", "going", "trying", "looking", "not", "still"}:
                self.prefs.preferred_name = name.capitalize()
        self.save()

    def get_communication_style(self) -> dict:
        return {
            "tone": "casual" if self.prefs.formality < 0.4 else "balanced" if self.prefs.formality < 0.7 else "formal",
            "length": "brief" if self.prefs.verbosity < 0.3 else "moderate" if self.prefs.verbosity < 0.7 else "detailed",
            "humor": "light" if self.prefs.humor < 0.3 else "moderate" if self.prefs.humor < 0.7 else "playful",
        }

    def get_context_string(self) -> str:
        parts = []
        if self.interaction_count > 10:
            parts.append(f"You've talked to this user {self.interaction_count} times.")
        if self.prefs.preferred_name:
            parts.append(f"Their name is {self.prefs.preferred_name}.")
        if self.prefs.active_projects:
            parts.append(f"Recent projects: {', '.join(self.prefs.active_projects[-3:])}.")
        if self.prefs.interests:
            parts.append(f"Interests: {', '.join(self.prefs.interests[-5:])}.")
        style = self.get_communication_style()
        if style["tone"] == "casual":
            parts.append("Keep it casual. Skip the pleasantries.")
        if style["length"] == "brief":
            parts.append("Short responses preferred.")
        if self.prefs.uses_slang:
            parts.append("User uses slang — match their energy.")
        return "\n".join(parts)

    def add_experience(self, desc: str, tag: str = ""):
        self.shared_experiences.append({"description": desc, "emotional_tag": tag, "timestamp": datetime.now(timezone.utc).isoformat()})
        if len(self.shared_experiences) > 50:
            self.shared_experiences = self.shared_experiences[-50:]
        self.save()

    def add_project(self, project: str):
        if project not in self.prefs.active_projects:
            self.prefs.active_projects.append(project)
            self.save()
