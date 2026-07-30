"""Debug launcher for Kai Prime tray app — catches errors and pauses."""
import sys, traceback
sys.path.insert(0, r"C:\Users\7nujy6xc\OneDrive\Desktop\Kai-AI")

try:
    from kai_prime.tray_app import TrayApp
    app = TrayApp()
    app.run()
except Exception:
    with open(r"C:\Users\7nujy6xc\Desktop\kai_error.log", "w") as f:
        traceback.print_exc(file=f)
    traceback.print_exc()
    input("\n\nPress Enter to exit...")
