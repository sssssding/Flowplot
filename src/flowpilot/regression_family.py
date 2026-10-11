"""Generate and inspect controlled, UNSOLVED rectangle variations, never acceptance data."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, ROOT, JAVA_SOURCE, _run, _write_json, sha256
from flowpilot.check_suite import run_suite, validate_manifest
from flowpilot.desktop_session import load_completed_check
from flowpilot.diagnostics import is_finite_number

ENTRY_SOURCE = ROOT / "src/comsol/RegressionFamily.java.in"
BASELINE = ROOT / "models/baseline_pipe_2d_laminar.mph"
BASELINE_SHA256 = "023d94cf9c7f2dd5b5bf1bd581b1f19ab8a38cf9304c3af25f239a2398707e1b"
# Expectations are specified BEFORE running the checker, not copied from its predictions.
SPECS = (
    ("units_equivalent", [], 1., .05, 1000., .001, .01),
    ("re_below", [], 1., .05, 1000., .001, .03998),
    ("re_at", [], 1., .05, 1000., .001, .04),
    ("re_above", ["REYNOLDS_RISK"], 1., .05, 1000., .001, .04002),
    ("zero_velocity", ["INLET_DIRECTION"], 1., .05, 1000., .001, 0.),
    ("reversed_fast", ["INLET_DIRECTION", "REYNOLDS_RISK"], 1., .05, 1000., .001, -.1),
    ("empty_inlet", ["MISSING_INLET"], 1., .05, 1000., .001, .01),
    ("empty_outlet", ["MISSING_OUTLET"], 1., .05, 1000., .001, .01),
    ("both_missing", ["MISSING_INLET", "MISSING_OUTLET"], 1., .05, 1000., .001, None),
    ("overlap_reversed", ["BC_SELECTION_OVERLAP", "MISSING_INLET"], 1., .05, 1000., .001, -.1),
    ("zero_viscosity", ["INVALID_MATERIAL_PARAMETER"], 1., .05, 1000., 0., .01),
    ("low_viscosity", ["REYNOLDS_RISK"], 1., .05, 1000., .0001, .01),
    ("short_narrow", [], .5, .02, 1000., .001, .01),
    ("long_wide", [], 2., .1, 1000., .001, .01),
)


def driver_source():
    source = JAVA_SOURCE.read_text(encoding="utf-8-sig")
    names = ", ".join(json.dumps(spec[0]) for spec in SPECS)
    entry = f"  private static final String[] FAMILY_NAMES = {{{names}}};\n"
    entry += ENTRY_SOURCE.read_text(encoding="utf-8-sig")
    for old, new in (
        ("public static void main(String[] args)", "public static void inspectBaseline(String[] args)"),
        ("public class ModelInventory {", "public class RegressionFamily {\n" + entry),
    ):
        if source.count(old) != 1:
            raise CheckError("Inventory entry changed; update the family adapter")
        source = source.replace(old, new)
    return source


def generation_markers(log):
    lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    def values(prefix):
        return [line[len(prefix):] for line in lines if line.startswith(prefix)]
    if (values("FLOWPILOT_FAMILY_SAVED ") != [spec[0] for spec in SPECS]
            or values("FLOWPILOT_FAMILY_VERIFIED ") != [str(len(SPECS))]):
        raise CheckError("Missing, duplicated or out-of-order family save markers")
    versions = values("FLOWPILOT_FAMILY_VERSION ")
    if len(versions) != 1:
        raise CheckError("Missing or ambiguous COMSOL version")
    try:
        version = json.loads(versions[0])
    except ValueError as error:
        raise CheckError("Malformed COMSOL version marker") from error
    if not isinstance(version, str) or not version.strip():
        raise CheckError("Missing COMSOL version string")
    return version


def case_evidence(loaded, spec):
    """Independently check dimensions, SI values and mutation-specific selection evidence."""
    name, expected, length, height, density, viscosity, velocity = spec
    report = loaded["report"]
    model = report.get("model", {})
    problems = []
    actual = {}
    def value(key, observed, wanted):
        actual[key] = observed
        if (not is_finite_number(observed)
                or not math.isclose(observed, wanted, rel_tol=1e-12, abs_tol=0.)):
            problems.append(key)
    value("length_m", model.get("geometry", {}).get("length_m"), length)
    value("height_m", model.get("geometry", {}).get("height_m"), height)
    for field, wanted in (("density", density), ("dynamic_viscosity", viscosity)):
        item = model.get("material", {}).get(field, {})
        value(field, item.get("value"), wanted)
        if item.get("status") != "resolved":
            problems.append(field + "_unresolved")
    boundaries = {item["feature_tag"]: item for item in model.get("boundaries", [])}
    if velocity is not None:
        item = boundaries.get("inl1", {}).get("parameters", {}).get("normal_velocity", {})
        value("normal_velocity_m_s", item.get("value"), velocity)
        if item.get("status") != "resolved":
            problems.append("velocity_unresolved")
    if name == "both_missing" and any(tag in boundaries for tag in ("inl1", "out1")):
        problems.append("deleted_nodes_still_present")
    for case, tag, code in (("empty_inlet", "inl1", "MISSING_INLET"),
                            ("empty_outlet", "out1", "MISSING_OUTLET")):
        if name == case:
            node = boundaries.get(tag)
            finding = next((f for f in report["findings"] if f["code"] == code), {})
            if (node is None or node["boundary_ids"] != [] or node["declared_boundary_ids"] != []
                    or finding.get("evidence", {}).get("absence_kind") != "all_effective_selections_empty"
                    or finding.get("feature_tags") != [tag]):
                problems.append("empty_selection_evidence")
    actual_codes = sorted({item["code"] for item in report["findings"]})
    if report["status"] != "checked" or actual_codes != sorted(expected):
        problems.append("status_or_codes")
    if name == "overlap_reversed" and boundaries.get("inl1", {}).get("boundary_ids") != []:
        problems.append("overridden_inlet_still_effective")
    return {"case_id": name, "passed": not problems, "mismatches": problems,
            "actual_values": actual, "expected_codes": sorted(expected), "actual_codes": actual_codes,
            "source_sha256": loaded["metadata"]["source"]["sha256"],
            "diagnosis_sha256": loaded["diagnosis_sha256"]}


def build_family(*, comsol_root, output_dir, loads=2, timeout=300.):
    if type(loads) is not int or not 1 <= loads <= 10 or not is_finite_number(timeout) or timeout <= 0:
        raise ValueError("loads must be 1 to 10 and timeout finite and positive")
    if sha256(BASELINE) != BASELINE_SHA256:
        raise CheckError("Baseline SHA-256 mismatch; no models generated")
    root = Path(comsol_root).resolve(strict=True)
    compiler, batch = (root / "bin/win64" / name for name in ("comsolcompile.exe", "comsolbatch.exe"))
    for path in (compiler, batch):
        if not path.is_file():
            raise FileNotFoundError(path)
    source = driver_source()
    output = Path(output_dir)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists: {output}")
    directory = output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": "regression-family-run-0.1", "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(), "baseline_sha256": BASELINE_SHA256,
                "builder_sha256": sha256(Path(__file__)), "entry_sha256": sha256(ENTRY_SOURCE),
                "inventory_source_sha256": sha256(JAVA_SOURCE), "stage": "generate"}
    try:
        snapshot = directory / "input.mph"
        shutil.copyfile(BASELINE, snapshot)
        if sha256(snapshot) != BASELINE_SHA256:
            raise CheckError("Baseline changed during snapshot")
        (directory / "models").mkdir()
        driver = directory / "RegressionFamily.java"
        with driver.open("x", encoding="utf-8") as stream:
            stream.write(source)
        _run([str(compiler), str(driver)], cwd=directory, log=directory / "compile.log", timeout=timeout)
        compiled = directory / "RegressionFamily.class"
        if not compiled.is_file() or compiled.stat().st_size == 0:
            raise CheckError("Missing compiled family driver")
        log = directory / "batch-console.log"
        _run([str(batch), "-inputfile", str(compiled), "-nosave", "-batchlog",
              str(directory / "batch.log"), "-batchlogout", "-np", "2"],
             cwd=directory, log=log, timeout=timeout)
        version = generation_markers(log)
        if sha256(BASELINE) != BASELINE_SHA256 or sha256(snapshot) != BASELINE_SHA256:
            raise CheckError("Source or snapshot hash changed during generation")
        manifest = {"schema_version": "case-manifest-0.1", "comsol_version": version,
                    "family": "controlled_rectangular_channel_variations", "reynolds_warning": 2000.,
                    "label_status": "engineering_expected_expert_review_pending",
                    "independent_acceptance_set": False, "cases": []}
        for spec in SPECS:
            name, expected, *_ = spec
            model = directory / "models" / (name + ".mph")
            if model.is_symlink() or not model.is_file() or model.stat().st_size == 0:
                raise CheckError(f"Missing saved variation: {name}")
            manifest["cases"].append({"case_id": name, "model_path": "models/" + model.name,
                                      "sha256": sha256(model), "expected_codes": expected,
                                      "used_for_rule_development": True})
        validate_manifest(manifest)
        _write_json(directory / "manifest.json", manifest)
        metadata["stage"] = "check"
        suite = run_suite(directory / "manifest.json", comsol_root=root, model_root=directory,
                          output_dir=directory / "checks", loads=loads, timeout=timeout)
        evidence = [case_evidence(load_completed_check(directory / "checks" / spec[0]), spec) for spec in SPECS]
        if sha256(BASELINE) != BASELINE_SHA256 or sha256(snapshot) != BASELINE_SHA256:
            raise CheckError("Source or snapshot hash changed during verification")
        # Never label a broken generator/checker as successful just because all subprocesses exited zero.
        passed = (suite["checked_cases"] == len(SPECS) == suite["exact_match_cases"]
                  and all(case["passed"] for case in evidence))
        summary = {"schema_version": "regression-family-0.1", "verification_passed": passed,
                   "comsol_version": version, "verified_loads_per_case": loads, "case_count": len(SPECS),
                   "distinct_geometry_count": len({(spec[2], spec[3]) for spec in SPECS}),
                   "models_solved": False, "expert_review": False, "independent_acceptance_set": False,
                   "baseline_sha256": BASELINE_SHA256, "rule_engine_sha256": suite["rule_engine_sha256"],
                   "builder_sha256": metadata["builder_sha256"], "entry_sha256": metadata["entry_sha256"],
                   "inventory_source_sha256": metadata["inventory_source_sha256"], "cases": evidence}
        _write_json(directory / "summary.json", summary)
        metadata["status"] = "completed" if passed else "mismatch"
        return summary
    except KeyboardInterrupt:
        metadata.update(status="cancelled", error="Interrupted by user")
        raise
    except Exception as error:
        metadata.update(status="failed", error=str(error))
        raise
    finally:
        metadata["baseline_unchanged"] = sha256(BASELINE) == BASELINE_SHA256
        metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(directory / "run.json", metadata)


def main():
    parser = argparse.ArgumentParser(description="Generate and inspect 14 controlled, unsolved COMSOL variations")
    parser.add_argument("--comsol-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory, never reused")
    parser.add_argument("--loads", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=300.)
    args = parser.parse_args()
    try:
        summary = build_family(comsol_root=args.comsol_root, output_dir=args.output_dir,
                               loads=args.loads, timeout=args.timeout)
    except (OSError, ValueError, CheckError, KeyError, TypeError) as error:
        parser.exit(1, f"Family failed: {error}\n")
    print(f"Verified {sum(case['passed'] for case in summary['cases'])}/{summary['case_count']}; "
          f"{args.output_dir / 'summary.json'}")
    if not summary["verification_passed"]:
        parser.exit(2, "Variation/evidence mismatches; inspect summary.json\n")


if __name__ == "__main__":
    main()
