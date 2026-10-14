"""Preserve historical evidence: only reverse the explicit display-name migration.

This verifies the old byte fingerprint, NOT a current-version visual review.
Any other source change still fails and requires fresh evidence/review.
"""
import hashlib

BRANDING_ONLY_SOURCES = frozenset({
    "src/flowpilot/desktop.py", "src/flowpilot/history_window.py",
    "src/flowpilot/check_model.py", "src/flowpilot/compare_reports.py",
    "src/flowpilot/report_package.py", "src/flowpilot/launcher.py",
})


def historical_digest(name, raw):
    if name in BRANDING_ONLY_SOURCES:
        raw = raw.replace(b"FlowPlot", b"FlowPilot")
    return hashlib.sha256(raw).hexdigest()
