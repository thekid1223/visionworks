"""Shell tools — cross-platform command execution."""
from __future__ import annotations
import json, os, platform, subprocess, time
from pathlib import Path

class ShellTools:
    def __init__(self, workspace: Path | None = None):
        self.workspace = workspace or Path.cwd()
        self.is_windows = platform.system() == "Windows"
        self.wsl_distro = "kali-linux"

    def run_command(self, command: str, timeout: int = 30) -> str:
        try:
            r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
            return r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s"
        except Exception as e:
            return f"Command failed: {e}"

    def run_powershell(self, command: str, timeout: int = 30) -> str:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
            return r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return f"PowerShell command timed out after {timeout}s"
        except Exception as e:
            return f"PowerShell failed: {e}"

    def run_wsl(self, command: str, timeout: int = 30, distro: str = "") -> str:
        distro = distro or self.wsl_distro
        if not self.is_windows:
            return self.run_command(command, timeout)
        try:
            r = subprocess.run(["wsl.exe", "-d", distro, "--"] + command.split(), capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
            return r.stdout + r.stderr
        except FileNotFoundError:
            return "WSL not available"
        except subprocess.TimeoutExpired:
            return f"WSL command timed out after {timeout}s"
        except Exception as e:
            return f"WSL failed: {e}"

    def has_wsl(self) -> bool:
        if not self.is_windows:
            return True
        try:
            r = subprocess.run(["wsl.exe", "-d", self.wsl_distro, "--", "echo", "ready"], capture_output=True, text=True, timeout=10)
            return r.returncode == 0 and "ready" in r.stdout
        except Exception:
            return False

    def has_nmap(self) -> bool:
        try:
            r = subprocess.run(["where.exe", "nmap"], capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False
