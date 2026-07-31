"""Kai Prime Web Server — Flask + SSE."""
from __future__ import annotations
import json, logging, os, sys, time, threading, traceback
from pathlib import Path
from flask import Flask, render_template, request, Response, jsonify, redirect, send_from_directory

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from kai_prime.config import SERVER_HOST, SERVER_PORT, WORKSPACE
from kai_prime.brain.core import KaiBrain
from kai_prime.session import SessionState
from kai_prime import stream

log = logging.getLogger("kai_prime.server")

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"))

brain: KaiBrain | None = None
session: SessionState | None = None
_computer = None
_ctos = None
_init_lock = threading.Lock()
_computer_lock = threading.Lock()
_db_sync_started = False

def _get_computer():
    global _computer
    with _computer_lock:
        if _computer is None:
            from kai_prime.agents.computer import ComputerAgent
            _computer = ComputerAgent(WORKSPACE)
        return _computer

def _init():
    global brain, session, _db_sync_started
    with _init_lock:
        if brain is None:
            brain = KaiBrain(WORKSPACE)
            log.info("Brain initialized with %d tools", len(brain._tools))
        if session is None:
            session = SessionState()
            session.mark_start()
        if not _db_sync_started:
            try:
                from kai_prime import db_sync
                db_sync.start_background()
                _db_sync_started = True
            except Exception as e:
                log.warning("DB sync not started: %s", e)

def _init_with(brain_obj: KaiBrain, session_obj: SessionState):
    global brain, session
    with _init_lock:
        brain = brain_obj
        session = session_obj

@app.route("/")
def index():
    return redirect("/business")

@app.route("/api/ask", methods=["POST"])
def api_ask():
    _init()
    t0 = time.time()
    data = request.json or {}
    user_input = data.get("message", "").strip()
    if not user_input:
        return jsonify({"error": "No message"}), 400
    stream.reset_stream()
    stream.info(f"User: {user_input[:100]}")
    try:
        response = brain.ask(user_input)
        t1 = time.time()
        session.update_context(user_input, response, "chat")
        state = brain.get_state()
        t2 = time.time()
        result = jsonify({"response": response, "state": state})
        t3 = time.time()
        log.info("ask timings: brain=%.3fs session=%.3fs jsonify=%.3fs total=%.3fs input=%s", t1-t0, t2-t1, t3-t2, t3-t0, user_input[:30])
        return result
    except Exception as e:
        stream.error(str(e)[:200])
        return jsonify({"error": str(e)}), 500

@app.route("/api/stream")
def api_stream():
    def generate():
        last_idx = 0
        start = time.time()
        while time.time() - start < 15:
            status = stream.get_status()
            entries = status.get("kai_status_stream", [])
            if len(entries) > last_idx:
                for entry in entries[last_idx:]:
                    yield f"data: {json.dumps(entry)}\n\n"
                last_idx = len(entries)
            yield f": keepalive\n\n"
            time.sleep(1)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/state")
def api_state():
    _init()
    return jsonify(brain.get_state())

@app.route("/api/session")
def api_session():
    _init()
    prev = session.get_previous_session() if session else {}
    return jsonify({"previous_session": prev, "is_restore": session.is_restore() if session else False})

@app.route("/api/desktop/screenshot", methods=["POST"])
def api_screenshot():
    computer = _get_computer()
    return jsonify({"result": computer.screenshot()})

@app.route("/api/desktop/click", methods=["POST"])
def api_click():
    data = request.json or {}
    computer = _get_computer()
    return jsonify({"result": computer.desktop.click(data.get("x", 0), data.get("y", 0))})

@app.route("/api/desktop/type", methods=["POST"])
def api_type():
    data = request.json or {}
    computer = _get_computer()
    return jsonify({"result": computer.desktop.type_text(data.get("text", ""))})

@app.route("/api/desktop/hotkey", methods=["POST"])
def api_hotkey():
    data = request.json or {}
    computer = _get_computer()
    return jsonify({"result": computer.desktop.hotkey(*data.get("keys", []))})

@app.route("/api/system/info")
def api_system_info():
    computer = _get_computer()
    return jsonify({"result": computer.get_system_info()})

@app.route("/api/system/processes")
def api_processes():
    computer = _get_computer()
    return jsonify({"result": computer.list_processes()})

@app.route("/api/voice/speak", methods=["POST"])
def api_speak():
    data = request.json or {}
    computer = _get_computer()
    return jsonify({"result": computer.speak(data.get("text", ""))})

@app.route("/api/tools/list")
def api_tools_list():
    _init()
    return jsonify({"tools": brain._tool_descriptions})

@app.route("/api/tools/run", methods=["POST"])
def api_tools_run():
    data = request.json or {}
    tool_name = data.get("tool", "")
    args = data.get("args", {})
    _init()
    if tool_name not in brain._tools:
        return jsonify({"error": f"Unknown tool: {tool_name}"}), 400
    try:
        result = brain._tools[tool_name](**args)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/network/scan", methods=["POST"])
