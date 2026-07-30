"""Kai Prime — main entry point."""
from __future__ import annotations
import sys, os, socket
from pathlib import Path

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if str(_root.parent) not in sys.path:
    sys.path.insert(0, str(_root.parent))

def main():
    import logging
    from kai_prime.config import SERVER_PORT, SERVER_HOST, LOCAL_IP, GATEWAY_IP, WORKSPACE, LLM_PROVIDERS

    print()
    print("  ================================")
    print("       KAI PRIME v2.0")
    print("    Autonomous AI Co-Pilot")
    print("  ================================")
    print()
    print(f"  Local IP:  {LOCAL_IP}")
    print(f"  Gateway:   {GATEWAY_IP or 'detected'}")
    print(f"  Port:      {SERVER_PORT}")
    print()

    key_count = len([p for p in LLM_PROVIDERS if p.get("api_key")])
    print(f"  Providers: {key_count} with API keys")

    try:
        test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test.settimeout(1)
        test.bind((SERVER_HOST, SERVER_PORT))
        test.close()
    except OSError:
        try:
            test6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            test6.settimeout(1)
            test6.bind(('::', SERVER_PORT))
            test6.close()
        except OSError:
            print(f"\n  ERROR: Port {SERVER_PORT} is already in use.")
            print(f"  Is Kai Prime already running? Close it first.")
            print()
            input("  Press Enter to exit...")
            sys.exit(1)

    from kai_prime.web.server import create_app
    from kai_prime.brain.core import KaiBrain
    from kai_prime.session import SessionState

    session = SessionState()
    session.mark_start()
    brain = KaiBrain(WORKSPACE)

    if session.is_restore():
        prev = session.get_previous_session()
        crash_msg = f"Previous session crashed. Last input: {prev.get('last_user_input', '?')}"
        brain.memory.add("system", crash_msg)
        brain.semantic_memory.learn_from_conversation(crash_msg)
        print(f"  Crash recovery: seeded memory with previous session info")

    watcher = None
    try:
        from kai_prime.agents.watcher import Watcher
        def _on_watcher_event(event_type, message):
            try:
                from kai_prime import stream
                stream.proactive(event_type, message)
            except Exception:
                pass
        watcher = Watcher(workspace=WORKSPACE, speak_fn=None)
        watcher.on_event(_on_watcher_event)
        watcher.start()
        print("  Watcher:   active (idle, downloads, clipboard, battery, time)")
    except Exception as e:
        print(f"  Watcher:   failed to start ({e})")

    tools = list(brain._tools.keys())
    print(f"  Tools:     {len(tools)} registered")
    print()

    app = create_app(brain_obj=brain, session_obj=session, watcher_obj=watcher)
    print(f"  Dashboard: http://localhost:{SERVER_PORT}")
    print()
    print("  Ready.")
    print()
    print()

    import atexit
    atexit.register(session.mark_shutdown)
    if hasattr(brain, '_learning'):
        atexit.register(brain._learning.improve_skills)
    if watcher:
        atexit.register(watcher.stop)

    try:
        from waitress import create_server
        import socket as _socket, threading as _threading
        print("  Using waitress WSGI server")
        server = create_server(app, host=SERVER_HOST, port=SERVER_PORT, threads=40)
        try:
            server6 = create_server(app, host='::1', port=SERVER_PORT, threads=10)
            t6 = _threading.Thread(target=server6.run, daemon=True)
            t6.start()
            print(f"  IPv6 listener: ::1:{SERVER_PORT}")
        except Exception:
            pass
        print(f"  IPv4 listener: {SERVER_HOST}:{SERVER_PORT}")
        server.run()
    except ImportError:
        print("  WARNING: waitress not installed, using Flask dev server")
        app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)

if __name__ == "__main__":
    main()
