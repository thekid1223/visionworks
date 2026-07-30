"""Desktop notification system — always-on-top toast notifications."""
from __future__ import annotations
import logging, threading, time, tkinter as tk
from tkinter import font as tkfont

log = logging.getLogger("kai_prime.notify")

_active_notifications: list = []


def notify(title: str, message: str, duration: float = 8.0, urgent: bool = False):
    """Show an always-on-top toast notification. Call from any thread."""
    threading.Thread(target=_show_toast, args=(title, message, duration, urgent), daemon=True).start()


def _show_toast(title: str, message: str, duration: float, urgent: bool):
    try:
        root = tk.Tk()
        root.withdraw()
        root.after(0, lambda: _build_toast(root, title, message, duration, urgent))
        root.mainloop()
    except Exception as e:
        log.warning("Notification failed: %s", e)
        print(f"[NOTIFY] {title}: {message}")


def _build_toast(root: tk.Tk, title: str, message: str, duration: float, urgent: bool):
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    win = tk.Toplevel(root)
    win.title("Kai Prime")
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    try:
        win.attributes("-alpha", 0.95)
    except Exception:
        pass

    width = 500
    height = 220
    x = screen_w - width - 20
    y = screen_h - height - 60

    bg = "#1a1a2e" if not urgent else "#4a0000"
    border = "#00d4ff" if not urgent else "#ff4444"

    win.geometry(f"{width}x{height}+{x}+{y}")
    win.configure(bg=border)
    win.protocol("WM_DELETE_WINDOW", lambda: _close(win, root))

    inner = tk.Frame(win, bg=bg, padx=2, pady=2)
    inner.pack(fill="both", expand=True)

    header = tk.Frame(inner, bg=bg)
    header.pack(fill="x", padx=10, pady=(8, 2))

    icon_text = "⚡" if urgent else "🗡"
    tk.Label(header, text=icon_text, font=("Segoe UI Emoji", 16), bg=bg, fg="#00d4ff").pack(side="left")
    tk.Label(header, text=title, font=("Segoe UI", 12, "bold"), bg=bg, fg="#00d4ff").pack(side="left", padx=8)

    msg_label = tk.Label(
        inner, text=message, font=("Segoe UI", 10),
        bg=bg, fg="#e0e0e0", wraplength=460, justify="left", anchor="nw"
    )
    msg_label.pack(fill="both", expand=True, padx=12, pady=(2, 8))

    _active_notifications.append(win)
    win.after(int(duration * 1000), lambda: _close(win, root))


def _close(win: tk.Toplevel, root: tk.Tk):
    try:
        if win in _active_notifications:
            _active_notifications.remove(win)
        win.destroy()
        if not _active_notifications:
            root.after(200, root.destroy)
    except Exception:
        pass


def notify_move(title: str, move: str, advice: str):
    """Chess-specific notification with move + advice."""
    notify(title, f"Move: {move}\n\n{advice}", duration=12.0, urgent=True)


def notify_reminder(title: str, text: str):
    notify(f"Reminder: {title}", text, duration=10.0, urgent=True)


TOOLS = {
    "send_notification": {
        "description": "Send a desktop notification that appears on screen. Args: title (required), message (required), urgent (optional bool)",
        "function": lambda title="Kai", message="", urgent=False: (
            notify(title, message, urgent=urgent),
            "Notification sent"
        )[-1],
        "params": {"title": "str", "message": "str", "urgent": "bool"},
    },
}
