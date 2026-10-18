"""Deterministic provenance for the complete diagnostic engine, including contracts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_SOURCES = (
    "src/flowpilot/engine_fingerprint.py",
    "src/flowpilot/diagnostics.py",
    "src/flowpilot/diagnostic_modules/__init__.py",
    "src/flowpilot/diagnostic_modules/flow.py",
    "schema/diagnostic-model.schema.json",
    "schema/diagnosis.schema.json",
)


def fingerprint_from_sources(hashes):
    """Historical freezes used the diagnostics file alone; preserve that identity."""
    if "src/flowpilot/engine_fingerprint.py" not in hashes:
        return hashes["src/flowpilot/diagnostics.py"]
    manifest = {name: hashes[name] for name in ENGINE_SOURCES}
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def engine_fingerprint(root=ROOT):
    hashes = {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest()
              for name in ENGINE_SOURCES}
    return fingerprint_from_sources(hashes)