def api_net_scan():
    _init()
    global _ctos
    try:
        from kai_prime.tools.ctos import CTOSEngine
        if _ctos is None:
            _ctos = CTOSEngine(WORKSPACE)
        _ctos.start_scan()
        return jsonify({"status": "scan started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/network/status")
def api_net_status():
    global _ctos
    try:
        from kai_prime.tools.ctos import CTOSEngine
        if _ctos is None:
            _ctos = CTOSEngine(WORKSPACE)
        return jsonify(_ctos.get_scan_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/network/devices")
def api_net_devices():
    global _ctos
    try:
        from kai_prime.tools.ctos import CTOSEngine
        if _ctos is None:
            _ctos = CTOSEngine(WORKSPACE)
        return jsonify({"devices": _ctos.all_devices()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/supervisor/status")
def api_supervisor_status():
    _init()
    if brain._supervisor:
        return jsonify(brain._supervisor.get_summary())
    return jsonify({"active": False, "error": "Supervisor not loaded"})

@app.route("/api/supervisor/toggle", methods=["POST"])
def api_supervisor_toggle():
    _init()
    if brain._supervisor:
        new_state = brain._supervisor.toggle()
        return jsonify({"active": new_state})
    return jsonify({"error": "Supervisor not loaded"}), 500

@app.route("/api/bridge")
def api_bridge():
    return jsonify(stream.get_status())

@app.route("/api/health")
def api_health():
    import psutil
    _init()
    prev = session.get_previous_session() if session else {}
    state = brain.get_state() if brain else {}
    return jsonify({
        "status": "ok",
        "uptime": time.time() - (session._state.get("last_start", time.time()) if session else time.time()),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_mb": round(psutil.Process().memory_info().rss / 1024 / 1024, 1),
        "tools": len(state.get("tools_registered", [])),
        "session_count": session._state.get("session_count", 0) if session else 0,
        "crash_count": session._state.get("crash_count", 0) if session else 0,
        "was_crash_recovery": session.is_restore() if session else False,
        "previous_session": prev,
    })

@app.route("/api/watcher/events")
def api_watcher_events():
    try:
        from kai_prime.agents.watcher import Watcher
        if hasattr(app, '_watcher') and app._watcher:
            return jsonify({"events": app._watcher.recent_events()})
    except Exception:
        pass
    return jsonify({"events": []})

@app.route("/api/watcher/status")
def api_watcher_status():
    try:
        from kai_prime.agents.watcher import Watcher
        if hasattr(app, '_watcher') and app._watcher:
            return jsonify({"active": app._watcher._running, "event_count": len(app._watcher._events)})
    except Exception:
        pass
    return jsonify({"active": False, "event_count": 0})

@app.route("/api/security/scan", methods=["POST"])
def api_sec_scan():
    data = request.json or {}
    path = data.get("path", "")
    _init()
    try:
        from kai_prime.tools.security_engine import SecurityEngine
        se = SecurityEngine(WORKSPACE)
        results = []
        from pathlib import Path as _P
        target = _P(path)
        if target.is_file():
            results = se.scan_file(str(target))
        elif target.is_dir():
            results = se.scan_project(str(target))
        else:
            return jsonify({"error": f"Path not found: {path}"}), 400
        return jsonify({"findings": results, "count": len(results)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/life/reminders")
def api_reminders():
    _init()
    try:
        from kai_prime.tools.life_manager import Reminders
        r = Reminders(WORKSPACE)
        return jsonify({"reminders": r.list_pending(), "total": r.status()["total"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/life/reminders/add", methods=["POST"])
def api_add_reminder():
    data = request.json or {}
    text = data.get("text", "")
    time_str = data.get("time_str", "")
    if not text:
        return jsonify({"error": "No text"}), 400
    _init()
    try:
        from kai_prime.tools.life_manager import Reminders
        r = Reminders(WORKSPACE)
        reminder = r.add(text, time_str)
        return jsonify({"result": reminder})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/life/tasks")
def api_tasks():
    _init()
    try:
        from kai_prime.tools.life_manager import Tasks
        t = Tasks(WORKSPACE)
        return jsonify({"tasks": t.list_pending(), "total": t.status()["total"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/life/tasks/add", methods=["POST"])
def api_add_task():
    data = request.json or {}
    title = data.get("title", "")
    priority = data.get("priority", "medium")
    if not title:
        return jsonify({"error": "No title"}), 400
    _init()
    try:
        from kai_prime.tools.life_manager import Tasks
        t = Tasks(WORKSPACE)
        task = t.add(title, priority)
        return jsonify({"result": task})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/notify", methods=["POST"])
def api_notify():
    data = request.json or {}
    title = data.get("title", "Kai Prime")
    message = data.get("message", "")
    urgent = data.get("urgent", False)
    if not message:
        return jsonify({"error": "No message"}), 400
    try:
        from kai_prime.tools.notifier import notify
        notify(title, message, urgent=urgent)
        return jsonify({"result": "Notification sent"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chess/watch", methods=["POST"])
def api_chess_watch():
    data = request.json or {}
    action = data.get("action", "start")
    try:
        from kai_prime.tools.chess_watcher import get_watcher
        watcher = get_watcher(brain=brain if brain else None)
        if action == "start":
            result = watcher.start()
        elif action == "stop":
            result = watcher.stop()
        else:
            result = f"Watching: {'YES' if watcher.is_watching else 'NO'}"
        return jsonify({"result": result, "watching": watcher.is_watching})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chess/status")
def api_chess_status():
    try:
        from kai_prime.tools.chess_watcher import get_watcher
        watcher = get_watcher()
        return jsonify({
            "watching": watcher.is_watching,
            "last_advice": watcher._last_advice or "none",
            "moves_seen": watcher._last_move_count,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/confidence/score", methods=["POST"])
def api_confidence_score():
    data = request.get_json(force=True, silent=True) or {}
    reply = data.get("reply", "")
    user_input = data.get("user_input", "")
    if brain and hasattr(brain, '_confidence'):
        score = brain._confidence.score(reply, user_input)
        return jsonify({"score": round(score, 3), "confident": score >= 0.5})
    return jsonify({"error": "Confidence scorer not available"}), 500


@app.route("/api/confidence/diagnose", methods=["POST"])
def api_confidence_diagnose():
    data = request.get_json(force=True, silent=True) or {}
    reply = data.get("reply", "")
    user_input = data.get("user_input", "")
    if brain and hasattr(brain, '_confidence'):
        issues = brain._confidence.diagnose(reply, user_input)
        return jsonify({"issues": issues, "ok": len(issues) == 0})
    return jsonify({"error": "Confidence scorer not available"}), 500


@app.route("/api/outcome/summary")
def api_outcome_summary():
    if brain and hasattr(brain, '_outcome_ledger'):
        return jsonify(brain._outcome_ledger.summary())
    return jsonify({"error": "Outcome ledger not available"}), 500


@app.route("/api/outcome/tool-rate/<tool_name>")
def api_outcome_tool_rate(tool_name):
    if brain and hasattr(brain, '_outcome_ledger'):
        rate = brain._outcome_ledger.tool_success_rate(tool_name)
        return jsonify({"tool": tool_name, "rate": round(rate, 3)})
    return jsonify({"error": "Outcome ledger not available"}), 500


@app.route("/api/outcome/trending-down")
def api_outcome_trending():
    if brain and hasattr(brain, '_outcome_ledger'):
        return jsonify({"trending_down": brain._outcome_ledger.trending_down()})
    return jsonify({"error": "Outcome ledger not available"}), 500


@app.route("/api/learning/skills")
def api_learning_skills():
    if brain and hasattr(brain, '_learning'):
        category = request.args.get("category", None)
        skills = brain._learning.list_skills(category)
        return jsonify({"skills": [{"name": s.name, "category": s.category, "confidence": s.confidence, "uses": s.usage_count} for s in skills]})
    return jsonify({"error": "Learning system not available"}), 500


@app.route("/api/learning/add", methods=["POST"])
def api_learning_add():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    desc = data.get("description", "")
    cat = data.get("category", "general")
    steps = [s.strip() for s in data.get("steps", "").split(",") if s.strip()] if data.get("steps") else []
    if brain and hasattr(brain, '_learning'):
        skill = brain._learning.create_skill(name, desc, cat, steps)
        return jsonify({"ok": True, "skill": skill.name, "confidence": skill.confidence})
    return jsonify({"error": "Learning system not available"}), 500



@app.route("/api/image/edit", methods=["POST"])
def api_image_edit():
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")
    path = data.get("path", "")
    if brain and hasattr(brain, '_image_editor'):
        editor = brain._image_editor
        if action == "resize":
            result = editor.resize(path, data.get("width", 0), data.get("height", 0))
        elif action == "crop":
            result = editor.crop(path, data.get("x", 0), data.get("y", 0), data.get("w", 100), data.get("h", 100))
        elif action == "rotate":
            result = editor.rotate(path, data.get("degrees", 0))
        elif action == "filter":
            result = editor.apply_filter(path, data.get("filter", "grayscale"))
        elif action == "adjust":
            result = editor.adjust(path, data.get("brightness", 1.0), data.get("contrast", 1.0))
        else:
            return jsonify({"error": f"Unknown action: {action}"}), 400
        return jsonify(result)
    return jsonify({"error": "Image editor not available"}), 500


@app.route("/api/image/info", methods=["POST"])
def api_image_info():
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path", "")
    if brain and hasattr(brain, '_image_editor'):
        info = brain._image_editor.info(path)
        return jsonify(info)
    return jsonify({"error": "Image editor not available"}), 500


# ── Phase 2 Routes ─────────────────────────────────────────────────────────

@app.route("/api/watchguard/status")
def api_watchguard_status():
    if brain and hasattr(brain, '_watchguard'):
        return jsonify(brain._watchguard.status())
    return jsonify({"error": "Watchguard not available"}), 500


@app.route("/api/ports/devices")
def api_ports_devices():
    if brain and hasattr(brain, '_port_whisperer'):
        dtype = request.args.get("type", "")
        devices = brain._port_whisperer.get_by_type(dtype) if dtype else brain._port_whisperer.get_devices()
        return jsonify({"devices": devices})
    return jsonify({"error": "Port Whisperer not available"}), 500


@app.route("/api/ports/status")
def api_ports_status():
    if brain and hasattr(brain, '_port_whisperer'):
        return jsonify(brain._port_whisperer.status())
    return jsonify({"error": "Port Whisperer not available"}), 500


@app.route("/api/traffic/live")
def api_traffic_live():
    if brain and hasattr(brain, '_traffic_eye'):
        return jsonify({"connections": brain._traffic_eye.get_live()})
    return jsonify({"error": "Traffic Eye not available"}), 500


@app.route("/api/traffic/stats")
def api_traffic_stats():
    if brain and hasattr(brain, '_traffic_eye'):
        return jsonify(brain._traffic_eye.get_stats())
    return jsonify({"error": "Traffic Eye not available"}), 500


@app.route("/api/rituals/list")
def api_rituals_list():
    if brain and hasattr(brain, '_rituals'):
        return jsonify({"rituals": brain._rituals.list_rituals()})
    return jsonify({"error": "Ritual engine not available"}), 500


@app.route("/api/rituals/create", methods=["POST"])
def api_rituals_create():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    steps = data.get("steps", [])
    if brain and hasattr(brain, '_rituals'):
        result = brain._rituals.create_ritual(name, steps)
        return jsonify({"ok": True, "message": result})
    return jsonify({"error": "Ritual engine not available"}), 500


@app.route("/api/rituals/run", methods=["POST"])
def api_rituals_run():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    if brain and hasattr(brain, '_rituals'):
        result = brain._rituals.run_ritual(name)
        return jsonify({"ok": True, "result": result})
    return jsonify({"error": "Ritual engine not available"}), 500


@app.route("/api/rituals/delete", methods=["POST"])
def api_rituals_delete():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    if brain and hasattr(brain, '_rituals'):
        result = brain._rituals.delete_ritual(name)
        return jsonify({"ok": True, "message": result})
    return jsonify({"error": "Ritual engine not available"}), 500


@app.route("/api/twin/status")
def api_twin_status():
    if brain and hasattr(brain, '_digital_twin'):
        return jsonify(brain._digital_twin.status())
    return jsonify({"error": "Digital Twin not available"}), 500


@app.route("/api/twin/check", methods=["POST"])
def api_twin_check():
    if brain and hasattr(brain, '_digital_twin'):
        return jsonify(brain._digital_twin.run_check())
    return jsonify({"error": "Digital Twin not available"}), 500


@app.route("/api/clipboard/current")
def api_clipboard_current():
    if brain and hasattr(brain, '_clipboard'):
        text = brain._clipboard.get_current()
        return jsonify({"text": text, "char_count": len(text)})
    return jsonify({"error": "Clipboard monitor not available"}), 500


@app.route("/api/clipboard/history")
def api_clipboard_history():
    count = request.args.get("count", 10, type=int)
    if brain and hasattr(brain, '_clipboard'):
        return jsonify({"history": brain._clipboard.get_history(count)})
    return jsonify({"error": "Clipboard monitor not available"}), 500


@app.route("/api/files/search")
def api_files_search():
    q = request.args.get("q", "")
    if brain and hasattr(brain, '_file_search'):
        return jsonify({"results": brain._file_search.search(q)})
    return jsonify({"error": "File search not available"}), 500


@app.route("/api/files/recent")
def api_files_recent():
    count = request.args.get("count", 15, type=int)
    if brain and hasattr(brain, '_file_search'):
        return jsonify({"files": brain._file_search.recent(count)})
    return jsonify({"error": "File search not available"}), 500


@app.route("/api/files/ext/<ext>")
def api_files_ext(ext):
    if brain and hasattr(brain, '_file_search'):
        return jsonify({"files": brain._file_search.search_ext(ext)})
    return jsonify({"error": "File search not available"}), 500


@app.route("/api/files/status")
def api_files_status():
    if brain and hasattr(brain, '_file_search'):
        return jsonify(brain._file_search.status())
    return jsonify({"error": "File search not available"}), 500


@app.route("/api/capture/screen", methods=["POST"])
def api_capture_screen():
    data = request.get_json(force=True, silent=True) or {}
    question = data.get("question", "")
    if brain and hasattr(brain, '_quick_capture'):
        return jsonify(brain._quick_capture.grab_screen(question))
    return jsonify({"error": "Quick capture not available"}), 500


@app.route("/api/capture/clipboard")
def api_capture_clipboard():
    if brain and hasattr(brain, '_quick_capture'):
        return jsonify(brain._quick_capture.grab_clipboard())
    return jsonify({"error": "Quick capture not available"}), 500


@app.route("/api/capture/both", methods=["POST"])
def api_capture_both():
    data = request.get_json(force=True, silent=True) or {}
    question = data.get("question", "")
    if brain and hasattr(brain, '_quick_capture'):
        return jsonify(brain._quick_capture.grab_both(question))
    return jsonify({"error": "Quick capture not available"}), 500


@app.route("/api/schedule/list")
def api_schedule_list():
    if brain and hasattr(brain, '_scheduler'):
        return jsonify({"tasks": brain._scheduler.list_tasks()})
    return jsonify({"error": "Scheduler not available"}), 500


@app.route("/api/schedule/add", methods=["POST"])
def api_schedule_add():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    command = data.get("command", "")
    interval = data.get("interval_seconds", 3600)
    desc = data.get("description", "")
    if brain and hasattr(brain, '_scheduler'):
        task = brain._scheduler.add_task(name, command, interval, description=desc)
        return jsonify({"ok": True, "task": task})
    return jsonify({"error": "Scheduler not available"}), 500


@app.route("/api/schedule/remove", methods=["POST"])
def api_schedule_remove():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    if brain and hasattr(brain, '_scheduler'):
        ok = brain._scheduler.remove_task(name)
        return jsonify({"ok": ok})
    return jsonify({"error": "Scheduler not available"}), 500


@app.route("/api/schedule/toggle", methods=["POST"])
def api_schedule_toggle():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    enabled = data.get("enabled", True)
    if brain and hasattr(brain, '_scheduler'):
        ok = brain._scheduler.toggle_task(name, enabled)
        return jsonify({"ok": ok})
    return jsonify({"error": "Scheduler not available"}), 500


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    import os, signal
    threading.Thread(target=lambda: os._exit(0), daemon=True).start()
    return jsonify({"result": "Shutting down"})


@app.route("/api/status")
def api_status():
    tcount = len(brain._tools) if brain else 0
    return jsonify({
        "tools": tcount,
        "ready": brain is not None
    })


@app.route("/api/system/daemons")
def api_system_daemons():
    if not brain:
        return jsonify({"daemons": {}})
    import psutil
    daemons = brain.get_daemon_statuses()
    # Watcher is on app, not on brain
    try:
        watcher = getattr(app, '_watcher', None)
        if watcher:
            daemons["watcher"] = {"running": getattr(watcher, '_running', False), "events": len(getattr(watcher, '_events', []))}
        else:
            daemons["watcher"] = {"running": False, "events": 0}
    except Exception:
        daemons["watcher"] = {"running": False, "events": 0}
    daemons["cpu_percent"] = psutil.cpu_percent(interval=0.1)
    daemons["memory_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
    daemons["tools"] = len(brain._tools)
    daemons["uptime"] = round(time.time() - session._state.get("last_start", time.time()), 1) if session else 0
    return jsonify(daemons)


# ── Business Management Routes ──

_business = None
EXPENSE_CATEGORIES = [
    "Materials", "Subcontractor", "Equipment Rental", "Permits & Fees",
    "Fuel", "Transportation", "Insurance", "Office & Admin",
    "Utilities", "Marketing", "Maintenance", "Other",
]

def _get_biz():
    global _business
    if _business is None:
        from kai_prime.tools.business import get_business
        _business = get_business()
    return _business

@app.route("/business")
def business_dashboard():
    b = _get_biz()
    d = b.dashboard()
    return render_template("business/dashboard.html", data=d)

@app.route("/business/clients")
def business_clients():
    b = _get_biz()
    clients = b.get_clients()
    return render_template("business/clients.html", clients=clients)

@app.route("/business/clients/add", methods=["GET", "POST"])
def business_client_add():
    if request.method == "POST":
        b = _get_biz()
        b.add_client(request.form["name"], request.form.get("phone",""), request.form.get("email",""), request.form.get("address",""))
        return _redirect("/business/clients")
    return render_template("business/client_form.html")

@app.route("/business/clients/<int:cid>/delete", methods=["POST"])
def business_client_delete(cid):
    _get_biz().delete_client(cid)
    return _redirect("/business/clients")

@app.route("/business/clients/<int:cid>/edit", methods=["GET", "POST"])
def business_client_edit(cid):
    b = _get_biz()
    c = b.get_client(cid)
    if not c:
        return ("Not found", 404)
    if request.method == "POST":
        b.update_client(cid, request.form["name"], request.form.get("phone",""), request.form.get("email",""), request.form.get("address",""))
        return _redirect("/business/clients")
    return render_template("business/client_form.html", client=c)

@app.route("/business/quotes")
def business_quotes():
    b = _get_biz()
    quotes = b.get_quotes()
    return render_template("business/quotes.html", quotes=quotes)

@app.route("/business/quotes/new", methods=["GET", "POST"])
def business_quote_new():
    b = _get_biz()
    if request.method == "POST":
        client_id = int(request.form["client_id"])
        items = []
        descs = request.form.getlist("desc[]")
        qtys = request.form.getlist("qty[]")
        rates = request.form.getlist("rate[]")
        units = request.form.getlist("unit[]")
        types = request.form.getlist("type[]")
        for i, d in enumerate(descs):
            qty = float(qtys[i]) if i < len(qtys) and qtys[i] else 0
            rate = float(rates[i]) if i < len(rates) and rates[i] else 0
            if d and qty > 0:
                items.append({
                    "desc": d, "qty": qty, "rate": rate,
                    "unit": units[i] if i < len(units) else "hour",
                    "type": types[i] if i < len(types) else "Labor",
                    "total": round(qty * rate, 2)
                })
        tax_rate = float(request.form.get("tax_rate", 0))
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        new_id = b.create_quote(client_id, items=items, notes=request.form.get("notes",""), tax_rate=tax_rate)
        if phone or email:
            b.update_client_contact(client_id, phone, email)
        return _redirect(f"/business/quotes/{new_id}")
    clients = b.get_clients()
    rates = b.get_local_rates()
    return render_template("business/quote_form.html", clients=clients, rates=rates)

@app.route("/business/quotes/estimate", methods=["GET", "POST"])
def business_quote_estimate():
    b = _get_biz()
    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        description = request.form.get("description", "")
        tax_rate = float(request.form.get("tax_rate", 0))
        if not client_name:
            return render_template("business/quote_estimate.html", clients=b.get_clients(),
                                  error="Please enter a client name", description=description)
        items, error = b.generate_estimate(description)
        if error:
            return render_template("business/quote_estimate.html", clients=b.get_clients(),
                                  error=error, description=description)
        return render_template("business/quote_review.html", items=items, client_name=client_name,
                              description=description, tax_rate=tax_rate)
    return render_template("business/quote_estimate.html", clients=b.get_clients())

@app.route("/business/quotes/save-estimate", methods=["POST"])
def business_quote_save_estimate():
    b = _get_biz()
    client_name = request.form.get("client_name", "").strip()
    if not client_name:
        return _redirect("/business/quotes/estimate")
    clients = b.get_clients(search=client_name)
    if clients:
        client_id = clients[0]["id"]
    else:
        client_id = b.add_client(client_name)
    items = []
    descs = request.form.getlist("desc[]")
    qtys = request.form.getlist("qty[]")
    rates = request.form.getlist("rate[]")
    units = request.form.getlist("unit[]")
    types = request.form.getlist("type[]")
    for i, d in enumerate(descs):
        qty = float(qtys[i]) if i < len(qtys) and qtys[i] else 0
        rate = float(rates[i]) if i < len(rates) and rates[i] else 0
        if d and qty > 0:
            items.append({
                "desc": d, "qty": qty, "rate": rate,
                "unit": units[i] if i < len(units) else "hour",
                "type": types[i] if i < len(types) else "Labor",
                "total": round(qty * rate, 2)
            })
    tax_rate = float(request.form.get("tax_rate", 0))
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    new_id = b.create_quote(client_id, items=items, notes=request.form.get("notes",""), tax_rate=tax_rate)
    if phone or email:
        b.update_client_contact(client_id, phone, email)
    return _redirect(f"/business/quotes/{new_id}")

@app.route("/business/quotes/<int:qid>")
def business_quote_view(qid):
    b = _get_biz()
    q = b.get_quote(qid)
    return render_template("business/quote_view.html", q=q) if q else ("Not found", 404)

@app.route("/business/quotes/<int:qid>/contact", methods=["POST"])
def business_quote_contact(qid):
    b = _get_biz()
    q = b.get_quote(qid)
    if q:
        b.update_client_contact(q["client_id"], request.form.get("phone", "").strip(),
                                request.form.get("email", "").strip())
    return _redirect(f"/business/quotes/{qid}")

@app.route("/business/quotes/<int:qid>/sent", methods=["POST"])
def business_quote_sent(qid):
    _get_biz().update_quote_status(qid, "sent")
    return ("ok", 200)

@app.route("/business/quotes/<int:qid>/invoice", methods=["POST"])
def business_quote_to_invoice(qid):
    b = _get_biz()
    q = b.get_quote(qid)
    if q:
        b.create_invoice(q["client_id"], quote_id=qid, items=q["items"], notes=q["notes"], tax_rate=q.get("tax_rate",0))
    return _redirect("/business/invoices")

@app.route("/business/quotes/<int:qid>/delete", methods=["POST"])
def business_quote_delete(qid):
    _get_biz().delete_quote(qid)
    return _redirect("/business/quotes")

@app.route("/business/invoices")
def business_invoices():
    b = _get_biz()
    invoices = b.get_invoices()
    return render_template("business/invoices.html", invoices=invoices)

@app.route("/business/invoices/new", methods=["GET", "POST"])
def business_invoice_new():
    b = _get_biz()
    if request.method == "POST":
        client_id = int(request.form["client_id"])
        items = []
        descs = request.form.getlist("desc[]")
        qtys = request.form.getlist("qty[]")
        rates = request.form.getlist("rate[]")
        units = request.form.getlist("unit[]")
        types = request.form.getlist("type[]")
        for i, d in enumerate(descs):
            qty = float(qtys[i]) if i < len(qtys) and qtys[i] else 0
            rate = float(rates[i]) if i < len(rates) and rates[i] else 0
            if d and qty > 0:
                items.append({
                    "desc": d, "qty": qty, "rate": rate,
                    "unit": units[i] if i < len(units) else "hour",
                    "type": types[i] if i < len(types) else "Labor",
                    "total": round(qty * rate, 2)
                })
        tax_rate = float(request.form.get("tax_rate", 0))
        b.create_invoice(client_id, items=items, notes=request.form.get("notes",""), tax_rate=tax_rate)
        return _redirect("/business/invoices")
    clients = b.get_clients()
    return render_template("business/invoice_form.html", clients=clients)

@app.route("/business/invoices/<int:iid>")
def business_invoice_view(iid):
    b = _get_biz()
    inv = b.get_invoice(iid)
    return render_template("business/invoice_view.html", inv=inv) if inv else ("Not found", 404)

@app.route("/business/invoices/<int:iid>/pay", methods=["POST"])
def business_invoice_pay(iid):
    b = _get_biz()
    method = request.form.get("method", "")
    b.mark_paid(iid, method)
    return _redirect(f"/business/invoices/{iid}")

@app.route("/business/invoices/<int:iid>/delete", methods=["POST"])
def business_invoice_delete(iid):
    _get_biz().delete_invoice(iid)
    return _redirect("/business/invoices")

@app.route("/business/hours", methods=["GET", "POST"])
def business_hours():
    b = _get_biz()
    if request.method == "POST":
        rate = float(request.form.get("rate", 0))
        b.log_hours(request.form["employee"], request.form["date"], float(request.form["hours"]), request.form.get("description",""), rate=rate)
        return _redirect("/business/hours")
    hours = b.get_hours(days=30)
    summary = b.get_hours_summary(days=30)
    return render_template("business/hours.html", hours=hours, summary=summary)

@app.route("/business/hours/<int:hid>/edit", methods=["GET", "POST"])
def business_hours_edit(hid):
    b = _get_biz()
    h = b.get_single_hours(hid)
    if not h:
        return ("Not found", 404)
    if request.method == "POST":
        b.update_hours(hid, request.form["employee"], request.form.get("date",""), float(request.form["hours"]), request.form.get("rate", 0), request.form.get("description",""))
        return _redirect("/business/hours")
    return render_template("business/hours_form.html", h=h)

@app.route("/business/hours/<int:hid>/delete", methods=["POST"])
def business_hours_delete(hid):
    _get_biz().delete_hours(hid)
    return _redirect("/business/hours")

@app.route("/business/expenses", methods=["GET", "POST"])
def business_expenses():
    b = _get_biz()
    if request.method == "POST":
        b.add_expense(request.form["category"], float(request.form["amount"]), request.form.get("description",""), request.form.get("date",""))
        return _redirect("/business/expenses")
    expenses = b.get_expenses(days=30)
    by_cat = b.get_expenses_by_category(days=30)
    return render_template("business/expenses.html", expenses=expenses, by_cat=by_cat, categories=EXPENSE_CATEGORIES)

@app.route("/business/expenses/<int:eid>/edit", methods=["GET", "POST"])
def business_expense_edit(eid):
    b = _get_biz()
    e = b.get_single_expense(eid)
    if not e:
        return ("Not found", 404)
    if request.method == "POST":
        b.update_expense(eid, request.form["category"], float(request.form["amount"]), request.form.get("description",""), request.form.get("date",""))
        return _redirect("/business/expenses")
    return render_template("business/expenses_form.html", e=e, categories=EXPENSE_CATEGORIES)

@app.route("/business/expenses/<int:eid>/delete", methods=["POST"])
def business_expense_delete(eid):
    _get_biz().delete_expense(eid)
    return _redirect("/business/expenses")

# ── Local Rates Management ──

@app.route("/business/rates", methods=["GET", "POST"])
def business_rates():
    b = _get_biz()
    if request.method == "POST":
        b.add_local_rate(request.form["category"], request.form["item_name"], request.form["unit"], float(request.form["rate"]), request.form.get("description",""))
        return _redirect("/business/rates")
    rates = b.get_local_rates()
    cats = b.get_rate_categories()
    return render_template("business/rates.html", rates=rates, categories=cats)

@app.route("/business/rates/<int:rid>/delete", methods=["POST"])
def business_rate_delete(rid):
    _get_biz().delete_local_rate(rid)
    return _redirect("/business/rates")

@app.route("/business/rates/<int:rid>/edit", methods=["GET", "POST"])
def business_rate_edit(rid):
    b = _get_biz()
    rates = b.get_local_rates()
    rate = next((r for r in rates if r["id"] == rid), None)
    if not rate:
        return ("Not found", 404)
    if request.method == "POST":
        b.update_local_rate(rid, request.form["category"], request.form["item_name"], request.form["unit"], float(request.form["rate"]), request.form.get("description",""))
        return _redirect("/business/rates")
    return render_template("business/rates_form.html", r=rate)

@app.route("/business/export/<table>")
def business_export(table):
    csv_data = _get_biz().export_csv(table)
    if csv_data is None:
        return "Not found", 404
    return Response(csv_data, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={table}.csv"})


# ── Social / Lead Generation ──

@app.route("/business/social", methods=["GET", "POST"])
def business_social():
    b = _get_biz()
    if request.method == "POST":
        b.update_company(
            facebook_url=request.form.get("facebook_url", ""),
            homeadvisor_url=request.form.get("homeadvisor_url", ""),
        )
        return _redirect("/business/social")
    company = b.get_company()
    return render_template("business/social.html", company=company)

@app.route("/business/leads", methods=["GET", "POST"])
def business_leads():
    b = _get_biz()
    if request.method == "POST" and request.form.get("name"):
        b.add_lead(
            name=request.form["name"],
            phone=request.form.get("phone", ""),
            email=request.form.get("email", ""),
            description=request.form.get("description", ""),
            source=request.form.get("source", "Direct"),
        )
        return _redirect("/business/leads")
    status = request.args.get("status", "")
    leads = b.get_leads(status=status)
    return render_template("business/leads.html", leads=leads, current_status=status)

@app.route("/business/leads/<int:lid>/status", methods=["POST"])
def business_lead_status(lid):
    b = _get_biz()
    b.update_lead_status(lid, request.form.get("status", "new"))
    return _redirect("/business/leads")

@app.route("/business/leads/<int:lid>/delete", methods=["POST"])
def business_lead_delete(lid):
    _get_biz().delete_lead(lid)
    return _redirect("/business/leads")

@app.route("/business/leads/<int:lid>/edit", methods=["GET", "POST"])
def business_lead_edit(lid):
    b = _get_biz()
    leads = b.get_leads(days=3650)
    lead = next((x for x in leads if x["id"] == lid), None)
    if not lead:
        return ("Not found", 404)
    if request.method == "POST":
        b.update_lead(lid, request.form["name"], request.form.get("phone",""), request.form.get("email",""), request.form.get("description",""))
        b.update_lead_status(lid, request.form.get("status", "new"))
        return _redirect("/business/leads")
    return render_template("business/leads_form.html", lead=lead)

@app.route("/business/lead-capture")
def business_lead_capture():
    return render_template("business/lead_capture.html")

@app.route("/api/business/lead", methods=["POST"])
def api_business_lead():
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    _get_biz().add_lead(name, data.get("phone",""), data.get("email",""), data.get("description",""), "Lead Capture Page")
    return jsonify({"ok": True})


def _redirect(url):
    try:
        from kai_prime import db_sync
        threading.Thread(target=db_sync.backup, daemon=True).start()
    except Exception:
        pass
    return redirect(url)


def create_app(brain_obj=None, session_obj=None, watcher_obj=None):
    if brain_obj and session_obj:
        _init_with(brain_obj, session_obj)
    else:
        _init()
    if watcher_obj:
        app._watcher = watcher_obj
    return app


def main():
    _init()
    log.info("Kai Prime v2.0 starting on port %d", SERVER_PORT)
    print(f"\n  Kai Prime v2.0")
    print(f"  http://localhost:{SERVER_PORT}")
    try:
        from waitress import serve
        print("  Using waitress WSGI server")
        serve(app, host=SERVER_HOST, port=SERVER_PORT, threads=40)
    except ImportError:
        log.warning("waitress not installed, falling back to Flask dev server")
        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
