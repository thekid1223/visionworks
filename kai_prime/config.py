"""Kai Prime configuration."""
from __future__ import annotations
import logging, logging.handlers, os, socket, subprocess, sys, traceback
from pathlib import Path

WORKSPACE = Path(os.environ.get("KAI_WORKSPACE", Path(__file__).resolve().parent.parent))
KAI_DATA = WORKSPACE / "kai_prime_data"
KAI_DATA.mkdir(parents=True, exist_ok=True)
MEMORY_DIR = KAI_DATA / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR = KAI_DATA / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_log_handler = logging.handlers.RotatingFileHandler(
    LOGS_DIR / "kai_prime.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[_log_handler, logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("kai_prime")

def _load_config_keys():
    locations = [
        WORKSPACE / "kai_config.json",
        Path(__file__).resolve().parent.parent / "kai_config.json",
    ]
    env_cfg = os.environ.get("KAI_CONFIG", "")
    if env_cfg:
        locations.insert(0, Path(env_cfg))
    for cfg in locations:
        if cfg.exists():
            try:
                import json
                data = json.loads(cfg.read_text(encoding="utf-8"))
                g = data.get("GROQ_API_KEY", "") or data.get("groq_api_key", "")
                d = data.get("DEEPSEEK_API_KEY", "") or data.get("deepseek_api_key", "")
                o = data.get("OPENAI_API_KEY", "") or data.get("openai_api_key", "")
                if g or d or o:
                    log.info("Loaded config from %s", cfg)
                    return data, g, d, o
            except Exception as e:
                log.warning("Failed to parse %s: %s", cfg, e)
    log.warning("No API keys found. LLM features will not work.")
    return {}, "", "", ""

_raw_cfg, _cfg_groq, _cfg_deepseek, _cfg_openai = _load_config_keys()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "") or _cfg_groq
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "") or _cfg_deepseek
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "") or _cfg_openai

LLM_PROVIDERS = []
if GROQ_API_KEY:
    LLM_PROVIDERS.append({"name": "groq", "base_url": "https://api.groq.com/openai/v1", "api_key": GROQ_API_KEY, "model": "llama-3.3-70b-versatile"})
if DEEPSEEK_API_KEY:
    LLM_PROVIDERS.append({"name": "deepseek", "base_url": "https://api.deepseek.com/v1", "api_key": DEEPSEEK_API_KEY, "model": "deepseek-chat"})
if OPENAI_API_KEY:
    LLM_PROVIDERS.append({"name": "openai", "base_url": "https://api.openai.com/v1", "api_key": OPENAI_API_KEY, "model": "gpt-4o-mini"})
if not LLM_PROVIDERS:
    LLM_PROVIDERS.append({"name": "groq", "base_url": "https://api.groq.com/openai/v1", "api_key": "", "model": "llama-3.3-70b-versatile"})

SERVER_HOST = os.environ.get("KAI_HOST", "0.0.0.0")
try:
    SERVER_PORT = int(os.environ.get("KAI_PORT", os.environ.get("PORT", "8080")))
except ValueError:
    SERVER_PORT = 8080
BRIDGE_PATH = KAI_DATA / "kai_bridge.json"

DEFAULT_VOICE = "en-US-ChristopherNeural"
TTS_RATE = 155

CRITICAL_RANGES = ("192.168.1.1", "192.168.0.1", "10.0.0.1", "172.16.0.1", "192.168.12.1")
DESTRUCTIVE_MODULES = {
    "windows/smb/ms17_010_eternalblue",
    "windows/smb/ms08_067_netapi",
    "windows/smb/cve_2020_0796_smbghost",
    "windows/rdp/cve_2019_0708_bluekeep_rce",
}
KILLCHAIN_TIMEOUT = 300
SCAN_TIMEOUT = 120
MAX_CONTEXT_TOKENS = 12000
KEEP_RECENT_TURNS = 8
MAX_EPISODES = 500
SUPERVISOR_DEFAULT_ACTIVE = True

def _detect_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        log.warning("Could not detect local IP, using 127.0.0.1")
        return "127.0.0.1"

def _detect_gateway_ip():
    try:
        r = subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-Command",
             "(Get-NetRoute -DestinationPrefix '0.0.0.0/0').NextHop | Select -First 1"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.strip()
        if r.count(".") == 3:
            return r
    except Exception:
        log.warning("Could not detect gateway IP")
    return ""

LOCAL_IP = _detect_local_ip()
GATEWAY_IP = _detect_gateway_ip()
