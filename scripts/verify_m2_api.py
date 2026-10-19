"""Read actual COMSOL 6.3 models repeatedly; generate unsolved controlled output copies.

Usage: python scripts/verify_m2_api.py --comsol-root "<COMSOL_ROOT>" --write-fixture
All generated Java/classes, models and detailed command logs remain under outputs/m2_api.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {"normal","invalid_k","invalid_cp","invalid_rho","missing_k","empty_heat_flux","thermal_overlap","disabled_coupling","disabled_heat_interface","inactive_heat_study","legal_manual_velocity","legal_prescribed_velocity","legal_convective_flux","temperature_dependent_k","anisotropic_k","conjugate_normal","conjugate_missing_wall_k"}
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
    output = ROOT / "outputs" / "m2_api" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    models = [ROOT / "models/baseline_pipe_2d_laminar.mph", *sorted((ROOT / "models/cases").glob("*.mph"))]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in models}
    implementations = [ROOT / "src/comsol/ModelInventory.java", ROOT / "src/comsol/M2ApiProbe.java.in", Path(__file__).resolve()]
    implementation_before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in implementations}
    source = (ROOT / "src/comsol/M2ApiProbe.java.in").read_text(encoding="utf-8")
    for key, path in {"BASE": models[0], "CASES": ROOT / "models/cases", "OUTPUT": output}.items():
        source = source.replace(f"@{key}@", path.as_posix())
    inventory_source = (ROOT / "src/comsol/ModelInventory.java").read_text(encoding="utf-8")
    inventory_body = inventory_source[inventory_source.index("public class ModelInventory {") + len("public class ModelInventory {"):-2]
    inventory_body = inventory_body.replace("public static void main(String[] args)", "public static void inspectBaseline(String[] args)")
    probe_imports, probe_body = source.split("public class M2ApiProbe {", 1)
    imports = "\n".join(line for line in inventory_source.splitlines() if line.startswith("import "))
    source = imports + "\npublic class M2ApiProbe {\n" + inventory_body + probe_body.replace("ModelInventory.inspect(model)", "inspect(model)")
    (output / "M2ApiProbe.java").write_text(source, encoding="utf-8")
    bin_dir = args.comsol_root / "bin/win64"
    run([str(bin_dir / "comsolcompile.exe"), "M2ApiProbe.java"], output, "compile", args.timeout)
    for name in ("M2ApiProbe",):
        if not (output / f"{name}.class").is_file():
            raise RuntimeError(f"Missing compiled class: {name}")
    text = run([str(bin_dir / "comsolbatch.exe"), "-inputfile", "M2ApiProbe.class", "-nosave", "-batchlog", "batch.log", "-batchlogout", "-np", "2"], output, "batch", args.timeout)
    if "M2_API_VERIFIED" not in text or "M2_LICENSE_BASELINE true" not in text:
        raise RuntimeError(f"Missing completion marker; inspect {output}")
    inventories = {}
    for line in text.splitlines():
        if line.startswith("M2_INVENTORY "):
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
        for marker in (f"M2_READ_VERIFIED {name} 3", f"M2_UNSOLVED_VERIFIED {name} 3"):
            if marker not in text:
                raise RuntimeError(f"Missing genuine verification marker: {marker}")
    def heat(name):
        return next(p for p in inventories[name]["components"][0]["physics"] if p["tag"] == "ht")
    normal = inventories["normal"]["components"][0]["geometries"][0]
    evidence = normal["axisymmetric_evidence"]
    assert heat("normal")["type"] == "HeatTransferInFluids"
    assert heat("conjugate_normal")["type"] == "HeatTransfer"
    assert heat("normal")["heat_evidence"]["read_status"] == "read"
    assert inventories["conjugate_normal"]["components"][0]["geometries"][0]["domain_count"] == 2
    def features(name):
        return {f["tag"]: f for f in heat(name)["features"]}
    assert features("normal")["fluid1"]["type"] == "FluidHeatTransferModel"
    assert features("conjugate_normal")["solid1"]["type"] == "SolidHeatTransferModel"
    assert features("normal")["fluid1"]["parameters"]["u_src"] == "root.comp1.u"
    assert features("empty_heat_flux")["flux1"]["selected_entity_ids"] == []
    assert not heat("inactive_heat_study")["study_active"]
    assert features("legal_prescribed_velocity")["fluid1"]["parameters"]["u_src"] == "userdef"
    assert features("legal_convective_flux")["flux1"]["parameters"]["HeatFluxType"] == "ConvectiveHeatFlux"
    summary = {
        "schema_version": "m2-api-evidence-1", "verified_at": datetime.now().isoformat(timespec="seconds"),
        "comsol_version": inventories["normal"]["comsol_version"], "license_baseline_available": True,
        "solved": False, "solution_sequences_per_model": 0, "source_models_unchanged": True,
        "source_model_sha256": before, "reads_per_model": 3, "verified_models": sorted(inventories),
        "implementation_sha256": implementation_before, "implementation_sha256_after": implementation_after,
        "inventory_sha256": {name: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest() for name, value in inventories.items()},
        "output_model_sha256": {name: hashlib.sha256((output / f"{name}.mph").read_bytes()).hexdigest() for name in inventories},
        "repeat_markers": {name: f"M2_READ_VERIFIED {name} 3" for name in inventories},
        "unsolved_markers": {name: f"M2_UNSOLVED_VERIFIED {name} 3" for name in inventories},
        "generated_driver_sha256": hashlib.sha256((output / "M2ApiProbe.java").read_bytes()).hexdigest(),
        "geometry_api_evidence": evidence,
        "observed_boundary_types": {name: features("normal")[name]["type"] for name in ("axi1", "temp1", "flux1")},
        "scope": "Controlled unsolved 2D axisymmetric heated fluid pipe and fluid/solid wall API evidence; development samples, not independent accuracy evaluation",
        "limitations": ["No mesh or solver was run; repeated static reads do not establish physical correctness or convergence.", "Temperature-dependent material expression is retained unresolved without evaluating a solution field.", "Default managed thermal nodes are recorded with actual effective selections, including empty inactive applicability regions.", "NonIsothermalFlow domain selection is COMSOL-managed and cannot be edited; rejected explicit selection attempts remain in 214203 and 214244 logs. No fabricated empty/wrong coupling selection sample is counted.", "Initial sandboxed COMSOL launches stalled; successful verification used locally authorized COMSOL execution. Exploratory logs remain under outputs/m2_api/explore."]
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.write_fixture:
        (ROOT / "data/fixtures/m2_api_evidence.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (ROOT / "data/fixtures/m2_inventories.json").write_text(json.dumps(inventories, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "verified_models": sorted(inventories)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
