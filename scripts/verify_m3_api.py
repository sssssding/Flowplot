"""Read actual COMSOL 6.3 models repeatedly; generate unsolved controlled output copies.

Usage: python scripts/verify_m3_api.py --comsol-root "<COMSOL_ROOT>" --write-fixture
All generated Java/classes, models and detailed command logs remain under outputs/m3_api.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {'selection_overlap', 'wall_on_inlet', 'conjugate_normal', 'reversed_inlet', 'invalid_k', 'normal', 'missing_outlet', 'slip_wall', 'empty_heat_flux', 'disabled_coupling', 'high_reynolds', 'conjugate_missing_wall_k', 'missing_inlet', 'invalid_viscosity', 'empty_inlet', 'thermal_overlap'}
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
    output = ROOT / "outputs" / "m3_api" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    models = [ROOT / "models/baseline_pipe_2d_laminar.mph", *sorted((ROOT / "models/cases").glob("*.mph"))]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in models}
    implementations = [ROOT / "src/comsol/ModelInventory.java", ROOT / "src/comsol/M3ApiProbe.java.in", Path(__file__).resolve()]
    implementation_before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in implementations}
    source = (ROOT / "src/comsol/M3ApiProbe.java.in").read_text(encoding="utf-8")
    for key, path in {"BASE": models[0], "CASES": ROOT / "models/cases", "OUTPUT": output}.items():
        source = source.replace(f"@{key}@", path.as_posix())
    inventory_source = (ROOT / "src/comsol/ModelInventory.java").read_text(encoding="utf-8")
    inventory_body = inventory_source[inventory_source.index("public class ModelInventory {") + len("public class ModelInventory {"):-2]
    inventory_body = inventory_body.replace("public static void main(String[] args)", "public static void inspectBaseline(String[] args)")
    probe_imports, probe_body = source.split("public class M3ApiProbe {", 1)
    imports = "\n".join(line for line in inventory_source.splitlines() if line.startswith("import "))
    source = imports + "\npublic class M3ApiProbe {\n" + inventory_body + probe_body.replace("ModelInventory.inspect(model)", "inspect(model)")
    (output / "M3ApiProbe.java").write_text(source, encoding="utf-8")
    bin_dir = args.comsol_root / "bin/win64"
    run([str(bin_dir / "comsolcompile.exe"), "M3ApiProbe.java"], output, "compile", args.timeout)
    for name in ("M3ApiProbe",):
        if not (output / f"{name}.class").is_file():
            raise RuntimeError(f"Missing compiled class: {name}")
    text = run([str(bin_dir / "comsolbatch.exe"), "-inputfile", "M3ApiProbe.class", "-nosave", "-batchlog", "batch.log", "-batchlogout", "-np", "2"], output, "batch", args.timeout)
    if "M3_API_VERIFIED" not in text or "M3_LICENSE_BASELINE true" not in text:
        raise RuntimeError(f"Missing completion marker; inspect {output}")
    inventories = {}
    for line in text.splitlines():
        if line.startswith("M3_INVENTORY "):
            _, name, inventory = line.split(" ", 2)
            if name in inventories:
                raise RuntimeError(f"Duplicate sample inventory: {name}")
            inventories[name] = json.loads(inventory)
            (output / f"{name}.inventory.json").write_text(json.dumps(inventories[name], ensure_ascii=False, indent=2), encoding="utf-8")
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in models}
    if before != after:
        raise RuntimeError("Original models changed")
    implementation_after = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in implementations}
    if implementation_before != implementation_after:
        raise RuntimeError("Implementation changed during verification; rerun against stable source")
    if set(inventories) != SAMPLES:
        raise RuntimeError("Unexpected or missing verified sample inventory")
    for name in SAMPLES:
        for marker in (f"M3_READ_VERIFIED {name} 3", f"M3_UNSOLVED_VERIFIED {name} 3"):
            if marker not in text:
                raise RuntimeError(f"Missing genuine verification marker: {marker}")
    def heat(name):
        return next(p for p in inventories[name]["components"][0]["physics"] if p["tag"] == "ht")
    normal = inventories["normal"]["components"][0]["geometries"][0]
    evidence = normal["three_dimensional_evidence"]
    assert normal["dimension"] == 3 and evidence["read_status"] == "read"
    assert normal["domain_count"] == 1
    conjugate = inventories["conjugate_normal"]["components"][0]
    assert conjugate["geometries"][0]["domain_count"] == 2
    assert conjugate["geometries"][0]["three_dimensional_evidence"]["read_status"] == "read"
    def features(name):
        return {f["tag"]: f for f in heat(name)["features"]}
    summary = {
        "schema_version": "m3-api-evidence-1", "verified_at": datetime.now().isoformat(timespec="seconds"),
        "comsol_version": inventories["normal"]["comsol_version"], "license_baseline_available": True,
        "solved": False, "solution_sequences_per_model": 0, "source_models_unchanged": True,
        "source_model_sha256": before, "reads_per_model": 3, "verified_models": sorted(inventories),
        "implementation_sha256": implementation_before, "implementation_sha256_after": implementation_after,
        "inventory_sha256": {name: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest() for name, value in inventories.items()},
        "output_model_sha256": {name: hashlib.sha256((output / f"{name}.mph").read_bytes()).hexdigest() for name in inventories},
        "repeat_markers": {name: f"M3_READ_VERIFIED {name} 3" for name in inventories},
        "unsolved_markers": {name: f"M3_UNSOLVED_VERIFIED {name} 3" for name in inventories},
        "generated_driver_sha256": hashlib.sha256((output / "M3ApiProbe.java").read_bytes()).hexdigest(),
        "geometry_api_evidence": evidence,
        "observed_boundary_types": {name: features("normal")[name]["type"] for name in ("temp1", "flux1")},
        "scope": "Controlled unsolved 3D heated fluid pipe and fluid/solid wall API evidence; development samples, not independent accuracy evaluation",
        "limitations": ["No mesh or solver was run; repeated static reads do not establish physical correctness or convergence.", "Controlled z-axis circular cylinders and concentric wall only; geometry roles require topology, sampled curvature/normals and API-measured area/volume checks; native curved measurements differ from analytic values by approximately 0.51%, so the adapter permits 1% measure error while shape checks use 1e-7 relative tolerance.", "Surface parameter grids may include points outside trimmed faces; API-measured entity measures and edge evidence are retained for conservative validation."]
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.write_fixture:
        (ROOT / "data/fixtures/m3_api_evidence.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (ROOT / "data/fixtures/m3_inventories.json").write_text(json.dumps(inventories, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "verified_models": sorted(inventories)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
