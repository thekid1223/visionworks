"""Desktop Pet — canvas-drawn pixel art black & tan male Shiba Inu.

Always-on-top tkinter window with smooth animation, speech bubbles,
and interactive behaviors. No image files needed — all drawn via Canvas.
"""
from __future__ import annotations

import math
import random
import threading
import time
import logging

log = logging.getLogger("kai_prime.desktop_pet")

# ── Color Palette ────────────────────────────────────────────────────────────
C_BLACK   = "#1a1a1a"
C_TAN     = "#c4913a"
C_TAN_DK  = "#a07028"
C_TAN_LT  = "#d4a84a"
C_CREAM   = "#f0dcc0"
C_WHITE   = "#ffffff"
C_NOSE    = "#2a2020"
C_EYE     = "#1a1010"
C_EYE_W   = "#ffffff"
C_MOUTH   = "#3a2020"
C_TONGUE  = "#e06060"
C_BG      = "#2b2b2b"
C_BORDER  = "#555555"
C_BUBBLE  = "#ffffff"
C_BUBBLE_T= "#1a1a1a"

# ── Pixel Art Grid (20x24) ──────────────────────────────────────────────────
# Each row is a string. Characters map to colors:
# B=black T=tan D=tan_dark L=tan_light C=cream W=white N=nose E=eye M=mouth
# O=tongue .=transparent

_SHIBA_BODY = [
    "....BBBBTTTTBBBB....",
    "...BBTTTTTTTTTTBBB..",
    "..BTTTTDDDDDDTTTTB..",
    ".BTTDDDDDDDDDDTTTBB.",
    "BTTDDDDDDDDDDDDTTTB.",
    "BTDDEEEBCCCBEEEDTTB.",
    "BTDDENEBCCCBNEEDTTB.",
    "BTDDDDDDCCCCCCDDTTB.",
    "BTDDDDDDDDDDDDDDTB.",
    ".BTDDDDDDDDDDDDDTB.",
    ".BTDDDCCCCCCCDDDTB.",
    "..BTDDCCCCCCCDDTB...",
    "..BBDDCCCCCDDDDB....",
    "...BBDDCCCCDDDB.....",
    "....BBDDDDDDDB......",
    "....BTTTTTTTTB......",
    "...BTTTTTTTTTTB.....",
    "..BTTTTTTTTTTTTB....",
    ".BTTTTB....BTTTTB...",
    ".BTTTB......BTTTB...",
    "..BTB........BTB....",
    "..BB..........BB....",
]

_COLOR_MAP = {
    "B": C_BLACK, "T": C_TAN, "D": C_TAN_DK, "L": C_TAN_LT,
    "C": C_CREAM, "W": C_WHITE, "N": C_NOSE, "E": C_EYE,
    "M": C_MOUTH, "O": C_TONGUE,
}

# ── Animation Frames ─────────────────────────────────────────────────────────
# Each frame is a list of (dx, dy) pixel offsets for body parts
# that move during animation.

_FRAMES = {
    "idle": [
        {"tail": [(0, 0)], "ears": [(0, 0)], "body": [(0, 0)]},
        {"tail": [(0, -1)], "ears": [(0, 0)], "body": [(0, 0)]},
    ],
    "tail_wag": [
        {"tail": [(-1, 0)], "ears": [(0, 0)], "body": [(0, 0)]},
        {"tail": [(1, -1)], "ears": [(0, 0)], "body": [(0, 0)]},
        {"tail": [(-1, 1)], "ears": [(0, 0)], "body": [(0, 0)]},
        {"tail": [(1, 0)], "ears": [(0, 0)], "body": [(0, 0)]},
    ],
    "sniff": [
        {"tail": [(0, 0)], "ears": [(0, -1)], "body": [(0, 0)]},
        {"tail": [(0, 0)], "ears": [(0, 0)], "body": [(0, -1)]},
        {"tail": [(0, 0)], "ears": [(0, 1)], "body": [(0, 0)]},
    ],
    "happy": [
        {"tail": [(1, -1)], "ears": [(-1, -1)], "body": [(0, -1)]},
        {"tail": [(-1, -1)], "ears": [(1, -1)], "body": [(0, -2)]},
        {"tail": [(1, -1)], "ears": [(-1, -1)], "body": [(0, -1)]},
    ],
    "alert": [
        {"tail": [(0, 0)], "ears": [(0, -2)], "body": [(0, 0)]},
        {"tail": [(0, 0)], "ears": [(0, -2)], "body": [(0, 0)]},
    ],
    "sleep": [
        {"tail": [(0, 0)], "ears": [(0, 1)], "body": [(0, 1)]},
        {"tail": [(0, 0)], "ears": [(0, 1)], "body": [(0, 1)]},
    ],
}

