"""Auto backup/restore of the business SQLite DB to a private GitHub repo.

Render free tier uses an ephemeral filesystem — every redeploy/restart wipes the
disk, so the local SQLite DB is lost. This module pushes the DB to a private
GitHub repo on a dedicated branch and restores it on a fresh start.
"""
import base64, logging, os, sqlite3, threading, time
from pathlib import Path

log = logging.getLogger("kai_prime.db_sync")

try:
    import requests
except ImportError:
    requests = None

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
BACKUP_REPO = os.environ.get("BACKUP_REPO", "thekid1223/visionworks-backup")
BACKUP_BRANCH = os.environ.get("BACKUP_BRANCH", "backup")
BACKUP_FILE = "kai_prime_data/business.db"
API = "https://api.github.com"

DB_PATH = Path(__file__).resolve().parent / "kai_prime_data" / "business.db"

_backup_lock = threading.Lock()
_last_backup = 0.0


def _headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "kai-prime",
    }


def _ensure_branch() -> bool:
    if not requests:
        return False
    owner, repo = BACKUP_REPO.strip("/").split("/", 1)
    try:
        r = requests.get(f"{API}/repos/{owner}/{repo}", headers=_headers(), timeout=30)
        if r.status_code != 200:
            log.warning("db_sync: cannot read repo %s: %s", BACKUP_REPO, r.status_code)
            return False
        default = r.json().get("default_branch", "main")
        r = requests.get(f"{API}/repos/{owner}/{repo}/git/ref/heads/{default}", headers=_headers(), timeout=30)
        if r.status_code == 409:
            if DB_PATH.exists():
                content = base64.b64encode(DB_PATH.read_bytes()).decode("ascii")
                r = requests.put(f"{API}/repos/{owner}/{repo}/contents/{BACKUP_FILE}",
                                 headers=_headers(), json={"message": "initial backup", "content": content}, timeout=60)
                if r.status_code not in (200, 201):
                    log.warning("db_sync: empty repo init failed %s: %s", r.status_code, r.text[:200])
                    return False
            else:
                r = requests.put(f"{API}/repos/{owner}/{repo}/contents/README.md",
                                 headers=_headers(), json={"message": "init", "content": "backup"}, timeout=60)
                if r.status_code not in (200, 201):
                    return False
        elif r.status_code != 200:
            return False
        r = requests.get(f"{API}/repos/{owner}/{repo}/git/ref/heads/{default}", headers=_headers(), timeout=30)
        if r.status_code != 200:
            return False
        sha = r.json()["object"]["sha"]
        r = requests.get(f"{API}/repos/{owner}/{repo}/git/ref/heads/{BACKUP_BRANCH}", headers=_headers(), timeout=30)
        if r.status_code == 200:
            return True
        r = requests.post(f"{API}/repos/{owner}/{repo}/git/refs", headers=_headers(),
                          json={"ref": f"refs/heads/{BACKUP_BRANCH}", "sha": sha}, timeout=30)
        return r.status_code in (200, 201)
    except Exception as e:
        log.warning("db_sync: ensure branch error: %s", e)
        return False


def _file_sha():
    owner, repo = BACKUP_REPO.strip("/").split("/", 1)
    try:
        r = requests.get(f"{API}/repos/{owner}/{repo}/contents/{BACKUP_FILE}",
                         headers=_headers(), params={"ref": BACKUP_BRANCH}, timeout=30)
        if r.status_code == 200:
            return r.json().get("sha")
    except Exception as e:
        log.warning("db_sync: get sha error: %s", e)
    return None


def backup():
    """Upload a consistent snapshot of the local DB to the backup branch."""
    global _last_backup
    if not requests or not GITHUB_TOKEN or not DB_PATH.exists():
        return
    with _backup_lock:
        if time.time() - _last_backup < 30:
            return
        tmp = DB_PATH.with_suffix(".bak_tmp")
        try:
            src = sqlite3.connect(str(DB_PATH))
            dst = sqlite3.connect(str(tmp))
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            if not tmp.exists():
                return
            content = base64.b64encode(tmp.read_bytes()).decode("ascii")
            tmp.unlink(missing_ok=True)
            if not _ensure_branch():
                return
            owner, repo = BACKUP_REPO.strip("/").split("/", 1)
            payload = {"message": "auto-backup business.db", "content": content, "branch": BACKUP_BRANCH}
            sha = _file_sha()
            if sha:
                payload["sha"] = sha
            r = requests.put(f"{API}/repos/{owner}/{repo}/contents/{BACKUP_FILE}",
                             headers=_headers(), json=payload, timeout=60)
            if r.status_code in (200, 201):
                _last_backup = time.time()
                log.info("db_sync: backed up %d bytes", DB_PATH.stat().st_size)
            else:
                log.warning("db_sync: backup upload failed %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("db_sync: backup error: %s", e)
        finally:
            tmp.unlink(missing_ok=True)


def restore():
    """Restore the DB from the backup branch if the local DB is missing/fresh."""
    if not requests or not GITHUB_TOKEN:
        return
    if DB_PATH.exists():
        try:
            with sqlite3.connect(str(DB_PATH)) as c:
                n = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            if n > 0:
                return
        except Exception:
            return
    owner, repo = BACKUP_REPO.strip("/").split("/", 1)
    try:
        r = requests.get(f"{API}/repos/{owner}/{repo}/contents/{BACKUP_FILE}",
                         headers=_headers(), params={"ref": BACKUP_BRANCH}, timeout=30)
        if r.status_code != 200:
            log.info("db_sync: no backup to restore")
            return
        data = base64.b64decode(r.json()["content"])
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        DB_PATH.write_bytes(data)
        log.info("db_sync: restored %d bytes from backup", len(data))
    except Exception as e:
        log.warning("db_sync: restore error: %s", e)


def start_background():
    """Restore once, then periodically upload the DB. Idempotent."""
    restore()
    t = threading.Thread(target=_loop, daemon=True, name="db-sync")
    t.start()


def _loop():
    while True:
        time.sleep(45)
        try:
            backup()
        except Exception:
            pass
