#!/usr/bin/env python3
"""Install a user-level macOS LaunchAgent (run manually on the user's Mac)."""
from pathlib import Path
import plistlib
import sys

BASE = Path(__file__).resolve().parent
PYTHON = BASE / ".venv" / "bin" / "python"
LABEL = "local.macreelspublisher"


def main():
    if sys.platform != "darwin":
        raise SystemExit("This installer must run on macOS")
    if not PYTHON.exists():
        raise SystemExit("Run python3 -m venv .venv and pip install -r requirements.txt first")
    logs = BASE / "state"
    logs.mkdir(exist_ok=True)
    destination = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LABEL,
        "ProgramArguments": [str(PYTHON), str(BASE / "publisher.py"), "tick"],
        "WorkingDirectory": str(BASE),
        "StartInterval": 300,
        "RunAtLoad": True,
        "StandardOutPath": str(logs / "scheduler.log"),
        "StandardErrorPath": str(logs / "scheduler_error.log"),
        # launchd has a reduced PATH compared with your Terminal session.
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
    }
    destination.write_bytes(plistlib.dumps(payload))
    print("Created:", destination)
    print("Activate (user session):")
    print("  launchctl bootstrap gui/$(id -u) " + str(destination))
    print("Inspect:")
    print("  launchctl print gui/$(id -u)/" + LABEL)


if __name__ == "__main__":
    main()