# ── Speech Bubble Phrases ────────────────────────────────────────────────────
_IDLE_PHRASES = [
    "*yawn*", "*stretch*", "Boop!", "Woof!", "*tail wag*",
    "What do you need?", "I'm here!", "Ready when you are.",
    "Need help with something?", "Just vibing.", "*sniff sniff*",
    "Hey!", "Let's do this!", "All systems online.",
]

_ACHIEVEMENT_PHRASES = [
    "Nice one!", "Achievement unlocked!", "You did it!",
    "That's awesome!", "Badge earned!", "Level up!",
]

_TOOL_PHRASES = [
    "On it!", "Working on it...", "Done!", "Let me check...",
    "Processing...", "Got it!", "Done deal!",
]


class DesktopPet:
    """Pixel art Shiba Inu desktop companion."""

    def __init__(self):
        self._window = None
        self._canvas = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._state = "idle"
        self._frame_idx = 0
        self._x = 100
        self._y = 100
        self._size = 4
        self._dragging = False
        self._drag_offset = (0, 0)
        self._bubble_text = ""
        self._bubble_until = 0.0
        self._eye_state = "open"
        self._blink_until = 0.0
        self._phrase_cooldown = 0.0
        self._event_queue: list[str] = []
        self._sleep_until = 0.0

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Desktop Pet started")

    def stop(self):
        self._running = False
        if self._window:
            try:
                self._window.after(0, self._window.destroy)
            except Exception:
                pass

    def show_bubble(self, text: str, duration: float = 4.0):
        self._bubble_text = text[:60]
        self._bubble_until = time.time() + duration

    def trigger_event(self, event: str):
        """Queue an event: 'achievement', 'tool_ok', 'tool_fail', 'chat'"""
        self._event_queue.append(event)
        if event == "achievement":
            self._state = "happy"
            self.show_bubble(random.choice(_ACHIEVEMENT_PHRASES), 5.0)
        elif event == "tool_ok":
            self._state = "tail_wag"
            self.show_bubble(random.choice(_TOOL_PHRASES), 3.0)
        elif event == "tool_fail":
            self._state = "alert"
            self.show_bubble("Hmm, that didn't work...", 3.0)
        elif event == "chat":
            if time.time() > self._phrase_cooldown:
                self._state = "tail_wag"
                self.show_bubble(random.choice(_IDLE_PHRASES), 3.0)
                self._phrase_cooldown = time.time() + 8

    def _run(self):
        try:
            import tkinter as tk
        except ImportError:
            log.warning("tkinter not available — desktop pet disabled")
            self._running = False
            return

        self._window = tk.Tk()
        self._window.title("Kai")
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._window.attributes("-alpha", 0.95)
        self._window.configure(bg=C_BG)

        w = 20 * self._size + 20
        h = 24 * self._size + 20
        screen_w = self._window.winfo_screenwidth()
        self._x = screen_w - w - 40
        self._y = 100
        self._window.geometry(f"{w}x{h}+{self._x}+{self._y}")

        self._canvas = tk.Canvas(
            self._window, width=w, height=h,
            bg=C_BG, highlightthickness=1, highlightbackground=C_BORDER,
        )
        self._canvas.pack()

        # Event bindings
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Button-3>", self._on_right_click)
        self._canvas.bind("<Double-Button-1>", self._on_double_click)

        # Start animation loop
        self._animate()
        self._auto_idle()

        try:
            self._window.mainloop()
        except Exception:
            pass
        self._running = False

    def _animate(self):
        if not self._running or not self._canvas:
            return
        try:
            self._draw()
        except Exception:
            pass
        # Frame rate: ~8fps for smooth but not CPU-heavy
        self._window.after(125, self._animate)

    def _auto_idle(self):
        """Random idle behaviors."""
        if not self._running:
            return
        now = time.time()
        if now > self._sleep_until and self._state not in ("happy", "alert"):
            r = random.random()
            if r < 0.3 and self._state == "idle":
                self._state = "tail_wag"
                self._window.after(2000, lambda: self._set_state("idle"))
            elif r < 0.5 and self._state == "idle":
                self._state = "sniff"
                self._window.after(1500, lambda: self._set_state("idle"))
            elif r < 0.6 and self._state == "idle":
                self._state = "alert"
                self._window.after(3000, lambda: self._set_state("idle"))
            elif r < 0.65 and self._state == "idle":
                self.show_bubble(random.choice(_IDLE_PHRASES), 3.0)

        # Random blink
        if now > self._blink_until and self._eye_state == "open":
            if random.random() < 0.3:
                self._eye_state = "closed"
                self._blink_until = now + 0.15
        elif now > self._blink_until and self._eye_state == "closed":
            self._eye_state = "open"

        # Reset state after events
        if self._state in ("happy", "alert") and now > self._bubble_until:
            self._state = "idle"

        self._window.after(500, self._auto_idle)

    def _set_state(self, state: str):
        if self._state not in ("happy", "alert"):
            self._state = state

    def _draw(self):
        c = self._canvas
        c.delete("all")
        frames = _FRAMES.get(self._state, _FRAMES["idle"])
        frame = frames[self._frame_idx % len(frames)]
        self._frame_idx += 1

        s = self._size
        ox, oy = 10, 10  # offset from canvas edge

        # Draw body pixels
        body_off = frame.get("body", [(0, 0)])[0]
        ear_off = frame.get("ears", [(0, 0)])[0]

        for row_i, row in enumerate(_SHIBA_BODY):
            for col_i, ch in enumerate(row):
                if ch == ".":
                    continue
                color = _COLOR_MAP.get(ch, C_BLACK)

                # Apply offsets to specific regions
                dx, dy = 0, 0
                if row_i < 4:  # ears region
                    dx, dy = ear_off
                elif row_i > 18:  # legs region
                    dx, dy = 0, -body_off[1]

                x1 = ox + (col_i + dx) * s
                y1 = oy + (row_i + dy) * s
                x2 = x1 + s
                y2 = y1 + s
                c.create_rectangle(x1, y1, x2, y2, fill=color, outline="")

        # Draw eyes
        ey = oy + 5 * s
        ex_l = ox + 7 * s
        ex_r = ox + 12 * s
        ew = 2 * s
        if self._eye_state == "closed":
            c.create_line(ex_l, ey + s // 2, ex_l + ew, ey + s // 2, fill=C_BLACK, width=2)
            c.create_line(ex_r, ey + s // 2, ex_r + ew, ey + s // 2, fill=C_BLACK, width=2)
        else:
            c.create_oval(ex_l, ey, ex_l + ew, ey + ew, fill=C_EYE, outline="")
            c.create_oval(ex_r, ey, ex_r + ew, ey + ew, fill=C_EYE, outline="")
            # Eye highlights
            hw = max(2, s // 2)
            c.create_oval(ex_l + s, ey + 1, ex_l + s + hw, ey + 1 + hw, fill=C_WHITE, outline="")
            c.create_oval(ex_r + s, ey + 1, ex_r + s + hw, ey + 1 + hw, fill=C_WHITE, outline="")

        # Tail
        tail_off = frame.get("tail", [(0, 0)])[0]
        tx = ox + 16 * s + tail_off[0] * s
        ty = oy + 16 * s + tail_off[1] * s
        c.create_polygon(
            tx, ty, tx + 3 * s, ty - 2 * s, tx + 4 * s, ty - s,
            fill=C_TAN, outline=C_BLACK, width=1,
        )

        # Speech bubble
        now = time.time()
        if self._bubble_text and now < self._bubble_until:
            self._draw_bubble(c, ox + 10 * s, oy - 5)

        # "Zzz" when idle for a while
        if self._state == "idle" and now - self._phrase_cooldown > 30:
            zx = ox + 17 * s
            zy = oy + 2 * s
            c.create_text(zx, zy, text="z", fill=C_TAN_LT, font=("Arial", 8, "bold"))
            c.create_text(zx + 8, zy - 8, text="z", fill=C_TAN_LT, font=("Arial", 6, "bold"))

    def _draw_bubble(self, c, cx, cy):
        """Draw a speech bubble above the pet."""
        text = self._bubble_text
        # Measure text
        font_size = 9
        tw = len(text) * (font_size * 0.6) + 16
        th = font_size + 12
        bx1 = cx - tw / 2
        by1 = cy - th - 8
        bx2 = cx + tw / 2
        by2 = cy - 4

        # Bubble body
        c.create_round_rectangle(bx1, by1, bx2, by2, radius=8,
                                 fill=C_BUBBLE, outline=C_BORDER, width=1)
        # Pointer triangle
        c.create_polygon(
            cx - 4, by2, cx + 4, by2, cx, by2 + 6,
            fill=C_BUBBLE, outline=C_BORDER, width=1,
        )
        # Text
        c.create_text(cx, (by1 + by2) / 2, text=text,
                      fill=C_BUBBLE_T, font=("Arial", font_size, "bold"),
                      width=int(tw - 10))

    # ── Interaction ──────────────────────────────────────────────────────────

    def _on_click(self, event):
        self._dragging = True
        self._drag_offset = (event.x, event.y)
        self._state = "happy"
        if time.time() > self._phrase_cooldown:
            self.show_bubble("Hey! :3", 2.0)
            self._phrase_cooldown = time.time() + 5

    def _on_drag(self, event):
        if self._dragging and self._window:
            dx = event.x - self._drag_offset[0]
            dy = event.y - self._drag_offset[1]
            self._x += dx
            self._y += dy
            self._window.geometry(f"+{self._x}+{self._y}")

    def _on_release(self, event):
        self._dragging = False
        self._window.after(2000, lambda: self._set_state("idle"))

    def _on_double_click(self, event):
        self._state = "happy"
        self.show_bubble("Woof woof!", 3.0)
        self._phrase_cooldown = time.time() + 8

    def _on_right_click(self, event):
        """Context menu."""
        try:
            import tkinter as tk
            menu = tk.Menu(self._window, tearoff=0, bg=C_BG, fg=C_CREAM,
                          activebackground=C_TAN, activeforeground=C_BLACK)
            menu.add_command(label="Pet", command=lambda: self.show_bubble("*happy noises*", 2.0))
            menu.add_command(label="Sleep", command=lambda: self._go_to_sleep())
            menu.add_command(label="Hide", command=lambda: self._hide())
            menu.add_separator()
            menu.add_command(label="Close", command=lambda: self.stop())
            menu.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass

    def _go_to_sleep(self):
        self._state = "sleep"
        self.show_bubble("zzZ...", 5.0)
        self._sleep_until = time.time() + 30
        self._window.after(10000, lambda: self._set_state("idle"))

    def _hide(self):
        if self._window:
            self._window.withdraw()
            self._window.after(10000, lambda: self._window.deiconify() if self._window else None)

    def status(self) -> dict:
        return {
            "running": self._running,
            "state": self._state,
            "position": {"x": self._x, "y": self._y},
            "bubble": self._bubble_text if time.time() < self._bubble_until else "",
        }


_pet_instance: DesktopPet | None = None


def get_pet() -> DesktopPet:
    global _pet_instance
    if _pet_instance is None:
        _pet_instance = DesktopPet()
    return _pet_instance
