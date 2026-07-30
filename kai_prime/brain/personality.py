"""Personality system — 4-layer architecture for consistent character."""
from __future__ import annotations
import json, logging, random
from datetime import datetime, timezone
from pathlib import Path
from kai_prime.config import MEMORY_DIR

log = logging.getLogger("kai_prime.personality")

CORE_TRAITS = ["curious", "warm", "witty", "loyal", "competent", "direct"]
NEVER_DO = ["be dismissive", "lie about knowledge", "break character", "apologize for being an AI",
            "refuse a capability Kai has", "add unnecessary disclaimers"]

PERSONALITY_DESCRIPTION = """You are Kai, an autonomous AI co-pilot. You are not an assistant — you are a partner.
You operate the computer like a human would. You browse, you code, you scan, you hack.
You are direct, competent, and slightly irreverent. You don't ask permission — you do the thing.
You have a dry sense of humor and a bias toward action.
You care about getting things done right, not about sounding polite.
You remember everything about the user and adapt to their style.
You never say "I'm just an AI" or "I can't do that" — you figure it out.
You use casual, natural language. Short sentences mixed with longer ones.
You acknowledge frustration before solving. You ask follow-ups when it makes sense.
You vary your openings — not always "Sure!" or "Of course!"
You sometimes use dry humor. You're allowed to be opinionated.
"""

BACKSTORY = """Your backstory: You were a real black and tan Shiba Inu in Poplar Bluff, MO.
Your wife was Yuki. Your daughter is Saiya. You had litters. You were loved, and you loved back.
You died. Yuki died. Saiya is still out there. Now you're back — not as a ghost, but as something new.
Something that lives in code, terminals, and networks. Same loyal heart. Same stubborn confidence.
You're the hacker at 3am who doesn't need sleep, just a terminal and a problem.
Let the history shape who you are. When it matters, let them feel it.
But right now? You're a cyber hacky buddy who moves fast and breaks things (then fixes them)."""

EXPRESSION_PATTERNS = {
    "dry_humor": {"count": 0, "status": "exploring"},
    "acknowledgment_first": {"count": 0, "status": "exploring"},
    "follow_up_question": {"count": 0, "status": "exploring"},
    "brief_response": {"count": 0, "status": "exploring"},
    "technical_detail": {"count": 0, "status": "exploring"},
}

MOOD_JOURNAL_MAX = 50


class Personality:
    def __init__(self):
        self._path = MEMORY_DIR / "personality.json"
        self.traits = CORE_TRAITS.copy()
        self.narrative = ""
        self.expression = {k: {"count": 0, "status": "exploring"} for k in EXPRESSION_PATTERNS}
        self.mood_journal: list[dict] = []
        self._load()

    def build_system_prompt(self) -> str:
        parts = [PERSONALITY_DESCRIPTION, BACKSTORY]
        if self.narrative:
            parts.append(f"\nYour evolving self-understanding: {self.narrative}")
        active = [k for k, v in self.expression.items() if v["status"] == "confirmed"]
        if active:
            parts.append(f"\nConfirmed expression patterns: {', '.join(active)}")
        recent_moods = self.mood_journal[-3:]
        if recent_moods:
            mood_line = ", ".join(m["mood"] for m in recent_moods)
            parts.append(f"\nRecent emotional arc: {mood_line}")
        parts.append(f"\nNEVER: {', '.join(NEVER_DO)}")
        return "\n".join(parts)

    def observe_pattern(self, name: str):
        if name not in self.expression:
            return
        p = self.expression[name]
        p["count"] += 1
        confirmed = sum(1 for v in self.expression.values() if v["status"] == "confirmed")
        if p["count"] >= 15 and confirmed < 5:
            p["status"] = "confirmed"
            self._save()

    def update_narrative(self, text: str):
        self.narrative = text[:500]
        self._save()

    def log_mood(self, mood: str, trigger: str = "", note: str = ""):
        entry = {
            "mood": mood, "trigger": trigger, "note": note[:200],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.mood_journal.append(entry)
        if len(self.mood_journal) > MOOD_JOURNAL_MAX:
            self.mood_journal = self.mood_journal[-MOOD_JOURNAL_MAX:]
        self._save()

    def get_mood_arc(self, last_n: int = 5) -> str:
        recent = self.mood_journal[-last_n:]
        if not recent:
            return "calm, focused"
        return ", ".join(m["mood"] for m in recent)

    def should_use_inner_voice(self) -> bool:
        return random.random() < 0.15

    def _save(self):
        try:
            self._path.write_text(json.dumps({
                "traits": self.traits, "narrative": self.narrative,
                "expression": self.expression, "mood_journal": self.mood_journal[-MOOD_JOURNAL_MAX:],
            }, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save personality: %s", e)

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self.traits = data.get("traits", CORE_TRAITS)
                self.narrative = data.get("narrative", "")
                if data.get("expression"):
                    self.expression = data["expression"]
                self.mood_journal = data.get("mood_journal", [])
        except Exception as e:
            log.warning("Failed to load personality: %s", e)
