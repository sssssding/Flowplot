"""Dependency-aware desktop launcher; checks never install or open a window."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.preflight import ROOT, check_environment

DESKTOP = ROOT / "src/flowpilot/desktop.py"


def launch(arguments=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--check-env", action="store_true")
    options, remaining = parser.parse_known_args(arguments)
    checks = [item for item in check_environment() if item["name"] != "comsol"]
    failed = [item["name"] for item in checks if item["status"] == "error"]
    if failed:
        print("FlowPlot cannot start: unavailable dependencies: " + ", ".join(failed), file=sys.stderr)
        print(f'Python selected: "{sys.executable}"', file=sys.stderr)
        if "jsonschema" in failed:
            print("Install requirements-dev.txt with this interpreter, or select a prepared environment.", file=sys.stderr)
        if "tkinter" in failed:
            print("Use a Python installation with Tcl/Tk; this launcher does not install software.", file=sys.stderr)
        print("Set FLOWPILOT_PYTHON to a prepared python.exe before running FlowPlot.cmd.", file=sys.stderr)
        return 1
    if options.check_env:
        print("FlowPlot desktop dependencies are importable; no window or COMSOL process started.")
        print("This does not validate visible UI, licenses, models, or physical correctness.")
        for item in checks:
            print(f"{item['name']}: {item['status']} ({item.get('version', 'unknown')})")
        return 0
    try:
        # Use an argument list, not a shell; paths and desktop options remain literal.
        process = subprocess.run([sys.executable, "-X", "utf8", str(DESKTOP), *remaining],
                                 cwd=ROOT, check=False)
        return process.returncode
    except OSError:
        print("FlowPlot could not launch its desktop process. Check the selected Python environment.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(launch())
