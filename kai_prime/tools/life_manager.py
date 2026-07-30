"""Life Manager — reminders, tasks, and email monitoring."""
from __future__ import annotations
import json, logging, smtplib, threading, time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

log = logging.getLogger("kai_prime.life")


class Reminders:
    """Persistent reminders with time-based triggers."""

    def __init__(self, workspace: Path):
        self._path = workspace / "kai_prime_data" / "reminders.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._reminders: list[dict] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._reminders = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _save(self):
        try:
            self._path.write_text(json.dumps(self._reminders, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

    def add(self, text: str, remind_at: str = "", recurring: str = "") -> dict:
        reminder = {
            "id": f"rem-{int(time.time() * 1000)}",
            "text": text[:500],
            "remind_at": remind_at,
            "recurring": recurring,
            "created": datetime.now(timezone.utc).isoformat(),
            "fired": False,
        }
        with self._lock:
            self._reminders.append(reminder)
            self._save()
        return reminder

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [r for r in self._reminders if not r.get("fired")]

    def list_all(self) -> list[dict]:
        with self._lock:
            return list(self._reminders)

    def cancel(self, reminder_id: str) -> bool:
        with self._lock:
            for r in self._reminders:
                if r["id"] == reminder_id:
                    r["fired"] = True
                    self._save()
                    return True
        return False

    def check_due(self) -> list[dict]:
        now = time.time()
        due = []
        with self._lock:
            for r in self._reminders:
                if r.get("fired"):
                    continue
                remind_at = r.get("remind_at", "")
                if remind_at:
                    try:
                        target = datetime.fromisoformat(remind_at).timestamp()
                        if now >= target:
                            due.append(r)
                            if not r.get("recurring"):
                                r["fired"] = True
                    except Exception:
                        pass
        if due:
            self._save()
        return due

    def status(self) -> dict:
        with self._lock:
            return {"total": len(self._reminders), "pending": len([r for r in self._reminders if not r.get("fired")])}


class Tasks:
    """Simple task queue with priority and status tracking."""

    def __init__(self, workspace: Path):
        self._path = workspace / "kai_prime_data" / "tasks.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: list[dict] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._tasks = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _save(self):
        try:
            self._path.write_text(json.dumps(self._tasks, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

    def add(self, title: str, priority: str = "medium", details: str = "") -> dict:
        task = {
            "id": f"task-{int(time.time() * 1000)}",
            "title": title[:500], "priority": priority,
            "details": details[:1000], "status": "pending",
            "created": datetime.now(timezone.utc).isoformat(),
            "completed": None,
        }
        with self._lock:
            self._tasks.append(task)
            self._save()
        return task

    def complete(self, task_id: str) -> bool:
        with self._lock:
            for t in self._tasks:
                if t["id"] == task_id:
                    t["status"] = "completed"
                    t["completed"] = datetime.now(timezone.utc).isoformat()
                    self._save()
                    return True
        return False

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [t for t in self._tasks if t.get("status") == "pending"]

    def list_all(self) -> list[dict]:
        with self._lock:
            return list(self._tasks)

    def status(self) -> dict:
        with self._lock:
            pending = [t for t in self._tasks if t.get("status") == "pending"]
            done = [t for t in self._tasks if t.get("status") == "completed"]
            return {"pending": len(pending), "completed": len(done), "total": len(self._tasks)}


class EmailMonitor:
    """IMAP email monitoring for incoming messages."""

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._config_path = workspace / "kai_config.json"
        self._config = self._load_email_config()

    def _load_email_config(self) -> dict:
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text(encoding="utf-8"))
                return data.get("email", {})
            except Exception:
                pass
        return {}

    def check_inbox(self, limit: int = 10) -> list[dict]:
        if not self._config.get("imap_server"):
            return [{"error": "Email not configured. Add email settings to kai_config.json"}]
        try:
            import imaplib
            mail = imaplib.IMAP4_SSL(self._config["imap_server"])
            mail.login(self._config.get("email", ""), self._config.get("password", ""))
            mail.select("INBOX")
            _, data = mail.search(None, "UNSEEN")
            ids = data[0].split()[-limit:]
            messages = []
            for mid in ids:
                _, msg_data = mail.fetch(mid, "(RFC822)")
                import email
                msg = email.message_from_bytes(msg_data[0][1])
                messages.append({
                    "from": msg.get("From", ""),
                    "subject": msg.get("Subject", ""),
                    "date": msg.get("Date", ""),
                })
            mail.logout()
            return messages
        except Exception as e:
            return [{"error": f"Email check failed: {e}"}]

    def status(self) -> dict:
        configured = bool(self._config.get("imap_server"))
        return {"configured": configured, "server": self._config.get("imap_server", "not set")}
