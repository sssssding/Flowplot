"""Offline generator failure tests; real COMSOL evidence lives in the versioned summary."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import regression_family as family
from flowpilot.check_model import CheckError, sha256
from flowpilot.diagnostics import diagnose_inventory


def simulated_report(spec):
    """Synthetic inventories simulate mutation semantics, not COMSOL API validation."""
    name, _, length, height, rho, mu, speed = spec
    inventory = json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))
    component = inventory["components"][0]
    component["geometries"][0]["bounding_box"] = [0, length, 0, height]
    component["materials"][0]["density"]["value"] = rho
    component["materials"][0]["dynamic_viscosity"]["value"] = mu
    features = component["physics"][0]["features"]
    inlet = next(item for item in features if item["tag"] == "inl1")
    if speed is not None:
        inlet["evaluated_parameters"]["normal_velocity"]["value"] = speed
    if name == "both_missing":
        features[:] = [f for f in features if f["tag"] not in ("inl1", "out1")]
    if name in ("empty_inlet", "empty_outlet"):
        node = next(f for f in features if f["tag"] == ("inl1" if name == "empty_inlet" else "out1"))
        node.update(selected_entity_ids=[], declared_entity_ids=[])
    if name == "overlap_reversed":
        other = copy.deepcopy(next(f for f in features if f["tag"] == "out1"))
        other.update(tag="out_conflict", selected_entity_ids=inlet["selected_entity_ids"],
                     declared_entity_ids=inlet["declared_entity_ids"])
        inlet["selected_entity_ids"] = []
        features.append(other)
    return {"report": diagnose_inventory(inventory), "metadata": {"source": {"sha256": "a" * 64}},
            "diagnosis_sha256": "b" * 64}


class RegressionFamilyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.baseline = self.directory / "baseline.mph"
        self.baseline.write_bytes(b"synthetic baseline, not a COMSOL model")
        self.baseline_sha = sha256(self.baseline)
        self.root = self.directory / "COMSOL with spaces"
        binaries = self.root / "bin/win64"
        binaries.mkdir(parents=True)
        for name in ("comsolcompile.exe", "comsolbatch.exe"):
            (binaries / name).touch()
        self.output = self.directory / "new family"
        self.source_patch = patch.object(family, "BASELINE", self.baseline)
        self.sha_patch = patch.object(family, "BASELINE_SHA256", self.baseline_sha)
        self.source_patch.start()
        self.sha_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.addCleanup(self.sha_patch.stop)

    def simulate_process(self, command, *, cwd, log, timeout):
        self.assertEqual(timeout, 300.)
        if Path(command[0]).name == "comsolcompile.exe":
            (cwd / "RegressionFamily.class").write_bytes(b"synthetic compiled driver")
            Path(log).write_text("", encoding="utf-8")
        else:
            self.assertIn("-nosave", command)
            self.assertEqual((cwd / "input.mph").read_bytes(), self.baseline.read_bytes())
            for spec in family.SPECS:
                (cwd / "models" / (spec[0] + ".mph")).write_bytes(b"synthetic variation " + spec[0].encode())
            Path(log).write_text("\n".join("FLOWPILOT_FAMILY_SAVED " + s[0] for s in family.SPECS)
                                 + '\nFLOWPILOT_FAMILY_VERSION "synthetic-test-only"\n'
                                 + "FLOWPILOT_FAMILY_VERIFIED 14\n", encoding="utf-8")

    def simulate_suite(self, manifest_path, **options):
        manifest = family.validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
        self.assertFalse(manifest["independent_acceptance_set"])
        self.assertTrue(all(c["used_for_rule_development"] for c in manifest["cases"]))
        self.assertEqual(options["model_root"], self.output)
        return {"checked_cases": 14, "exact_match_cases": 14, "rule_engine_sha256": "c" * 64}

    def run_family(self, **options):
        with patch.object(family, "_run", side_effect=self.simulate_process), \
             patch.object(family, "run_suite", side_effect=self.simulate_suite), \
             patch.object(family, "load_completed_check", side_effect=lambda p: simulated_report(
                 next(s for s in family.SPECS if s[0] == p.name))):
            return family.build_family(comsol_root=self.root, output_dir=self.output, **options)

    def metadata(self):
        return json.loads((self.output / "run.json").read_text(encoding="utf-8"))

    def test_fixed_driver_no_user_path_or_solve(self):
        source = family.driver_source()
        self.assertEqual(source.count("public static void main(String[] args)"), 1)
        entry = family.ENTRY_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn(".run();", entry.replace('.geom("geom1").run();', ""))
        self.assertNotIn(str(self.baseline), source)
        self.assertIn('clearSolutionData()', entry)
        self.assertIn('isEmpty()', entry)
        self.assertIn('selection(tag).entities(1).length', entry)

    def test_all_synthetic_mutations_have_expected_evidence(self):
        for spec in family.SPECS:
            with self.subTest(case=spec[0]):
                self.assertTrue(family.case_evidence(simulated_report(spec), spec)["passed"])

    def test_success_new_models_manifest_and_protected_baseline(self):
        result = self.run_family()
        self.assertTrue(result["verification_passed"])
        self.assertEqual(result["case_count"], 14)
        self.assertEqual(result["distinct_geometry_count"], 3)
        self.assertFalse(result["models_solved"])
        self.assertFalse(result["expert_review"])
        self.assertFalse(result["independent_acceptance_set"])
        self.assertEqual(self.metadata()["status"], "completed")
        self.assertTrue(self.metadata()["baseline_unchanged"])
        self.assertEqual(sha256(self.baseline), self.baseline_sha)

    def test_existing_output_never_reused(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.run_family()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_baseline_mismatch_prevents_creation(self):
        self.baseline.write_bytes(b"user modified model")
        with self.assertRaisesRegex(CheckError, "Baseline SHA"):
            self.run_family()
        self.assertFalse(self.output.exists())

    def test_options_rejected_before_launch(self):
        for options in ({"loads": True}, {"loads": 0}, {"loads": 11}, {"timeout": True},
                        {"timeout": float("nan")}, {"timeout": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_family(**options)
        self.assertFalse(self.output.exists())

    def test_changed_inventory_entry_fails_before_creation(self):
        with patch.object(Path, "read_text", return_value="unexpected Java source"), self.assertRaises(CheckError):
            self.run_family()
        self.assertFalse(self.output.exists())

    def test_missing_compiled_output_fails_without_batch(self):
        with patch.object(family, "_run") as run, self.assertRaisesRegex(CheckError, "compiled"):
            family.build_family(comsol_root=self.root, output_dir=self.output)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.metadata()["status"], "failed")
        self.assertFalse((self.output / "manifest.json").exists())

    def test_process_failure_or_interrupt_preserves_source_and_records_status(self):
        for error, expected in ((CheckError("synthetic timeout"), "failed"), (KeyboardInterrupt(), "cancelled")):
            self.output = self.directory / expected
            with patch.object(family, "_run", side_effect=error), self.assertRaises(type(error)):
                family.build_family(comsol_root=self.root, output_dir=self.output)
            self.assertEqual(self.metadata()["status"], expected)
            self.assertTrue(self.metadata()["baseline_unchanged"])

    def test_marker_missing_duplicate_reordered_and_version_rejected(self):
        log = self.directory / "console.log"
        good = ["FLOWPILOT_FAMILY_SAVED " + s[0] for s in family.SPECS]
        tail = ['FLOWPILOT_FAMILY_VERSION "synthetic"', "FLOWPILOT_FAMILY_VERIFIED 14"]
        log.write_text("\n".join(good + tail), encoding="utf-8")
        self.assertEqual(family.generation_markers(log), "synthetic")
        localized = "COMSOL Multiphysics 6.3 (开发版本: 290)"
        log.write_text("\n".join(good + ["FLOWPILOT_FAMILY_VERSION " + json.dumps(localized)] + tail[1:]),
                       encoding="utf-8")
        self.assertEqual(family.generation_markers(log), localized)
        for lines in (good[1:] + tail, good + good[:1] + tail, good[::-1] + tail,
                      good + tail[:1], good + tail + tail[:1], good + tail[1:],
                      good + ['FLOWPILOT_FAMILY_VERSION invalid'] + tail[1:],
                      good + ['FLOWPILOT_FAMILY_VERSION null'] + tail[1:],
                      good + ['FLOWPILOT_FAMILY_VERSION ""'] + tail[1:]):
            log.write_text("\n".join(lines), encoding="utf-8")
            with self.assertRaises(CheckError):
                family.generation_markers(log)

    def test_missing_or_duplicate_model_cannot_publish_manifest(self):
        original = self.simulate_process
        for label in ("missing", "duplicate"):
            self.output = self.directory / label
            def process(command, **options):
                original(command, **options)
                if Path(command[0]).name == "comsolbatch.exe":
                    first, second = sorted((options["cwd"] / "models").glob("*.mph"))[:2]
                    if label == "missing":
                        first.unlink()
                    else:
                        second.write_bytes(first.read_bytes())
            with patch.object(family, "_run", side_effect=process), self.assertRaises((CheckError, ValueError)):
                family.build_family(comsol_root=self.root, output_dir=self.output)
            self.assertFalse((self.output / "manifest.json").exists())

    def test_snapshot_mutation_detected(self):
        def process(command, **options):
            self.simulate_process(command, **options)
            if Path(command[0]).name == "comsolbatch.exe":
                (options["cwd"] / "input.mph").write_bytes(b"synthetic damaged snapshot")
        with patch.object(family, "_run", side_effect=process), self.assertRaisesRegex(CheckError, "hash changed"):
            family.build_family(comsol_root=self.root, output_dir=self.output)
        self.assertEqual(self.metadata()["status"], "failed")

    def test_geometry_or_si_or_status_mismatch_not_success(self):
        spec = family.SPECS[0]
        for field in ("length_m", "height_m", "density", "status"):
            loaded = simulated_report(spec)
            if field in ("length_m", "height_m"):
                loaded["report"]["model"]["geometry"][field] *= 2
            elif field == "density":
                loaded["report"]["model"]["material"][field]["value"] = True
            else:
                loaded["report"]["status"] = "partial"
            self.assertFalse(family.case_evidence(loaded, spec)["passed"])

    def test_empty_selection_is_not_deleted_node(self):
        spec = next(s for s in family.SPECS if s[0] == "empty_inlet")
        loaded = simulated_report(spec)
        loaded["report"]["model"]["boundaries"] = [b for b in loaded["report"]["model"]["boundaries"]
                                                    if b["feature_tag"] != "inl1"]
        self.assertIn("empty_selection_evidence", family.case_evidence(loaded, spec)["mismatches"])

    def test_si_evidence_mismatch_records_mismatch_not_completed(self):
        original = family.case_evidence
        def mismatch(loaded, spec):
            loaded = copy.deepcopy(loaded)
            loaded["report"]["model"]["geometry"]["length_m"] *= 2
            return original(loaded, spec)
        with patch.object(family, "case_evidence", side_effect=mismatch):
            result = self.run_family()
        self.assertFalse(result["verification_passed"])
        self.assertEqual(self.metadata()["status"], "mismatch")

    def test_real_versioned_evidence_and_current_sources(self):
        result = json.loads((ROOT / "data/fixtures/regression_family.json").read_text(encoding="utf-8"))
        self.assertTrue(result["verification_passed"])
        self.assertIn("6.3", result["comsol_version"])
        self.assertIn("290", result["comsol_version"])
        self.assertNotIn("\ufffd", result["comsol_version"])
        self.assertEqual(result["verified_loads_per_case"], 2)
        self.assertEqual(result["case_count"], 14)
        self.assertEqual(result["distinct_geometry_count"], 3)
        self.assertEqual(result["builder_sha256"], sha256(Path(family.__file__)))
        self.assertEqual(result["entry_sha256"], sha256(family.ENTRY_SOURCE))
        self.assertEqual(result["rule_engine_sha256"], sha256(ROOT / "src/flowpilot/diagnostics.py"))
        self.assertEqual(result["inventory_source_sha256"], sha256(family.JAVA_SOURCE))
        self.assertFalse(result["models_solved"])
        self.assertFalse(result["expert_review"])
        self.assertFalse(result["independent_acceptance_set"])
        self.assertEqual([c["case_id"] for c in result["cases"]], [s[0] for s in family.SPECS])
        self.assertTrue(all(c["passed"] and c["mismatches"] == [] for c in result["cases"]))
        self.assertEqual(len({c["source_sha256"] for c in result["cases"]}), 14)
        for case, spec in zip(result["cases"], family.SPECS):
            self.assertEqual(case["actual_codes"], sorted(spec[1]))
            self.assertEqual(case["expected_codes"], sorted(spec[1]))
            for field, wanted in zip(("length_m", "height_m", "density", "dynamic_viscosity",
                                      "normal_velocity_m_s"), spec[2:]):
                if wanted is not None:
                    self.assertAlmostEqual(case["actual_values"][field], wanted, places=12)


if __name__ == "__main__":
    unittest.main()
