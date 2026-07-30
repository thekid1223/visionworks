"""Chess Watcher — uses vision AI to analyze chess boards and give move advice."""
from __future__ import annotations
import hashlib, logging, threading, time
from pathlib import Path

log = logging.getLogger("kai_prime.chess_watcher")

_active_watcher: ChessWatcher | None = None


class ChessWatcher:

    def __init__(self, brain=None, interval: float = 5.0):
        self.brain = brain
        self.interval = interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_hash: str = ""
        self._last_advice: str = ""
        self._change_count: int = 0
        self._last_change_time: float = 0
        self._recent_changes: list[float] = []
        self._event_log: list[str] = []

    def start(self, on_move=None):
        if self._running:
            return "Already watching"
        self._running = True
        self._last_hash = ""
        self._change_count = 0
        self._last_change_time = 0
        self._recent_changes = []
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        log.info("Chess watcher started (interval=%.1fs)", self.interval)
        return "Watching chess.com — you'll get a pop-up with analysis when the board changes"

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Chess watcher stopped")
        return "Chess watcher stopped"

    @property
    def is_watching(self) -> bool:
        return self._running

    def _watch_loop(self):
        from kai_prime.agents.vision import VisionAgent
        vision = VisionAgent()

        while self._running:
            try:
                self._tick(vision)
            except Exception as e:
                log.warning("Chess watcher error: %s", e)
            time.sleep(self.interval)

    def _tick(self, vision):
        ss_result = vision.take_screenshot()
        if "Screenshot saved:" not in ss_result:
            return

        ss_path = ss_result.split("Screenshot saved: ")[-1]
        current_hash = self._hash_board_region(ss_path)

        if not current_hash:
            return

        if self._last_hash == "":
            self._last_hash = current_hash
            self._log_event("Watching started — baseline set")
            return

        if current_hash == self._last_hash:
            return

        now = time.time()

        self._recent_changes.append(now)
        self._recent_changes = [t for t in self._recent_changes if now - t < 20]

        if len(self._recent_changes) >= 4:
            self._log_event("Too many changes in 20s — ignoring (animation/clock)")
            self._recent_changes = []
            return

        if self._last_change_time and (now - self._last_change_time) < 8:
            self._log_event("Change too soon after last — ignoring")
            return

        self._last_change_time = now
        self._last_hash = current_hash
        self._change_count += 1

        self._log_event(f"Board change #{self._change_count} detected — analyzing with vision")

        advice = self._analyze_with_vision(ss_path)

        # Extract just the move for the notification title
        title = f"♟ Move #{self._change_count}"
        body = advice
        for line in advice.split('\n'):
            line = line.strip()
            if line.upper().startswith('PLAY:'):
                title = f"♟ {line}"
                body = advice.replace(line, '').strip()
                break

        # Truncate body so notification isn't cut off
        if len(body) > 150:
            body = body[:147] + '...'

        from kai_prime.tools.notifier import notify
        notify(
            title,
            body,
            duration=20.0,
            urgent=True,
        )
        self._last_advice = advice
        self._recent_changes = []
        log.info("Board change #%d detected, vision analysis sent", self._change_count)

    def _hash_board_region(self, path: str) -> str:
        try:
            from PIL import Image
            img = Image.open(path)
            w, h = img.size
            left = int(w * 0.15)
            top = int(h * 0.05)
            right = int(w * 0.75)
            bottom = int(h * 0.85)
            board = img.crop((left, top, right, bottom))
            small = board.resize((80, 80), Image.BILINEAR)
            pixels = list(small.getdata())
            pixel_str = "".join(f"{r//16}{g//16}{b//16}" for r, g, b in pixels)
            return hashlib.md5(pixel_str.encode()).hexdigest()[:16]
        except Exception:
            return ""

    def _analyze_with_vision(self, ss_path: str) -> str:
        if not self.brain or not self.brain._provider_chain:
            return "Board changed! Check your position."

        try:
            prompt = (
                "Chess coach. Look at this chess.com screenshot.\n"
                "Read the move list on the right. Figure out the position.\n"
                "REPLY IN 3 LINES MAX. No thinking, no analysis, no explanation of the board.\n\n"
                "Line 1: Last 2 moves played\n"
                "Line 2: PLAY: [your move in algebraic notation]\n"
                "Line 3: [one sentence why]\n\n"
                "Example:\n"
                "1. e4 e5\n"
                "PLAY: Nf3\n"
                "Attacks e5 and develops a knight\n\n"
                "DO NOT describe the board. DO NOT list pieces. JUST give the move."
            )
            result = self.brain._provider_chain.vision_chat(ss_path, prompt, temperature=0.2, max_tokens=100)
            if result:
                cleaned = result.strip()
                while "<think>" in cleaned and "</think>" in cleaned:
                    start = cleaned.find("<think>")
                    end = cleaned.find("</think>") + 7
                    cleaned = cleaned[:start] + cleaned[end:]
                cleaned = cleaned.strip()
                return cleaned if cleaned else "Board changed but vision analysis unavailable."
            return "Board changed but vision analysis unavailable."
        except Exception as e:
            return f"Board changed! Analysis error: {e}"

    def _log_event(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self._event_log.append(entry)
        if len(self._event_log) > 50:
            self._event_log = self._event_log[-50:]
        log.info("Chess watcher: %s", msg)


def get_watcher(brain=None) -> ChessWatcher:
    global _active_watcher
    if _active_watcher is None:
        _active_watcher = ChessWatcher(brain=brain)
    if brain and not _active_watcher.brain:
        _active_watcher.brain = brain
    return _active_watcher


TOOLS = {
    "chess_watch_start": {
        "description": "Start watching chess.com — notifies you with vision analysis when the board changes. No args.",
        "function": lambda: get_watcher().start(),
        "params": {},
    },
    "chess_watch_stop": {
        "description": "Stop watching chess.com. No args.",
        "function": lambda: get_watcher().stop(),
        "params": {},
    },
    "chess_watch_status": {
        "description": "Check if chess watcher is active. No args.",
        "function": lambda: f"Watching: {'YES' if get_watcher().is_watching else 'NO'} — Changes: {get_watcher()._change_count} — Last: {get_watcher()._last_advice or 'none'}",
        "params": {},
    },
}
