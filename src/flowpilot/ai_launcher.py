"""Dependency check before opening the opt-in recommendation desktop."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.preflight import ROOT, check_environment


def launch(arguments=None):
    failed = [item["name"] for item in check_environment()
              if item["name"] != "comsol" and item["status"] == "error"]
    if failed:
        print("FlowPlot AI unavailable dependencies: " + ", ".join(failed), file=sys.stderr)
        print("Install requirements-dev.txt in this environment, or set FLOWPILOT_PYTHON to a prepared Python.", file=sys.stderr)
        return 1
    try:
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/recommend_ui.py"),
                               *(sys.argv[1:] if arguments is None else arguments)], cwd=ROOT, check=False).returncode
    except OSError:
        print("FlowPlot AI could not start its desktop process.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(launch())
