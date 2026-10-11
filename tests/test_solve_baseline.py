"""Offline runner tests. Mock COMSOL output is not real simulation evidence."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import solve_baseline as solve


class SolveBaselineTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.reference = json.loads(solve.REFERENCE.read_text(encoding="utf-8-sig"))["runs"][0]
        self.payload = {"schema_version": "baseline-solve-0.1", "solver_run": True,
                        "solution_cleared_before_solve": True, "solution_present_after_solve": True,
                        "solver_tag": "sol1", "solve_seconds": 1.5, "comsol_version": "COMSOL 6.3.0.290",
                        "solver_warning": "", "solver_error": "",
                        "metrics": {key: self.reference[key] for key in solve.METRICS}}
        self.model = self.directory / "baseline.mph"
        self.model.write_bytes(b"synthetic model for an offline test")
        self.manifest = self.directory / "manifest.json"
        self.manifest.write_text(json.dumps({"cases": [{"case_id": "baseline", "model_path": str(self.model),
                                                        "sha256": solve.sha256(self.model)}]}), encoding="utf-8")
        self.comsol = self.directory / "COMSOL"
        binaries = self.comsol / "bin/win64"
        binaries.mkdir(parents=True)
        for name in ("comsolcompile.exe", "comsolbatch.exe"):
            (binaries / name).touch()
        self.output = self.directory / "run"
        self.calls = []

    def simulate(self, command, *, cwd, log, timeout):
        self.calls.append(command)
        if Path(command[0]).name == "comsolcompile.exe":
            (cwd / "BaselineSolve.class").write_bytes(b"compiled")
            Path(log).touch()
        else:
            self.assertIn("-nosave", command)
            self.assertEqual(command[-2:], ["-np", "2"])
            Path(log).write_text("FLOWPILOT_SOLUTION_CLEARED\nFLOWPILOT_SOLVE_JSON " + json.dumps(self.payload)
                                 + "\nFLOWPILOT_SOLVE_VERIFIED\n", encoding="utf-8")
            (cwd / "batch.log").write_bytes(b"native batch log fixture")
            (cwd / "solved.mph").write_bytes(b"mock solved model" * 20)

    def run_suite(self, runs=5, runner=None):
        with patch.object(solve, "MANIFEST", self.manifest), \
                patch.object(solve, "_run", side_effect=runner or self.simulate):
            return solve.solve_baseline(comsol_root=self.comsol, output_dir=self.output, runs=runs)

    def metadata(self):
        return json.loads((self.output / "run.json").read_text(encoding="utf-8"))

    def test_five_separate_copies_preserve_source_and_provenance(self):
        before = self.model.read_bytes()
        summary = self.run_suite()
        self.assertTrue(summary["all_checks_passed"])
        self.assertEqual(summary["completed_runs"], 5)
        self.assertEqual(summary["expert_review_status"], "expert_review_pending")
        self.assertEqual(summary["gui_log_comparison_status"], "pending")
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(self.metadata()["status"], "completed")
        self.assertEqual(self.model.read_bytes(), before)
        self.assertEqual(summary["source"]["sha256"], solve.sha256(self.model))
        for index in range(1, 6):
            self.assertEqual((self.output / f"run-{index:02d}/input.mph").read_bytes(), before)
        self.assertIn("GUI 日志对照仍待完成", (self.output / "report.md").read_text(encoding="utf-8"))

    def test_wrong_model_hash_refuses_launch(self):
        self.model.write_bytes(b"local edits")
        with self.assertRaisesRegex(solve.CheckError, "committed baseline"):
            self.run_suite()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        (self.output / "report.md").write_bytes(b"previous")
        with self.assertRaises(FileExistsError):
            self.run_suite()
        self.assertEqual((self.output / "report.md").read_bytes(), b"previous")
        self.assertEqual(self.calls, [])

    def test_missing_class_even_exit_zero_is_failure(self):
        with self.assertRaisesRegex(solve.CheckError, "compiled"):
            self.run_suite(runner=lambda command, **kwargs: Path(kwargs["log"]).touch())
        self.assertEqual(self.metadata()["stage"], "compile")
        self.assertEqual(self.metadata()["status"], "failed")

    def test_fail_fast_retains_successful_first_run(self):
        def fail_second(command, **kwargs):
            if kwargs["cwd"].name == "run-02":
                raise solve.CheckError("COMSOL timeout fixture")
            self.simulate(command, **kwargs)
        with self.assertRaisesRegex(solve.CheckError, "timeout"):
            self.run_suite(runner=fail_second)
        self.assertEqual(self.metadata()["completed_runs"], 1)
        self.assertEqual(self.metadata()["current_run"], 2)
        self.assertTrue((self.output / "run-01/result.json").exists())
        self.assertFalse((self.output / "summary.json").exists())
        self.assertFalse((self.output / "run-03").exists())

    def test_interrupt_is_recorded_as_cancelled(self):
        def interrupt(command, **kwargs):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_suite(runner=interrupt)
        self.assertEqual(self.metadata()["status"], "cancelled")

    def test_missing_saved_model_or_native_log_is_failure(self):
        for name in ("solved.mph", "batch.log"):
            self.output = self.directory / name.replace(".", "-")
            def remove_artifact(command, **kwargs):
                self.simulate(command, **kwargs)
                if Path(command[0]).name == "comsolbatch.exe":
                    (kwargs["cwd"] / name).unlink()
            with self.subTest(name=name), self.assertRaises(solve.CheckError):
                self.run_suite(runner=remove_artifact)
            self.assertEqual(self.metadata()["status"], "failed")
            self.assertFalse((self.output / "summary.json").exists())

    def test_modified_snapshot_refuses_completed_result(self):
        def modify(command, **kwargs):
            self.simulate(command, **kwargs)
            if Path(command[0]).name == "comsolbatch.exe":
                (kwargs["cwd"] / "input.mph").write_bytes(b"changed")
        with self.assertRaisesRegex(solve.CheckError, "snapshot changed"):
            self.run_suite(runner=modify)
        self.assertFalse((self.output / "summary.json").exists())

    def test_bad_engineering_metrics_stop_suite_with_evidence(self):
        self.payload["metrics"]["pressure_drop_pa"] *= 1.1
        with self.assertRaisesRegex(solve.CheckError, "engineering validation"):
            self.run_suite()
        self.assertTrue((self.output / "run-01/result.json").exists())
        self.assertFalse((self.output / "run-02").exists())
        self.assertFalse((self.output / "summary.json").exists())

    def test_missing_duplicate_and_out_of_order_markers_fail(self):
        log = self.directory / "console.log"
        payload = "FLOWPILOT_SOLVE_JSON " + json.dumps(self.payload) + "\n"
        clear, verified = "FLOWPILOT_SOLUTION_CLEARED\n", "FLOWPILOT_SOLVE_VERIFIED\n"
        for text in (payload + verified, clear + payload, clear * 2 + payload + verified,
                     clear + payload * 2 + verified, verified + clear + payload):
            log.write_text(text, encoding="utf-8")
            with self.subTest(text=text[:50]), self.assertRaises(solve.CheckError):
                solve._read_payload(log)

    def test_saved_solution_or_nonfinite_data_cannot_pass(self):
        mutations = [lambda p: p.update(solution_cleared_before_solve=False),
                     lambda p: p.update(solution_present_after_solve=False), lambda p: p.update(solver_run=False),
                     lambda p: p.update(solve_seconds=0), lambda p: p.update(solve_seconds=True),
                     lambda p: p["metrics"].update(max_speed_m_s=math.nan),
                     lambda p: p["metrics"].update(min_u_m_s=True), lambda p: p.update(solver_warning=None)]
        for mutate in mutations:
            payload = copy.deepcopy(self.payload)
            mutate(payload)
            with self.subTest(mutate=mutate), self.assertRaises(solve.CheckError):
                solve.analyze_solve(payload, self.reference)

    def test_zero_flow_and_solver_error_do_not_pass(self):
        self.payload["metrics"].update(mass_in_kg_m_s=0, mass_out_kg_m_s=0)
        self.payload["solver_error"] = "solver failed"
        result = solve.analyze_solve(self.payload, self.reference)
        self.assertIsNone(result["metrics"]["mass_relative_error"])
        self.assertFalse(result["engineering_checks_passed"])
        self.assertFalse(result["engineering_checks"]["no_solver_error"])

    def test_incomplete_or_drifting_suite_does_not_pass(self):
        run = {"analysis": solve.analyze_solve(self.payload, self.reference), "evidence": self.payload}
        with self.assertRaises(solve.CheckError):
            solve.summarize_runs([run], 5)
        second = copy.deepcopy(run)
        second["analysis"]["metrics"]["max_speed_m_s"] *= 1.01
        self.assertFalse(solve.summarize_runs([run, second], 2)["all_checks_passed"])

    def test_invalid_limits_rejected_before_launch(self):
        for runs in (0, 11, True, 1.5):
            with self.subTest(runs=runs), self.assertRaises(ValueError):
                self.run_suite(runs=runs)
        self.assertFalse(self.output.exists())

    def test_versioned_real_cold_solves_recompute_and_match_sources(self):
        stored = json.loads((ROOT / "data/fixtures/baseline_solve_suite.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["completed_runs"], 5)
        self.assertEqual(stored["requested_runs"], 5)
        for index, run in enumerate(stored["runs"], 1):
            self.assertEqual(run["index"], index)
            self.assertEqual(run["analysis"], solve.analyze_solve(run["evidence"], self.reference))
            self.assertTrue(run["analysis"]["engineering_checks_passed"])
            self.assertGreater(run["process_seconds"], run["evidence"]["solve_seconds"])
            self.assertEqual(run["evidence"]["solver_error"], "")
        summary = solve.summarize_runs(stored["runs"], 5)
        for key, value in summary.items():
            self.assertEqual(value, stored[key])
        manifest = json.loads(solve.MANIFEST.read_text(encoding="utf-8-sig"))
        baseline = next(case for case in manifest["cases"] if case["case_id"] == "baseline")
        self.assertEqual(stored["source"]["sha256"].lower(), baseline["sha256"].lower())
        self.assertEqual(stored["driver_sha256"], solve.sha256(solve.JAVA_SOURCE))
        self.assertEqual(stored["reference_sha256"], solve.sha256(solve.REFERENCE))


if __name__ == "__main__":
    unittest.main()
