"""Read actual COMSOL 6.3 models repeatedly; generate unsolved controlled output copies.

Usage: python scripts/verify_m0_api.py --comsol-root "D:/Program Files/COMSOL/COMSOL63/Multiphysics"
All generated Java/classes, models and detailed command logs remain under outputs/m0_api.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import _run


def run(command: list[str], cwd: Path, label: str, timeout: int) -> str:
    (cwd / f"{label}.command.json").write_text(json.dumps(command, ensure_ascii=False, indent=2), encoding="utf-8")
    log = cwd / f"{label}.stdout.log"
    _run(command, cwd=cwd, log=log, timeout=timeout)
    return log.read_text(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comsol-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--write-fixture", action="store_true", help="Write sanitized verified summary to data/fixtures")
    args = parser.parse_args()
    output = ROOT / "outputs" / "m0_api" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    models = [ROOT / "models/baseline_pipe_2d_laminar.mph", *sorted((ROOT / "models/cases").glob("*.mph"))]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in models}
    source = (ROOT / "src/comsol/M0ApiProbe.java.in").read_text(encoding="utf-8")
    for key, path in {"BASE": models[0], "CASES": ROOT / "models/cases", "OUTPUT": output}.items():
        source = source.replace(f"@{key}@", path.as_posix())
    inventory_source = (ROOT / "src/comsol/ModelInventory.java").read_text(encoding="utf-8")
    inventory_body = inventory_source[inventory_source.index("public class ModelInventory {") + len("public class ModelInventory {"):-2]
    inventory_body = inventory_body.replace("public static void main(String[] args)", "public static void inspectBaseline(String[] args)")
    probe_imports, probe_body = source.split("public class M0ApiProbe {", 1)
    imports = "\n".join(line for line in inventory_source.splitlines() if line.startswith("import "))
    source = imports + "\npublic class M0ApiProbe {\n" + inventory_body + probe_body.replace("ModelInventory.inspect(model)", "inspect(model)")
    (output / "M0ApiProbe.java").write_text(source, encoding="utf-8")
    bin_dir = args.comsol_root / "bin/win64"
    run([str(bin_dir / "comsolcompile.exe"), "M0ApiProbe.java"], output, "compile", args.timeout)
    for name in ("M0ApiProbe",):
        if not (output / f"{name}.class").is_file():
            raise RuntimeError(f"Missing compiled class: {name}")
    text = run([str(bin_dir / "comsolbatch.exe"), "-inputfile", "M0ApiProbe.class", "-nosave", "-batchlog", "batch.log", "-batchlogout", "-np", "2"], output, "batch", args.timeout)
    if "M0_API_VERIFIED" not in text or "M0_LICENSE_BASELINE true" not in text:
        raise RuntimeError(f"Missing genuine completion/license markers; inspect {output}")
    inventories = {}
    for line in text.splitlines():
        if line.startswith("M0_INVENTORY "):
            _, name, inventory = line.split(" ", 2)
            inventories[name] = json.loads(inventory)
    required = {"baseline", "missing_inlet", "missing_outlet", "selection_overlap", "reversed_inlet", "high_reynolds", "unknown_physics", "missing_viscosity"}
    if not required <= inventories.keys():
        raise RuntimeError("Missing required real sample inventories")
    for name, inventory in inventories.items():
        if f"M0_READ_VERIFIED {name} 3" not in text:
            raise RuntimeError(f"Missing repeated read marker: {name}")
        (output / f"{name}.inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in models}
    if before != after:
        raise RuntimeError("Original model changed")
    missing = next(m for m in inventories["missing_viscosity"]["components"][0]["materials"] if m["tag"] == "solid_m0")
    assert missing["dynamic_viscosity"]["status"] == "unresolved"
    assert missing["dynamic_viscosity"]["expression"] == ""
    assert missing["density"]["status"] == "resolved"
    assert any(p["tag"] == "spf" and p["enabled"] for p in inventories["missing_viscosity"]["components"][0]["physics"])
    summary = {
        "schema_version": "m0-api-evidence-1", "comsol_version": inventories["baseline"]["comsol_version"],
        "verified_at": datetime.now().isoformat(timespec="seconds"), "license_baseline_available": True,
        "interface_creation_succeeded": "HeatTransferInFluids", "solved": False, "source_models_unchanged": before == after,
        "reads_per_model": 3, "verified_models": sorted(inventories), "source_model_sha256": before,
        "missing_viscosity": missing["dynamic_viscosity"],
        "coupling_creation_marker": next((line if line.startswith("M0_COUPLING_CREATED ") else "M0_COUPLING_UNAVAILABLE (details retained in local logs)" for line in text.splitlines() if line.startswith(("M0_COUPLING_CREATED ", "M0_COUPLING_UNAVAILABLE "))), "missing"),
        "coupling": inventories.get("unknown_coupling", {}).get("components", [{}])[0].get("multiphysics", []),
        "implementation_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "src/comsol/ModelInventory.java", ROOT / "src/comsol/M0ApiProbe.java.in", ROOT / "scripts/verify_m0_api.py")},
        "inventory_sha256": {name: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest() for name, value in inventories.items()},
        "repeat_markers": {name: f"M0_READ_VERIFIED {name} 3" for name in inventories},
        "generated_driver_sha256": hashlib.sha256((output / "M0ApiProbe.java").read_bytes()).hexdigest(),
        "scope": "M0 evidence extraction and unknown-interface/coupling coverage only; no heat-transfer or coupling diagnostic support claim",
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_fixture:
        (ROOT / "data/fixtures/m0_api_evidence.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "verified_models": sorted(inventories)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
