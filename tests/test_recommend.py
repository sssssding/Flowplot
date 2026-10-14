"""Synthetic offline fault tests; these are not real solver/calibration evidence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import recommend as ai
from flowpilot import calibrate_solver as calibration
from flowpilot import solve_baseline as solve
from flowpilot import ai_launcher
from flowpilot import recommend_ui
from flowpilot.check_model import CheckError, sha256

BASELINE_HASH = next(c for c in ai.read_json(ai.MANIFEST)["cases"] if c["case_id"] == "baseline")["sha256"].lower()


def synthetic_dataset():
    reference = ai.read_json(solve.REFERENCE)["runs"][0]
    rows = []
    for c in ai.CANDIDATES:
        for repeat in (1, 2, 3):
            evidence = {"schema_version": "baseline-solve-0.1", "comsol_version": "synthetic COMSOL",
                        "solution_cleared_before_solve": True, "solution_present_after_solve": True,
                        "solver_run": True, "solver_tag": "sol1", "solve_seconds": 4.0 if c["id"] == "strict-2" else 2.0,
                        "solver_warning": "", "solver_error": "",
                        "metrics": {k: reference[k] for k in solve.METRICS}}
            rows.append({"candidate": dict(c), "repeat": repeat, "evidence": evidence,
                         "analysis": solve.analyze_solve(evidence, reference), "process_seconds": 10.,
                         "solved_sha256": "1"*64, "console_sha256": "2"*64, "batch_sha256": "3"*64})
    return {"schema_version": "solver-calibration-0.1", "status": "completed", "repeats": 3,
            "source_sha256": BASELINE_HASH, "environment_id": ai.environment_id(),
            "sources": {"driver": sha256(solve.JAVA_SOURCE), "reference": sha256(solve.REFERENCE)},
            "observations": rows}


class RecommendationTest(unittest.TestCase):
    def setUp(self):
        self.dataset = synthetic_dataset()

    def rank(self, dataset=None):
        return ai.rank(ai.fit(dataset or self.dataset), BASELINE_HASH)

    def test_real_learning_ranks_measured_candidates_without_solving(self):
        with patch.object(calibration, "_run", side_effect=AssertionError("Inference must not solve")):
            result = self.rank()
        self.assertEqual(result["status"], "recommended")
        self.assertEqual(result["selected"]["id"], "balanced-2")
        self.assertFalse(result["independent_validation"])
        self.assertEqual(len(result["ranking"]), 4)
        self.assertAlmostEqual(result["ranking"][0]["predicted_solve_seconds"], 2.)

    def test_small_or_overlapping_gain_keeps_original(self):
        for row in self.dataset["observations"]:
            row["evidence"]["solve_seconds"] = 4 if row["candidate"]["id"] == "strict-2" else 3.9
        self.assertEqual(self.rank()["selected"]["id"], "strict-2")
        self.dataset["observations"][0]["evidence"]["solve_seconds"] = 5.
        self.assertEqual(self.rank()["selected"]["id"], "strict-2")

    def test_unknown_model_and_hardware_abstain(self):
        model = ai.fit(self.dataset)
        for digest, cohort in (("b"*64, ai.environment_id()), (BASELINE_HASH, "0"*64)):
            result = ai.rank(model, digest, cohort=cohort)
            self.assertEqual(result["status"], "unavailable")
            self.assertIsNone(result["selected"])

    def test_quality_failure_and_warning_exclude_candidate(self):
        reference = ai.read_json(solve.REFERENCE)["runs"][0]
        for row in self.dataset["observations"]:
            if row["candidate"]["id"] == "balanced-2":
                row["evidence"]["metrics"]["pressure_drop_pa"] *= 2
                row["analysis"] = solve.analyze_solve(row["evidence"], reference)
            if row["candidate"]["id"] == "loose-2":
                row["evidence"]["solver_warning"] = "warning"
        self.assertEqual([x["candidate"]["id"] for x in self.rank()["ranking"]], ["strict-1", "strict-2"])

    def test_default_quality_failure_blocks_all_recommendations(self):
        for row in self.dataset["observations"]:
            if row["candidate"]["id"] == "strict-2":
                row["evidence"]["solver_warning"] = "unreviewed"
        self.assertEqual(self.rank()["status"], "unavailable")

    def test_incomplete_duplicate_unknown_or_forged_observations_rejected(self):
        mutations = [lambda d: d.update(status="failed"), lambda d: d["observations"].pop(),
                     lambda d: d["observations"].__setitem__(0, copy.deepcopy(d["observations"][1])),
                     lambda d: d["observations"][0]["candidate"].update(threads=True),
                     lambda d: d["observations"][0]["candidate"].update(stol=.001),
                     lambda d: d["observations"][0].update(evidence=None),
                     lambda d: d["observations"][0]["analysis"].update(engineering_checks_passed=False),
                     lambda d: d["observations"][0].update(process_seconds=float("inf")),
                     lambda d: d["observations"][0].update(batch_sha256=""),
                     lambda d: d["observations"][0]["evidence"].update(comsol_version="other"),
                     lambda d: d["sources"].update(driver="0"*64)]
        for mutate in mutations:
            dataset = copy.deepcopy(self.dataset)
            mutate(dataset)
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, CheckError)):
                ai.fit(dataset)

    def test_model_cannot_claim_independent_acceptance_or_change_method(self):
        for changes in ({"method": "external-api"}, {"k": True}, {"independent_validation": True},
                        {"expert_review": "approved"}):
            model = ai.fit(self.dataset)
            model.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ai.rank(model, BASELINE_HASH)

    def test_strict_bounded_json(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            path = Path(directory) / "model.json"
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'[]', b'x'*1048577):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    ai.read_json(path)

    def test_findings_partial_and_unsupported_never_recommend(self):
        for status, findings in (("checked", [{}]), ("partial", []), ("unsupported", [])):
            loaded = {"metadata": {"source": {"sha256": "a"*64}}, "report": {"status": status, "findings": findings}}
            with patch.object(ai, "load_completed_check", return_value=loaded), \
                    patch.object(ai, "read_regular_file", side_effect=AssertionError("Do not load ranker")):
                self.assertEqual(ai.recommend_report("unused")["status"], "unavailable")

    def test_report_inference_binds_exact_loaded_model_bytes(self):
        loaded = {"metadata": {"source": {"sha256": BASELINE_HASH}}, "report": {"status": "checked", "findings": []},
                  "diagnosis_sha256": "b"*64}
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(ai.fit(self.dataset)), encoding="utf-8")
            with patch.object(ai, "load_completed_check", return_value=loaded):
                result = ai.recommend_report("unused", path)
            self.assertEqual(result["learned_model_sha256"], sha256(path))
            self.assertEqual(result["diagnosis_sha256"], "b"*64)

    def test_current_real_calibration_recomputes_without_claiming_independence(self):
        model = ai.read_json(ai.DEFAULT_MODEL)
        self.assertEqual(ai.fit(model["dataset"]), model)
        result = ai.rank(model, BASELINE_HASH, cohort=model["dataset"]["environment_id"])
        self.assertEqual(result["status"], "recommended")
        self.assertFalse(result["independent_validation"])
        self.assertEqual(result["calibration_samples"], 12)
        self.assertEqual(len(result["ranking"]), 4)

    def test_functional_smoke_is_bound_to_current_sources_not_visible_acceptance(self):
        self.assertEqual(sha256(ROOT / "data/fixtures/ai_functional_smoke.json"),
                         "e198aa2590e31e4a9440e5024ae6b1ee4922b0da8b0a8cac45a31f2e26634765")
        record = ai.read_json(ROOT / "data/fixtures/ai_offline_preview_smoke.json")
        self.assertTrue(record["all_passed"])
        self.assertEqual(len(record["checks"]), 15)
        self.assertTrue(all(record["checks"].values()))
        self.assertFalse(record["solver_run_in_smoke"])
        self.assertFalse(record["visible_user_acceptance"])
        self.assertFalse(record["independent_performance_validation"])
        self.assertEqual(record["learned_model_sha256"], sha256(ai.DEFAULT_MODEL))
        for name, digest in record["source_sha256"].items():
            self.assertEqual(sha256(ROOT / name), digest)

    def test_dependency_failure_never_opens_window(self):
        with patch.object(ai_launcher, "check_environment", return_value=[{"name": "jsonschema", "status": "error"}]), \
                patch.object(ai_launcher.subprocess, "run", side_effect=AssertionError("Must not open UI")):
            self.assertEqual(ai_launcher.launch([]), 1)

    def test_bad_preview_report_exits_before_initializing_tk(self):
        with patch.object(recommend_ui, "load_completed_check", side_effect=CheckError("damaged report")), \
                patch("tkinter.Tk", side_effect=AssertionError("Invalid report must not open window")):
            with self.assertRaises(SystemExit) as result:
                recommend_ui.main(["--report", "bad directory"])
            self.assertEqual(result.exception.code, 1)

    def test_preview_startup_never_starts_a_model_check(self):
        loaded = {"test": "synthetic startup payload"}
        with patch.object(recommend_ui, "load_completed_check", return_value=loaded), \
                patch("tkinter.Tk") as root, patch.object(recommend_ui, "RecommendationApp") as app:
            recommend_ui.main(["--report", "report with spaces"])
            app.return_value.show_result.assert_called_once_with(loaded)
            app.return_value.result_tabs.select.assert_called_once_with(app.return_value.ai_tab)
            app.return_value.start_check.assert_not_called()
            root.return_value.mainloop.assert_called_once()

    def test_launcher_preserves_literal_arguments_and_does_not_require_license(self):
        with patch.object(ai_launcher, "check_environment", return_value=[{"name": "comsol", "status": "error"}]), \
                patch.object(ai_launcher.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(ai_launcher.launch(["--model", "path with spaces.mph"]), 0)
            self.assertEqual(run.call_args.args[0][-2:], ["--model", "path with spaces.mph"])
            self.assertNotIn("shell", run.call_args.kwargs)


class CalibrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.model = self.directory / "base.mph"
        self.model.write_bytes(b"synthetic MPH")
        self.manifest = self.directory / "manifest.json"
        self.manifest.write_text(json.dumps({"cases": [{"case_id": "baseline", "sha256": sha256(self.model)}]}))
        self.comsol = self.directory / "comsol"
        (self.comsol / "bin/win64").mkdir(parents=True)
        for name in ("comsolcompile.exe", "comsolbatch.exe"):
            (self.comsol / "bin/win64" / name).touch()
        self.output = self.directory / "calibration"
        self.calls = []

    def simulate(self, command, *, cwd, log, timeout):
        self.calls.append(command)
        if Path(command[0]).name == "comsolcompile.exe":
            (cwd / "CandidateSolve.class").write_bytes(b"mock class")
            Path(log).touch()
        else:
            c = next(c for c in ai.CANDIDATES if c["id"] == cwd.parent.name)
            payload = synthetic_dataset()["observations"][0]["evidence"]
            payload["solve_seconds"] = .001
            Path(log).write_text(f"FLOWPLOT_TOLERANCE {c['stol']}\nFLOWPILOT_SOLUTION_CLEARED\n"
                                 + "FLOWPILOT_SOLVE_JSON " + json.dumps(payload)
                                 + "\nFLOWPILOT_SOLVE_VERIFIED\n", encoding="utf-8")
            (cwd / "solved.mph").write_bytes(b"mock"*100)
            (cwd / "batch.log").write_bytes(b"mock native log")

    def run_calibration(self, runner=None):
        with patch.object(calibration, "MANIFEST", self.manifest), \
                patch.object(ai, "MANIFEST", self.manifest), \
                patch.object(calibration.time, "monotonic", side_effect=range(0, 1000, 10)), \
                patch.object(calibration, "_run", side_effect=runner or self.simulate):
            return calibration.calibrate(model_path=self.model, comsol_root=self.comsol, output_dir=self.output)

    def test_all_rotated_candidates_use_cold_copies_and_preserve_original(self):
        before = self.model.read_bytes()
        result = self.run_calibration()
        self.assertEqual(len(result["dataset"]["observations"]), 12)
        self.assertEqual(len(self.calls), 16)
        self.assertEqual(self.model.read_bytes(), before)
        for command in self.calls[4:]:
            self.assertIn("-nosave", command)
            self.assertIn(command[-1], ("1", "2"))
        self.assertTrue((self.output / "model.json").is_file())

    def test_modified_original_rejected_before_creating_output(self):
        self.model.write_bytes(b"user edit")
        with self.assertRaises(CheckError):
            self.run_calibration()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.model.read_bytes(), b"user edit")

    def test_existing_directory_never_overwritten(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.run_calibration()
        self.assertEqual(self.calls, [])

    def test_failed_compile_or_bad_tolerance_never_publishes_model(self):
        def bad(command, **kwargs):
            self.simulate(command, **kwargs)
            if Path(command[0]).name == "comsolbatch.exe":
                Path(kwargs["log"]).write_text("FLOWPLOT_TOLERANCE 0.1\n", encoding="utf-8")
        with self.assertRaises(CheckError):
            self.run_calibration(bad)
        self.assertFalse((self.output / "model.json").exists())
        self.assertEqual(ai.read_json(self.output / "run.json")["status"], "failed")


if __name__ == "__main__":
    unittest.main()
