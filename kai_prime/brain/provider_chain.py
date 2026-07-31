"""Enhanced LLM Provider Chain — multi-provider with Ollama fallback, exponential backoff, TPM rate limiting."""
from __future__ import annotations
import json, os, random, time, logging
from threading import Lock
from pathlib import Path

log = logging.getLogger("kai_prime.providers")

try:
    import requests
except ImportError:
    requests = None

_WINDOW_SECS = 60


def _is_transient(e: Exception) -> bool:
    err = str(e).lower()
    if isinstance(e, (ConnectionError, TimeoutError)):
        return True
    return any(k in err for k in ["429", "rate limit", "timeout", "connection", "refused", "reset", "too many requests"])


def _is_permanent(e: Exception) -> bool:
    err = str(e).lower()
    return any(k in err for k in ["401", "402", "403", "unauthorized", "invalid api key", "400", "413", "422", "bad request", "payment required"])


class ProviderChain:
    """Multi-provider LLM with retry, backoff, TPM limiting, Ollama fallback."""

    def __init__(self, workspace: Path, config_path: Path | None = None):
        self.workspace = workspace
        self.config_path = config_path or workspace / "kai_config.json"
        self._providers: list[dict] = []
        self._tpm_window: dict[str, list[tuple[float, int]]] = {}
        self._lock = Lock()
        self._dead: set[str] = set()
        self._ollama_alive: bool | None = None
        self._ollama_checked: float = 0
        self._init_providers()

    def _load_key(self, key: str) -> str:
        env = os.environ.get(key, "").strip()
        if env:
            return env
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                return str(data.get(key, "")).strip()
            except Exception:
                pass
        return ""

    def _load_config(self, key: str, default=None):
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                return data.get(key, default)
            except Exception:
                pass
        return default

    def _init_providers(self):
        self._providers = []
        groq_key = self._load_key("groq_api_key") or self._load_key("GROQ_API_KEY")
        if groq_key:
            self._providers.append({
                "name": "groq", "api_key": groq_key,
                "base_url": "https://api.groq.com/openai/v1",
                "model": self._load_config("groq_model", "llama-3.3-70b-versatile"),
                "timeout": 15, "tpm_limit": 5500, "retry_attempts": 2,
            })
        ds_key = self._load_key("deepseek_api_key") or self._load_key("DEEPSEEK_API_KEY")
        if ds_key:
            self._providers.append({
                "name": "deepseek", "api_key": ds_key,
                "base_url": "https://api.deepseek.com/v1",
                "model": self._load_config("deepseek_model", "deepseek-chat"),
                "timeout": 30, "tpm_limit": 60000, "retry_attempts": 1,
            })
        oai_key = self._load_key("openai_api_key") or self._load_key("OPENAI_API_KEY")
        if oai_key:
            self._providers.append({
                "name": "openai", "api_key": oai_key,
                "base_url": "https://api.openai.com/v1",
                "model": self._load_config("openai_model", "gpt-4o-mini"),
                "timeout": 15, "tpm_limit": 100000, "retry_attempts": 1,
            })
        ollama_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        self._providers.append({
            "name": "ollama", "api_key": "",
            "base_url": ollama_url,
            "model": self._load_config("ollama_model", "llama3.2:3b"),
            "timeout": 180, "tpm_limit": 999999, "retry_attempts": 0,
        })
        log.info("ProviderChain initialized: %s", [p["name"] for p in self._providers])

    def _record_tpm(self, name: str, chars: int):
        now = time.time()
        with self._lock:
            window = self._tpm_window.get(name, [])
            window.append((now, chars))
            cutoff = now - _WINDOW_SECS
            self._tpm_window[name] = [(t, c) for t, c in window if t > cutoff]

    def _would_exceed_tpm(self, name: str, chars: int) -> bool:
        limit = None
        for p in self._providers:
            if p["name"] == name:
                limit = p.get("tpm_limit")
                break
        if not limit:
            return False
        cutoff = time.time() - _WINDOW_SECS
        used = sum(c for t, c in self._tpm_window.get(name, []) if t > cutoff)
        est = chars // 4 + 1
        return (used + est) > limit

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024) -> str | None:
        """Try providers in order with retry + backoff. Returns None if all fail."""
        if not requests:
            return None
        input_chars = sum(len(m.get("content", "")) for m in messages)
        errors = []
        for p in self._providers:
            name = p["name"]
            if name in self._dead:
                continue
            if self._would_exceed_tpm(name, input_chars):
                errors.append(f"{name}: TPM limit")
                continue
            if name == "ollama":
                now = time.time()
                if self._ollama_alive is None or now - self._ollama_checked > 30:
                    self._ollama_alive = self._check_ollama()
                    self._ollama_checked = now
                if not self._ollama_alive:
                    self._dead.add(name)
                    continue
            elif not p.get("api_key"):
                continue
            retries = p.get("retry_attempts", 1)
            for attempt in range(retries + 1):
                try:
                    if name == "ollama":
                        reply = self._call_ollama(p, messages)
                    else:
                        reply = self._call_openai(p, messages, temperature, max_tokens)
                    if reply:
                        self._record_tpm(name, input_chars // 4 + len(reply) // 4 + 1)
                        return reply
                except Exception as e:
                    if _is_permanent(e):
                        log.warning("Provider %s permanent error: %s", name, e)
                        self._dead.add(name)
                        break
                    if attempt < retries and _is_transient(e):
                        delay = min(1.0 * (2 ** attempt) + random.uniform(0, 0.5), 10.0)
                        time.sleep(delay)
                        continue
                    log.warning("Provider %s failed: %s", name, e)
                    break
            errors.append(f"{name}: failed")
        log.warning("All providers failed: %s", errors)
        return None

    def _check_ollama(self) -> bool:
        try:
            resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def _call_openai(self, p: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
        resp = requests.post(
            f"{p['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {p['api_key']}", "Content-Type": "application/json"},
            json={"model": p["model"], "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=p.get("timeout", 15),
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")

    def _call_ollama(self, p: dict, messages: list[dict]) -> str:
        resp = requests.post(
            p["base_url"].rstrip("/") + "/api/chat",
            json={"model": p["model"], "messages": messages, "stream": False, "options": {"num_gpu": 0}},
            timeout=p.get("timeout", 180),
        )
        resp.raise_for_status()
        data = resp.json()
        if "message" in data and "content" in data["message"]:
            return data["message"]["content"]
        raise Exception("Unexpected Ollama response")

    @property
    def available_providers(self) -> list[str]:
        return [p["name"] for p in self._providers if p.get("api_key") or p["name"] == "ollama"]

    @property
    def has_cloud_provider(self) -> bool:
        return any(p.get("api_key") for p in self._providers if p["name"] != "ollama")

    @property
    def provider(self) -> str:
        return self._providers[0]["name"] if self._providers else "offline"

    @property
    def model(self) -> str:
        return self._providers[0]["model"] if self._providers else "none"

    def vision_chat(self, image_path: str, prompt: str, temperature: float = 0.3, max_tokens: int = 1024) -> str | None:
        """Send an image to a vision model and get a text description."""
        if not requests:
            return None
        import base64
        try:
            with open(image_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            log.warning("Failed to read image %s: %s", image_path, e)
            return None

        ext = image_path.lower().rsplit(".", 1)[-1] if "." in image_path else "png"
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
        data_url = f"data:{mime};base64,{img_data}"

        vision_models = [
            "qwen/qwen3.6-27b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ]

        for p in self._providers:
            if p["name"] in self._dead:
                continue
            if p["name"] == "ollama":
                continue
            if not p.get("api_key"):
                continue

            for vmodel in vision_models:
                try:
                    resp = requests.post(
                        f"{p['base_url']}/chat/completions",
                        headers={"Authorization": f"Bearer {p['api_key']}", "Content-Type": "application/json"},
                        json={
                            "model": vmodel,
                            "messages": [{
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": data_url}},
                                ]
                            }],
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        result = resp.json()["choices"][0]["message"]["content"]
                        log.info("Vision (%s) succeeded", vmodel)
                        return result
                    else:
                        log.info("Vision %s returned %d: %s", vmodel, resp.status_code, resp.text[:100])
                except Exception as e:
                    log.info("Vision %s failed: %s", vmodel, e)
                    continue

            break

        return None
