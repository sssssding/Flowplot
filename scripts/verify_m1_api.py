"""Read actual COMSOL 6.3 models repeatedly; generate unsolved controlled output copies.

Usage: python scripts/verify_m1_api.py --comsol-root "<COMSOL_ROOT>" --write-fixture
All generated Java/classes, models and detailed command logs remain under outputs/m1_api.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {"normal", "missing_inlet", "missing_outlet", "empty_inlet", "selection_overlap",
           "axis_wrong_selection", "legal_explicit_selection", "legal_slip_wall",
           "unsupported_inlet_mode", "closed_flow", "high_reynolds", "reversed_inlet", "invalid_material"}
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
    output = ROOT / "outputs" / "m1_api" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True)
    models = [ROOT / "models/baseline_pipe_2d_laminar.mph", *sorted((ROOT / "models/cases").glob("*.mph"))]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in models}
    implementations = [ROOT / "src/comsol/ModelInventory.java", ROOT / "src/comsol/M1ApiProbe.java.in", Path(__file__).resolve()]
    implementation_before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in implementations}
    source = (ROOT / "src/comsol/M1ApiProbe.java.in").read_text(encoding="utf-8")
    for key, path in {"BASE": models[0], "CASES": ROOT / "models/cases", "OUTPUT": output}.items():
        source = source.replace(f"@{key}@", path.as_posix())
    inventory_source = (ROOT / "src/comsol/ModelInventory.java").read_text(encoding="utf-8")
    inventory_body = inventory_source[inventory_source.index("public class ModelInventory {") + len("public class ModelInventory {"):-2]
    inventory_body = inventory_body.replace("public static void main(String[] args)", "public static void inspectBaseline(String[] args)")
    probe_imports, probe_body = source.split("public class M1ApiProbe {", 1)
    imports = "\n".join(line for line in inventory_source.splitlines() if line.startswith("import "))
    source = imports + "\npublic class M1ApiProbe {\n" + inventory_body + probe_body.replace("ModelInventory.inspect(model)", "inspect(model)")
    (output / "M1ApiProbe.java").write_text(source, encoding="utf-8")
    bin_dir = args.comsol_root / "bin/win64"
    run([str(bin_dir / "comsolcompile.exe"), "M1ApiProbe.java"], output, "compile", args.timeout)
    for name in ("M1ApiProbe",):
        if not (output / f"{name}.class").is_file():
            raise RuntimeError(f"Missing compiled class: {name}")
    text = run([str(bin_dir / "comsolbatch.exe"), "-inputfile", "M1ApiProbe.class", "-nosave", "-batchlog", "batch.log", "-batchlogout", "-np", "2"], output, "batch", args.timeout)
    if "M1_API_VERIFIED" not in text or "M1_LICENSE_BASELINE true" not in text:
        raise RuntimeError(f"Missing completion marker; inspect {output}")
    inventories = {}
    for line in text.splitlines():
        if line.startswith("M1_INVENTORY "):
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
        for marker in (f"M1_READ_VERIFIED {name} 3", f"M1_UNSOLVED_VERIFIED {name} 3"):
            if marker not in text:
                raise RuntimeError(f"Missing genuine verification marker: {marker}")
    def features(name):
        return {f["tag"]: f for f in inventories[name]["components"][0]["physics"][0]["features"]}
    normal = inventories["normal"]["components"][0]["geometries"][0]
    evidence = normal["axisymmetric_evidence"]
    assert normal["axisymmetric"] and evidence["read_status"] == "read"
    assert evidence["spatial_coordinate_names"] == ["r", "phi", "z"]
    assert evidence["vertex_coordinates"] == [[0.0, 0.0, 0.025, 0.025], [0.0, 1.0, 0.0, 1.0]]
    assert all(b["domain_ids"] == [1] and len(b["sample_coordinates"]) == 3 for b in evidence["boundaries"])
    assert features("normal")["axi1"]["type"] == "AxialSymmetry"
    assert features("normal")["axi1"]["selected_entity_ids"] == [1]
    assert "inl1" not in features("missing_inlet") and "out1" not in features("missing_outlet")
    assert features("empty_inlet")["inl1"]["declared_entity_ids"] == []
    assert features("selection_overlap")["out_conflict"]["declared_entity_ids"] == [2]
    assert features("axis_wrong_selection")["wall_axis"]["declared_entity_ids"] == [1]
    assert features("axis_wrong_selection")["wall_axis"]["selected_entity_ids"] == []
    assert features("legal_explicit_selection")["inl1"]["named_selection"] == ""
    assert features("legal_slip_wall")["wallbc1"]["parameters"]["BoundaryCondition"] == "Slip"
    assert features("unsupported_inlet_mode")["inl1"]["parameters"]["BoundaryCondition"] == "MassFlow"
    assert not {"inl1", "out1"} & features("closed_flow").keys()
    assert features("high_reynolds")["inl1"]["evaluated_parameters"]["normal_velocity"]["value"] == 0.1
    assert features("reversed_inlet")["inl1"]["evaluated_parameters"]["normal_velocity"]["value"] == -0.01
    assert inventories["invalid_material"]["components"][0]["materials"][0]["dynamic_viscosity"]["value"] == -0.001
    summary = {
        "schema_version": "m1-api-evidence-1", "verified_at": datetime.now().isoformat(timespec="seconds"),
        "comsol_version": inventories["normal"]["comsol_version"], "license_baseline_available": True,
        "solved": False, "solution_sequences_per_model": 0, "source_models_unchanged": True,
        "source_model_sha256": before, "reads_per_model": 3, "verified_models": sorted(inventories),
        "implementation_sha256": implementation_before, "implementation_sha256_after": implementation_after,
        "inventory_sha256": {name: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest() for name, value in inventories.items()},
        "output_model_sha256": {name: hashlib.sha256((output / f"{name}.mph").read_bytes()).hexdigest() for name in inventories},
        "repeat_markers": {name: f"M1_READ_VERIFIED {name} 3" for name in inventories},
        "unsolved_markers": {name: f"M1_UNSOLVED_VERIFIED {name} 3" for name in inventories},
        "generated_driver_sha256": hashlib.sha256((output / "M1ApiProbe.java").read_bytes()).hexdigest(),
        "geometry_api_evidence": evidence,
        "observed_boundary_types": {name: features("normal")[name]["type"] for name in ("axi1", "inl1", "out1", "wallbc1")},
        "scope": "Controlled unsolved 2D axisymmetric single-domain straight circular pipe API evidence; development samples, not independent accuracy evaluation",
        "limitations": ["COMSOL-managed default AxialSymmetry selection cannot be edited and the node cannot be disabled; rejected attempts retained in local probe logs.", "axis_wrong_selection adds an explicit wall declaration on the axis; COMSOL filters its effective selection to empty, leaving the managed axis effective.", "closed_flow removes both ports as a deliberate closed configuration alternative; all fault cases change only one setting or add one node.", "No mesh or solver was run; repeated static reads do not establish physical correctness or convergence."]
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.write_fixture:
        (ROOT / "data/fixtures/m1_api_evidence.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (ROOT / "data/fixtures/m1_inventories.json").write_text(json.dumps(inventories, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "verified_models": sorted(inventories)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
