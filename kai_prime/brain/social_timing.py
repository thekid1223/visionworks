"""Social Timing — knows when to speak up and when to stay quiet."""
from __future__ import annotations
import json, time, logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("kai_prime.social")


class SocialTiming:
    def __init__(self, save_path: Path | None = None):
        self.save_path = save_path or Path.cwd() / "kai_prime_data" / "memory" / "social_timing.json"
        self.last_interaction: float = 0.0
        self.total_interactions: int = 0
        self.session_start: float = 0.0
        self.quiet_start: int = 23
        self.quiet_end: int = 7
        self._greeted_today: bool = False
        self._last_proactive: float = 0.0
        self._load()

    def _load(self):
        if self.save_path.exists():
            try:
                data = json.loads(self.save_path.read_text(encoding="utf-8"))
                self.total_interactions = data.get("total_interactions", 0)
                self.last_interaction = data.get("last_interaction", 0.0)
            except Exception:
                pass

    def save(self):
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text(json.dumps({
            "total_interactions": self.total_interactions, "last_interaction": self.last_interaction,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")

    def interaction_started(self):
        now = time.time()
        self.last_interaction = now
        self.total_interactions += 1
        if self.session_start == 0:
            self.session_start = now
        self.save()

    def session_ended(self):
        self.session_start = 0

    @property
    def idle_minutes(self) -> float:
        if self.last_interaction <= 0:
            return 9999
        return (time.time() - self.last_interaction) / 60.0

    @property
    def session_duration_minutes(self) -> float:
        if self.session_start == 0:
            return 0
        return (time.time() - self.session_start) / 60.0

    @property
    def is_quiet_hours(self) -> bool:
        hour = datetime.now().hour
        if self.quiet_start > self.quiet_end:
            return hour >= self.quiet_start or hour < self.quiet_end
        return self.quiet_start <= hour < self.quiet_end

    @property
    def is_overwork(self) -> bool:
        return self.session_duration_minutes > 120

    def check_proactive(self) -> dict | None:
        if time.time() - self._last_proactive < 300:
            return None
        if self.is_quiet_hours:
            return None
        now = datetime.now()
        hour = now.hour
        if 8 <= hour < 9 and not self._greeted_today and self.idle_minutes > 60:
            self._greeted_today = True
            self._last_proactive = time.time()
            return {"signal": "morning", "message": "morning_greeting"}
        if self.is_overwork and self.session_duration_minutes % 60 < 2:
            self._last_proactive = time.time()
            return {"signal": "overwork", "message": "overwork_break"}
        if 15 < self.idle_minutes < 30:
            self._last_proactive = time.time()
            return {"signal": "idle", "message": "idle_checkin"}
        if hour >= 0 and hour < 4 and self.idle_minutes < 5:
            self._last_proactive = time.time()
            return {"signal": "late_night", "message": "late_night"}
        if hour == 0 and now.minute < 5:
            self._greeted_today = False
        return None

    def get_proactive_message(self, signal: dict) -> str:
        import random
        templates = {
            "morning": ["Morning. You're up early.", "Hey. Good to see you.", "Morning. What do you need?"],
            "return": ["Hey. Been a while.", "Welcome back.", "There you are."],
            "overwork": ["You've been at this a while. Take a break?", "Even Kai takes naps. Just saying."],
            "idle": ["Still there?", "Just checking in.", "I'm here if you need me."],
            "late_night": ["It's late. I'm still up, but I'm a Shiba.", "Can't sleep? Me neither."],
        }
        options = templates.get(signal.get("signal", ""), [])
        return random.choice(options) if options else ""
