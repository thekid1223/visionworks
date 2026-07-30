"""Kai Prime — System Tray App with Chat + Status tabs.
Double-click tray to open, right-click to quit.
"""

from __future__ import annotations
import os, queue, sys, threading, time, tkinter as tk
from tkinter import ttk, scrolledtext
from pathlib import Path

try:
    import win32event, win32api
    _MUTEX = win32event.CreateMutex(None, False, "KaiPrimeTrayApp")
    if win32api.GetLastError() == 183:
        print("Kai Prime tray app is already running.")
        sys.exit(0)
except Exception:
    pass

import requests, win32api, win32con, win32gui
from win32gui import NIM_ADD, NIM_DELETE, NIF_ICON, NIF_MESSAGE, NIF_TIP
from PIL import Image, ImageDraw, ImageFont

WORKSPACE = Path(__file__).resolve().parent.parent
KAI_URL = "http://localhost:8080"
ICON_FILE = WORKSPACE / "kai_prime" / "assets" / "kai.ico"

POLL_INTERVAL = 3000  # ms for status refresh


def _ensure_icon():
    if ICON_FILE.exists():
        return
    ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 29, 29], fill=(72, 133, 237, 255))
    try:
        f = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        f = ImageFont.load_default()
    b = draw.textbbox((0, 0), "K", font=f)
    draw.text((16 - (b[2] - b[0]) / 2, 15 - (b[3] - b[1]) / 2), "K", fill=(255, 255, 255), font=f)
    img.save(ICON_FILE, format="ICO", sizes=[(32, 32)])


