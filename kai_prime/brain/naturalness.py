"""Naturalness filter — anti-robotism, sentence variation, follow-ups."""
from __future__ import annotations
import re, random

OPENINGS = ["Sure.", "Got it.", "On it.", "Alright.", "Done.", "Here's the deal.", "Right.", "Let's see."]
VAGUE_PHRASES = ["i'll look into that", "let me check", "i'll get back to you", "one moment", "just a moment",
                  "i'll investigate", "i'll research", "let me see what i can do"]

def polish(response: str, user_message: str = "") -> str:
    if not response or len(response.strip()) < 5:
        return response
    s = response.strip()
    # Vary openings
    lower_s = s.lower()
    if lower_s.startswith("sure!") or lower_s.startswith("of course") or lower_s.startswith("absolutely"):
        s = random.choice(OPENINGS) + " " + s.lstrip("!. ")
    # Sentence length variation
    sentences = re.split(r'(?<=[.!?])\s+', s)
    if len(sentences) >= 3 and all(15 < len(sent) < 35 for sent in sentences):
        # All same length — vary by combining some
        combined = []
        i = 0
        while i < len(sentences):
            if i + 1 < len(sentences) and random.random() > 0.5:
                combined.append(sentences[i].rstrip(". ") + ". " + sentences[i + 1])
                i += 2
            else:
                combined.append(sentences[i])
                i += 1
        s = " ".join(combined)
    # Acknowledge frustration
    if user_message:
        lower_user = user_message.lower()
        has_frustration = any(w in lower_user for w in ["broken", "doesn't work", "still", "again", "ugh", "wtf", "stupid"])
        has_acknowledgment = any(w in s.lower() for w in ["i hear", "totally fair", "i understand", "makes sense", "fair enough"])
        if has_frustration and not has_acknowledgment:
            s = "Totally fair. " + s
    # Follow-up for open-ended topics
    if user_message and "?" not in user_message and len(user_message) > 30:
        if not s.rstrip().endswith("?") and random.random() > 0.6:
            follow_ups = [" Want me to go deeper?", " Need anything else?", " What's next?"]
            s += random.choice(follow_ups)
    return s


def detect_repetition(response: str) -> bool:
    sentences = re.split(r'[.!?]+', response.strip())
    counts = {}
    for s in sentences:
        norm = s.strip().lower()
        if len(norm) > 15:
            counts[norm] = counts.get(norm, 0) + 1
    return max(counts.values(), default=0) >= 3


def is_vague(response: str) -> bool:
    lower = response.lower()
    return any(p in lower for p in VAGUE_PHRASES) and len(response.strip()) < 200


def vary_sentence_length(text: str) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) < 3:
        return text
    result = []
    for i, sent in enumerate(sentences):
        if i % 2 == 0 and len(sent) > 30:
            words = sent.split()
            mid = len(words) // 2
            result.append(" ".join(words[:mid]) + ".")
            result.append(" ".join(words[mid:]))
        else:
            result.append(sent)
    return " ".join(result)
