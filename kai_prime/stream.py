"""Bridge stream — in-memory state with optional disk persistence."""
from __future__ import annotations
import json, logging, time, threading
from pathlib import Path
from kai_prime.config import BRIDGE_PATH

log = logging.getLogger("kai_prime.stream")

_lock = threading.Lock()
_MAX_STREAM = 50
_cache: dict = {}

def _read() -> dict:
    return dict(_cache)

def _write(data: dict):
    global _cache
    _cache = data
    try:
        BRIDGE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Bridge disk write failed (non-critical): %s", e)

def write(msg: str, typ: str = "progress"):
    entry = {"msg": msg, "ts": time.time(), "type": typ}
    with _lock:
        data = _read()
        stream = data.get("kai_status_stream", [])
        stream.append(entry)
        if len(stream) > _MAX_STREAM:
            stream = stream[-_MAX_STREAM:]
        data["kai_status_stream"] = stream
        data["kai_last_output"] = msg
        if typ == "error":
            data["kai_status"] = "error"
        elif typ == "complete":
            data["kai_status"] = "completed"
        else:
            data["kai_status"] = "busy"
        _write(data)

def task(name: str):
    with _lock:
        data = _read()
        data["kai_current_task"] = name
        _write(data)

def reset_stream():
    with _lock:
        data = _read()
        data["kai_status_stream"] = []
        data["kai_status"] = "running"
        data["kai_current_task"] = None
        _write(data)

def error(msg: str):
    write(msg, "error")

def complete(msg: str):
    write(msg, "complete")

def info(msg: str):
    write(msg, "info")

def tool_call(name: str, params: dict):
    write(f"Tool: {name}({json.dumps(params)[:200]})", "tool_call")

def tool_result(name: str, success: bool, summary: str = ""):
    typ = "tool_result" if success else "error"
    write(f"Tool {name}: {'OK' if success else 'FAILED'} -- {summary[:200]}", typ)

def get_status() -> dict:
    return _read()

def set_supervisor_active(active: bool):
    with _lock:
        data = _read()
        data["supervisor_active"] = active
        _write(data)

def get_supervisor_active() -> bool:
    return _read().get("supervisor_active", False)

def proactive(event_type: str, message: str):
    write(f"[{event_type}] {message}", "proactive")