class TrayApp:
    def __init__(self):
        _ensure_icon()
        self._q: queue.Queue = queue.Queue()
        self._win: tk.Tk | None = None
        self._notebook: ttk.Notebook | None = None
        self._chat: scrolledtext.ScrolledText | None = None
        self._entry: tk.Text | None = None
        self._history: list[dict] = []
        self._status_text: tk.Text | None = None
        self._hWnd = 0
        self._hIcon = 0
        self._ID = 1001
        self._WM_TRAY = win32con.WM_USER + 20
        self._WM_MENU = win32con.WM_USER + 21
        self._daemon_buttons: dict[str, tk.Button] = {}
        threading.Thread(target=self._boot, daemon=True).start()

    def _boot(self):
        try:
            if requests.get(f"{KAI_URL}/api/health", timeout=2).status_code == 200:
                return
        except Exception:
            pass
        sys.path.insert(0, str(WORKSPACE))
        from kai_prime import main as m
        m.main()

    def _wait_ready(self, timeout=60):
        time.sleep(3)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                r = requests.get(f"{KAI_URL}/api/health", timeout=2)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    # ── Tray ──

    def _tray(self):
        mod = win32api.GetModuleHandle(None)
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._proc
        wc.hInstance = mod
        wc.lpszClassName = "KaiTray"
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass
        self._hWnd = win32gui.CreateWindow("KaiTray", "Kai", win32con.WS_OVERLAPPED,
                                           0, 0, 0, 0, 0, 0, mod, None)
        self._hIcon = win32gui.LoadImage(mod, str(ICON_FILE),
                                          win32con.IMAGE_ICON, 32, 32,
                                          win32con.LR_LOADFROMFILE)
        win32gui.Shell_NotifyIcon(NIM_ADD,
            (self._hWnd, self._ID,
             NIF_ICON | NIF_MESSAGE | NIF_TIP,
             self._WM_TRAY, self._hIcon, "Kai Prime"))

    def _proc(self, hWnd, msg, wParam, lParam):
        if msg == self._WM_TRAY:
            if lParam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK):
                self._show()
            elif lParam == win32con.WM_RBUTTONUP:
                self._menu()
        elif msg == self._WM_MENU:
            if wParam == 1002:
                self._show()
            elif wParam == 1003:
                self._quit()
        return win32gui.DefWindowProc(hWnd, msg, wParam, lParam)

    def _menu(self):
        m = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(m, win32con.MF_STRING, 1002, "Open Kai")
        win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(m, win32con.MF_STRING, 1003, "Quit")
        p = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self._hWnd)
        c = win32gui.TrackPopupMenu(m,
            win32con.TPM_LEFTALIGN | win32con.TPM_RETURNCMD,
            p[0], p[1], 0, self._hWnd, None)
        if c:
            win32gui.PostMessage(self._hWnd, self._WM_MENU, c, 0)
        win32gui.PostMessage(self._hWnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(m)

    def _clean_tray(self):
        if self._hWnd:
            win32gui.Shell_NotifyIcon(NIM_DELETE, (self._hWnd, self._ID))
            if self._hIcon:
                win32gui.DestroyIcon(self._hIcon)
            win32gui.DestroyWindow(self._hWnd)

    # ── Window ──

    def _build_status_tab(self, parent):
        bg, fg, ibg = "#1e1e2e", "#cdd6f4", "#313244"
        ac = "#89b4fa"
        fn = ("Segoe UI", 10)

        main = tk.Frame(parent, bg=bg)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        col_left = tk.Frame(main, bg=bg)
        col_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        col_right = tk.Frame(main, bg=bg)
        col_right.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        self._status_text = tk.Text(col_left, wrap=tk.WORD, bg=ibg, fg=fg,
                                     insertbackground=fg, font=fn,
                                     border=2, highlightthickness=0, state=tk.DISABLED,
                                     relief=tk.FLAT, padx=8, pady=8)
        self._status_text.pack(fill=tk.BOTH, expand=True)

        # Right panel: daemon toggle buttons
        tk.Label(col_right, text="Daemons", bg=bg, fg=ac,
                 font=(fn[0], fn[1], "bold")).pack(pady=(0, 6))

        daemon_names = {
            "watcher": "Watcher",
            "watchguard": "Watchguard",
            "port_whisperer": "Port Whisperer",
            "traffic_eye": "Traffic Eye",
            "digital_twin": "Digital Twin",
            "clipboard_monitor": "Clipboard",
            "scheduler": "Scheduler",
            "file_search": "File Search",
        }
        for key, label in daemon_names.items():
            self._daemon_buttons[key] = tk.Button(
                col_right, text=label, bg=ibg, fg=fg,
                font=fn, border=1, cursor="hand2",
                disabledforeground=fg, padx=8, pady=2, anchor=tk.W)
            self._daemon_buttons[key].pack(fill=tk.X, pady=2)
            self._daemon_buttons[key].config(state=tk.DISABLED)

        # Refresh button
        tk.Button(col_right, text="Refresh", bg=ac, fg=bg,
                  font=(fn[0], fn[1], "bold"), border=0, padx=8, pady=4,
                  command=self._fetch_status, cursor="hand2"
                  ).pack(pady=(12, 0))

    def _show(self):
        if self._win is not None:
            try:
                self._win.deiconify()
                self._win.lift()
                self._win.focus_force()
                if self._entry:
                    self._entry.focus_set()
                return
            except tk.TclError:
                self._win = None

        bg, fg, ibg = "#1e1e2e", "#cdd6f4", "#313244"
        ac = "#89b4fa"
        fn = ("Segoe UI", 10)
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        self._win = tk.Tk()
        self._win.title("Kai Prime")
        self._win.geometry("720x540")
        self._win.minsize(500, 350)
        try:
            self._win.iconbitmap(default=str(ICON_FILE))
        except Exception:
            pass
        self._win.configure(bg=bg)
        self._win.protocol("WM_DELETE_WINDOW", self._hide)
        self._win.bind("<Control-w>", lambda e: self._hide())
        self._win.bind("<Control-Tab>", lambda e: self._switch_tab())

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", background=ibg, fg=fg,
                        padding=[12, 4], font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", ac)],
                  foreground=[("selected", bg)])

        self._notebook = ttk.Notebook(self._win)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))

        # ── Chat tab (display only, no input) ──
        chat_frame = tk.Frame(self._notebook, bg=bg)
        self._notebook.add(chat_frame, text=" Chat ")

        fn = ("Segoe UI", 11)
        self._chat = scrolledtext.ScrolledText(
            chat_frame, wrap=tk.WORD, bg=bg, fg=fg,
            insertbackground=fg, font=fn,
            padx=12, pady=12, border=0, highlightthickness=0, state=tk.DISABLED)
        self._chat.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._chat.tag_configure("user", foreground=ac, font=(fn[0], fn[1], "bold"))
        self._chat.tag_configure("kai", foreground=fg)
        self._chat.tag_configure("err", foreground="#f38ba8")

        # ── Status tab ──
        status_frame = tk.Frame(self._notebook, bg=bg)
        self._notebook.add(status_frame, text=" Status ")
        self._build_status_tab(status_frame)

        # ── Input frame (outside notebook, always visible) ──
        fr = tk.Frame(self._win, bg=ibg)
        fr.pack(fill=tk.X, padx=6, pady=6)
        self._entry = tk.Entry(fr, bg="#2d2d3d", fg="#ffffff", insertbackground="#ffffff",
                               font=fn, relief=tk.SUNKEN, borderwidth=2)
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=4, ipady=6)
        self._entry.bind("<Return>", self._send)
        self._entry.focus_set()
        tk.Button(fr, text="Send", command=lambda: self._send(None),
                  bg=ac, fg=bg, font=(fn[0], fn[1], "bold"),
                  border=0, padx=12, pady=4, cursor="hand2"
                  ).pack(side=tk.RIGHT, padx=(0, 6), pady=6)

        for m in self._history:
            self._append(m)
        self._poll()
        self._fetch_status()

    def _switch_tab(self):
        if self._notebook:
            cur = self._notebook.index("current")
            nxt = (cur + 1) % self._notebook.index("end")
            self._notebook.select(nxt)

    def _hide(self):
        if self._win:
            self._win.withdraw()

    def _append(self, msg):
        if not self._chat:
            return
        r, t = msg.get("role", "kai"), msg.get("content", "")
        tag = r if r in ("user", "kai", "err") else "kai"
        p = "You" if r == "user" else "Kai"
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, f"{p}: ", tag)
        self._chat.insert(tk.END, f"{t}\n\n", tag)
        self._chat.see(tk.END)
        self._chat.config(state=tk.DISABLED)

    def _send(self, e):
        if not self._entry:
            return "break"
        t = self._entry.get().strip()
        if not t:
            return "break"
        self._entry.delete(0, tk.END)
        m = {"role": "user", "content": t}
        self._history.append(m)
        self._append(m)
        self._entry.config(state=tk.DISABLED)

        def _do():
            try:
                r = requests.post(f"{KAI_URL}/api/ask", json={"message": t}, timeout=120)
                r2 = r.json().get("response", "") if r.ok else f"HTTP {r.status_code}"
            except requests.ConnectionError:
                r2 = "Kai server is not responding."
            except Exception as ex:
                r2 = f"Error: {ex}"
            m2 = {"role": "kai", "content": r2}
            self._history.append(m2)
            if self._win:
                self._win.after(0, lambda: self._append(m2))
                self._win.after(0, lambda: self._entry.config(state=tk.NORMAL))

        threading.Thread(target=_do, daemon=True).start()
        return "break"

    def _poll(self):
        if self._win:
            try:
                while True:
                    self._append(self._q.get_nowait())
            except queue.Empty:
                pass
            self._win.after(2000, self._poll)

    def _fetch_status(self):
        if not self._win or not self._status_text:
            return
        try:
            r = requests.get(f"{KAI_URL}/api/system/daemons", timeout=5)
            data = r.json() if r.ok else {}
        except Exception:
            self._win.after(POLL_INTERVAL, self._fetch_status)
            return

        cpu = data.get("cpu_percent", "?")
        mem = data.get("memory_mb", "?")
        uptime = data.get("uptime", "?")
        tools = data.get("tools", "?")
        daemons = data

        lines = []
        lines.append(f"  Uptime: {uptime}s")
        lines.append(f"  CPU:    {cpu}%")
        lines.append(f"  RAM:    {mem} MB")
        lines.append(f"  Tools:  {tools}")
        lines.append("")
        lines.append("  Daemon Status:")
        active = 0
        total = 0
        for key, label in [("watcher","Watcher"),("watchguard","Watchguard"),
                           ("port_whisperer","Port Whisperer"),("traffic_eye","Traffic Eye"),
                           ("digital_twin","Digital Twin"),("clipboard_monitor","Clipboard"),
                           ("scheduler","Scheduler"),("file_search","File Search")]:
            info = daemons.get(key, {})
            running = info.get("running", False)
            extra = ""
            if key == "watcher":
                extra = f" ({info.get('events', 0)} events)"
            elif key == "file_search":
                extra = f" (indexed={info.get('index_built', False)})"
            status_str = "RUNNING" if running else "stopped"
            lines.append(f"    {label:20s} {status_str}{extra}")
            if running:
                active += 1
            total += 1
            self._update_daemon_button(key, running)
        lines.append("")
        lines.append(f"  {active}/{total} daemons active")

        self._status_text.config(state=tk.NORMAL)
        self._status_text.delete("1.0", tk.END)
        self._status_text.insert("1.0", "\n".join(lines))
        self._status_text.config(state=tk.DISABLED)

        if self._win:
            self._win.after(POLL_INTERVAL, self._fetch_status)

    def _update_daemon_button(self, key, running):
        btn = self._daemon_buttons.get(key)
        if not btn:
            return
        label_map = {
            "watcher": "Watcher", "watchguard": "Watchguard",
            "port_whisperer": "Port Whisperer", "traffic_eye": "Traffic Eye",
            "digital_twin": "Digital Twin", "clipboard_monitor": "Clipboard",
            "scheduler": "Scheduler", "file_search": "File Search",
        }
        label = label_map.get(key, key)
        if running:
            btn.config(text=f"{label}: RUNNING", bg="#2d4a2d", fg="#a6e3a1")
        else:
            btn.config(text=f"{label}: stopped", bg="#4a2d2d", fg="#f38ba8")

    # ── Lifecycle ──

    def run(self):
        self._tray()
        ready = self._wait_ready()
        if ready:
            self._show()
        else:
            self._q.put({"role": "err", "content": "Kai server failed to start."})
            self._show()
        tk.mainloop()

    def _quit(self):
        self._clean_tray()
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
        try:
            requests.post(f"{KAI_URL}/api/shutdown", timeout=2)
        except Exception:
            pass
        os._exit(0)


if __name__ == "__main__":
    TrayApp().run()
