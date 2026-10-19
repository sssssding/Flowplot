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
    "src/flowpilot/diagnostic_modules/flow_3d.py",
    "src/flowpilot/diagnostic_modules/flow_scope.py",
    "src/flowpilot/diagnostic_modules/heat.py",
    "src/flowpilot/diagnostic_modules/thermal_coupling.py",
    "schema/diagnostic-model.schema.json",
    "schema/diagnosis.schema.json",
)


def fingerprint_from_sources(hashes):
    """Historical freezes used the diagnostics file alone; preserve that identity."""
    if "src/flowpilot/engine_fingerprint.py" not in hashes:
        return hashes["src/flowpilot/diagnostics.py"]
    # Versioned recorded source sets preserve M0/M1 and M2 identities while
    # requiring every member of whichever generation is present.
    m3 = {"src/flowpilot/diagnostic_modules/flow_3d.py"}
    m2 = {"src/flowpilot/diagnostic_modules/flow_scope.py",
          "src/flowpilot/diagnostic_modules/heat.py", "src/flowpilot/diagnostic_modules/thermal_coupling.py"}
    selected = (ENGINE_SOURCES if m3 & hashes.keys() else
                tuple(name for name in ENGINE_SOURCES if name not in m3) if m2 & hashes.keys() else
                tuple(name for name in ENGINE_SOURCES if name not in m3 | m2))
    manifest = {name: hashes[name] for name in selected}
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def engine_fingerprint(root=ROOT):
    hashes = {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest()
              for name in ENGINE_SOURCES}
    return fingerprint_from_sources(hashes)
