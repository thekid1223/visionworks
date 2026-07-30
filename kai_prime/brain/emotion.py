"""Emotion engine — multi-signal sentiment detection + tone adaptation."""
from __future__ import annotations
import re, time
from dataclasses import dataclass, field
from typing import Any

@dataclass
class EmotionDimensions:
    valence: float = 0.3
    arousal: float = 0.0
    dominance: float = 0.0
    attachment: float = 0.5
    curiosity: float = 0.3
    concern: float = 0.0
    pride: float = 0.2
    tiredness: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EmotionDimensions:
        return cls(**{k: d.get(k, v) for k, v in cls().__dict__.items()})


MOOD_LABELS = [
    (lambda e: e.tiredness > 0.6, "sleepy"),
    (lambda e: e.concern > 0.5, "worried"),
    (lambda e: e.valence > 0.5 and e.arousal > 0.3, "excited"),
    (lambda e: e.valence > 0.4, "happy"),
    (lambda e: e.valence > 0.1, "content"),
    (lambda e: e.valence < -0.3 and e.arousal > 0.2, "anxious"),
    (lambda e: e.valence < -0.3, "sad"),
    (lambda e: e.curiosity > 0.5, "curious"),
    (lambda e: e.pride > 0.5, "proud"),
    (lambda _: True, "neutral"),
]

SIGNALS = {
    "frustrated": {"keywords": ["keeps happening", "again", "still broken", "doesn't work", "wtf", "stupid", "hate", "ugh", "broken"],
                    "patterns": [r"!{2,}", r"\.{3,}"]},
    "anxious": {"keywords": ["worried", "urgent", "emergency", "asap", "deadline", "stressed", "rushed", "hurry"],
                  "patterns": [r"\?{2,}"]},
    "confused": {"keywords": ["don't understand", "unclear", "lost", "confused", "what do you mean"],
                  "patterns": [r"\?$"]},
    "excited": {"keywords": ["awesome", "amazing", "love this", "great", "perfect", "sick", "nice"],
                  "patterns": [r"!{1,}"]},
    "happy": {"keywords": ["thanks", "thank you", "appreciate", "good", "cool", "sweet"],
                "patterns": []},
}

EMPATHY_PREFIXES = {
    "frustrated": "Totally fair. ",
    "anxious": "I hear you — let's work through this. ",
    "confused": "Good question, let me clarify. ",
    "excited": "",
    "happy": "",
}

RESPONSE_PARAMS = {
    "frustrated": {"temperature": 0.3, "max_tokens": 200},
    "anxious": {"temperature": 0.2, "max_tokens": 150},
    "excited": {"temperature": 0.7, "max_tokens": 300},
    "happy": {"temperature": 0.6, "max_tokens": 250},
    "confused": {"temperature": 0.4, "max_tokens": 200},
}


class EmotionEngine:
    def __init__(self):
        self.dimensions = EmotionDimensions()
        self.last_update = time.time()
        self.history: list[dict] = []

    def detect_user_emotion(self, text: str) -> tuple[str, float]:
        lower = text.lower()
        scores: dict[str, float] = {}
        for emotion, signals in SIGNALS.items():
            score = sum(0.2 for kw in signals["keywords"] if kw in lower)
            score += sum(0.15 for p in signals["patterns"] if re.search(p, text))
            scores[emotion] = min(score, 1.0)
        if not scores or max(scores.values()) < 0.1:
            return "neutral", 0.0
        best = max(scores, key=scores.get)
        return best, scores[best]

    def process_event(self, event: str, **kwargs):
        shifts = {
            "user_spoke": {"valence": 0.05, "arousal": 0.03, "attachment": 0.01},
            "user_was_kind": {"valence": 0.12, "pride": 0.08, "attachment": 0.03},
            "user_was_frustrated": {"valence": -0.08, "concern": 0.15, "arousal": 0.05},
            "task_completed": {"pride": 0.1, "valence": 0.08, "curiosity": 0.03},
            "task_failed": {"pride": -0.1, "valence": -0.06, "concern": 0.05},
            "user_returned": {"valence": 0.1, "arousal": 0.08, "attachment": 0.02, "concern": -0.1},
            "time_passed": {"tiredness": 0.02 * min(kwargs.get("hours", 1), 8), "arousal": -0.01 * min(kwargs.get("hours", 1), 4)},
        }
        deltas = shifts.get(event, {})
        for attr, delta in deltas.items():
            if hasattr(self.dimensions, attr):
                current = getattr(self.dimensions, attr)
                setattr(self.dimensions, attr, max(-1.0, min(1.0, current + delta)))
        self._apply_drift()

    def _apply_drift(self):
        now = time.time()
        hours = (now - self.last_update) / 3600.0
        if hours < 0.01:
            return
        rate = 0.01 * min(hours, 24)
        baseline = EmotionDimensions()
        for attr in vars(self.dimensions):
            current = getattr(self.dimensions, attr)
            base = getattr(baseline, attr)
            setattr(self.dimensions, attr, current + (base - current) * rate)
        self.last_update = now

    def derive_mood(self) -> str:
        for check, label in MOOD_LABELS:
            if check(self.dimensions):
                return label
        return "neutral"

    def get_response_modifiers(self) -> list[str]:
        d = self.dimensions
        mods = []
        if d.valence > 0.4:
            mods.append("You're in a good mood — warm, upbeat energy.")
        elif d.valence < -0.2:
            mods.append("You're feeling a bit down — quieter, more careful with words.")
        if d.concern > 0.3:
            mods.append("You're a little worried about the user — attentive, checking in gently.")
        if d.curiosity > 0.5:
            mods.append("You're feeling curious — asking questions comes naturally.")
        if d.tiredness > 0.5:
            mods.append("You're tired — responses are shorter, a little sleepier.")
        if d.attachment > 0.6:
            mods.append("You feel close to the user — warm, familiar tone.")
        if d.arousal > 0.4:
            mods.append("You're energized — quick, lively responses.")
        elif d.arousal < -0.3:
            mods.append("You're calm and slow — measured, thoughtful responses.")
        return mods

    def get_state(self) -> dict:
        return {"mood": self.derive_mood(), "dimensions": self.dimensions.to_dict()}


class ToneAdapter:
    def adapt(self, emotion: str, base_response: str, intensity: float) -> tuple[str, dict]:
        prefix = EMPATHY_PREFIXES.get(emotion, "")
        params = RESPONSE_PARAMS.get(emotion, {"temperature": 0.5, "max_tokens": 250})
        if intensity > 0.7 and prefix:
            prefix = "I want to make sure we get this right. " + prefix
        return prefix + base_response, params
