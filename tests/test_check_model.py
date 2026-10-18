"""Offline orchestration checks; mocked COMSOL output is not a real MPH test."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import check_model as cli


class ModelCheckTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.model = self.directory / "模型 with spaces.mph"
        self.model.write_bytes(b"mock MPH bytes: original must remain unchanged")
        self.comsol = self.directory / "COMSOL with spaces"
        binaries = self.comsol / "bin" / "win64"
        binaries.mkdir(parents=True)
        for name in ("comsolcompile.exe", "comsolbatch.exe"):
            (binaries / name).touch()
        self.inventory = json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))
        self.inventory["components"][0]["geometries"][0]["rectangle_rotation_expression"] = "0"
        self.output = self.directory / "run"

    def simulate_comsol(self, command, *, cwd, log, timeout):
        """Use real normalization/rules; simulate only the compiler and batch process."""
        self.assertIsInstance(command, list)
        self.assertTrue(all(isinstance(item, str) for item in command))
        if Path(command[0]).name == "comsolcompile.exe":
            (cwd / "FileInventory.class").write_bytes(b"compiled")
            Path(log).write_text("", encoding="utf-8")
        else:
            self.assertIn("-nosave", command)
            self.assertEqual((cwd / "input.mph").read_bytes(), self.model.read_bytes())
            source = (cwd / "FileInventory.java").read_text(encoding="utf-8")
            loads = re.search(r'inspectFile\("input.mph", (\d+)\)', source).group(1)
            Path(log).write_text(cli.JSON_PREFIX + json.dumps(self.inventory) + "\n"
                                 + cli.VERIFIED_PREFIX + loads + "\n", encoding="utf-8")

    def run_check(self, **options):
        return cli.check_model(self.model, comsol_root=self.comsol, output_dir=self.output, **options)

    def test_snapshot_provenance_and_report_from_unicode_path(self):
        before = self.model.read_bytes()
        with patch.object(cli, "_run", side_effect=self.simulate_comsol):
            report = self.run_check(loads=3)
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["findings"], [])
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["diagnosis_sha256"], cli.sha256(self.output / "diagnosis.json"))
        self.assertEqual(metadata["inventory_sha256"], cli.sha256(self.output / "inventory.json"))
        self.assertEqual(metadata["status"], "completed")
        self.assertEqual(metadata["verified_loads"], 3)
        self.assertEqual(metadata["source"]["sha256"], cli.sha256(self.model))
        self.assertEqual(self.model.read_bytes(), before)
        source = (self.output / "FileInventory.java").read_text(encoding="utf-8")
        self.assertNotIn(str(self.model), source)
        self.assertIn("当前规则未发现问题", (self.output / "report.md").read_text(encoding="utf-8"))
        events = [json.loads(line) for line in (self.output / "progress.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["stage"] for event in events], ["snapshot", "compile", "inventory", "diagnose", "completed"])
        self.assertTrue(all(event["schema_version"] == "check-progress-0.1" for event in events))

    def test_progress_storage_failure_does_not_change_diagnosis(self):
        original_open = Path.open
        def failed_progress(path, *args, **kwargs):
            if path.name == "progress.jsonl":
                raise PermissionError("synthetic telemetry write denial")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", failed_progress), patch.object(cli, "_run", side_effect=self.simulate_comsol):
            report = self.run_check()
        self.assertEqual(report["status"], "checked")
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "completed")
        self.assertIn("telemetry write denial", metadata["progress_error"])

    def test_failed_progress_preserves_actual_failure_stage(self):
        with patch.object(cli, "_run", side_effect=cli.CheckError("synthetic compile failure")), self.assertRaises(cli.CheckError):
            self.run_check()
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["stage"], "compile")
        self.assertEqual(metadata["status"], "failed")
        events = [json.loads(line)["stage"] for line in (self.output / "progress.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events, ["snapshot", "compile", "failed"])

    def test_six_case_reports_preserve_rule_evidence(self):
        manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8"))
        for case in manifest["cases"]:
            with self.subTest(case=case["case_id"]):
                self.inventory = json.loads((ROOT / "data/fixtures/cases" / (case["case_id"] + ".json"))
                                            .read_text(encoding="utf-8-sig"))
                self.output = self.directory / case["case_id"]
                with patch.object(cli, "_run", side_effect=self.simulate_comsol):
                    report = self.run_check()
                self.assertEqual({item["code"] for item in report["findings"]}, set(case["expected_codes"]))
                markdown = (self.output / "report.md").read_text(encoding="utf-8")
                for finding in report["findings"]:
                    self.assertIn(finding["code"], markdown)
                    self.assertIn(cli.ACTIONS[finding["code"]], markdown)

    def test_existing_output_is_preserved_before_launch(self):
        self.output.mkdir()
        existing = self.output / "report.md"
        existing.write_bytes(b"user report")
        with patch.object(cli, "_run") as launch, self.assertRaises(FileExistsError):
            self.run_check()
        launch.assert_not_called()
        self.assertEqual(existing.read_bytes(), b"user report")

    def test_unrepresentable_reynolds_publishes_partial_not_failed_or_clean(self):
        material = self.inventory["components"][0]["materials"][0]
        material["density"]["value"] = 1e300
        inlet = next(item for item in self.inventory["components"][0]["physics"][0]["features"] if item["type"] == "Inlet")
        inlet["evaluated_parameters"]["normal_velocity"]["value"] = 1e100
        with patch.object(cli, "_run", side_effect=self.simulate_comsol):
            report = self.run_check()
        self.assertEqual(report["status"], "partial")
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "completed")
        self.assertEqual(metadata["diagnosis_status"], "partial")
        self.assertEqual(metadata["diagnosis_sha256"], cli.sha256(self.output / "diagnosis.json"))
        self.assertIn("部分检查未完成", (self.output / "report.md").read_text(encoding="utf-8"))
        self.assertEqual(report["findings"][0]["code"], "EVALUATION_UNAVAILABLE")

    def test_lfs_pointer_is_rejected_before_launch(self):
        self.model.write_bytes(cli.LFS_HEADER + b"\noid sha256:mock\nsize 123\n")
        with patch.object(cli, "_run") as launch, self.assertRaisesRegex(cli.CheckError, "LFS pointer"):
            self.run_check()
        launch.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_invalid_options_leave_no_output(self):
        for options in ({"loads": 0}, {"loads": 11}, {"loads": True},
                        {"timeout": float("nan")}, {"timeout": 0},
                        {"reynolds_warning": float("inf")}, {"reynolds_warning": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_check(**options)
        self.assertFalse(self.output.exists())

    def test_missing_comsol_executable_does_not_create_run(self):
        (self.comsol / "bin/win64/comsolbatch.exe").unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_check()
        self.assertFalse(self.output.exists())

    def test_compile_exit_zero_without_class_is_failure(self):
        with patch.object(cli, "_run"), self.assertRaisesRegex(cli.CheckError, "without a compiled driver"):
            self.run_check()
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual((metadata["status"], metadata["stage"]), ("failed", "compile"))
        self.assertFalse((self.output / "diagnosis.json").exists())

    def test_exit_zero_with_missing_or_ambiguous_markers_fails(self):
        payload = cli.JSON_PREFIX + json.dumps(self.inventory) + "\n"
        for index, log in enumerate((payload, payload + cli.VERIFIED_PREFIX + "9\n",
                                     payload + payload + cli.VERIFIED_PREFIX + "1\n",
                                     payload + cli.VERIFIED_PREFIX + "1\n" + cli.VERIFIED_PREFIX + "1\n")):
            self.output = self.directory / f"invalid-markers-{index}"
            def simulate(command, **kwargs):
                self.simulate_comsol(command, **kwargs)
                if Path(command[0]).name == "comsolbatch.exe":
                    Path(kwargs["log"]).write_text(log, encoding="utf-8")
            with self.subTest(index=index), patch.object(cli, "_run", side_effect=simulate), \
                    self.assertRaisesRegex(cli.CheckError, "verification markers"):
                self.run_check()
            self.assertFalse((self.output / "diagnosis.json").exists())

    def test_invalid_json_is_not_published_as_diagnosis(self):
        log = self.directory / "bad.log"
        for payload in ("{", "[]", '{"schema_version":"unknown"}'):
            log.write_text(cli.JSON_PREFIX + payload + "\n" + cli.VERIFIED_PREFIX + "1\n", encoding="utf-8")
            with self.subTest(payload=payload), self.assertRaisesRegex(cli.CheckError, "Invalid COMSOL inventory"):
                cli._read_inventory(log, 1)

    def test_changed_input_or_snapshot_cannot_produce_clean_report(self):
        original = self.model.read_bytes()
        for target in ("source", "snapshot"):
            self.model.write_bytes(original)
            self.output = self.directory / target
            def simulate(command, **kwargs):
                self.simulate_comsol(command, **kwargs)
                if Path(command[0]).name == "comsolbatch.exe":
                    path = self.model if target == "source" else kwargs["cwd"] / "input.mph"
                    path.write_bytes(b"changed concurrently")
            with self.subTest(target=target), patch.object(cli, "_run", side_effect=simulate), \
                    self.assertRaisesRegex(cli.CheckError, "hash changed"):
                self.run_check()
            self.assertFalse((self.output / "diagnosis.json").exists())

    def test_unsupported_and_partial_have_explicit_report_states(self):
        original = copy.deepcopy(self.inventory)
        for status in ("unsupported", "partial"):
            self.inventory = copy.deepcopy(original)
            self.output = self.directory / status
            if status == "unsupported":
                self.inventory["studies"][0]["type"] = "Transient"
            else:
                inlet = next(feature for feature in self.inventory["components"][0]["physics"][0]["features"]
                             if feature["type"] == "Inlet")
                inlet["evaluated_parameters"]["normal_velocity"].update(status="unresolved", value=None)
            with patch.object(cli, "_run", side_effect=self.simulate_comsol):
                report = self.run_check()
            self.assertEqual(report["status"], status)
            markdown = (self.output / "report.md").read_text(encoding="utf-8")
            self.assertNotIn("当前规则未发现问题", markdown)

    def test_rotated_rectangle_does_not_use_bounding_box_as_height(self):
        for rotation in ("45[deg]", "90", "theta", None):
            self.inventory["components"][0]["geometries"][0]["rectangle_rotation_expression"] = rotation
            self.output = self.directory / ("rotation-" + str(rotation).replace("[", "").replace("]", ""))
            with self.subTest(rotation=rotation), patch.object(cli, "_run", side_effect=self.simulate_comsol):
                report = self.run_check()
            self.assertEqual(report["status"], "unsupported")
            self.assertIn("非轴对称 API 证据", report["coverage"][0]["reason"])

    def test_explicit_planar_rotation_keeps_boundaries_without_reynolds_height(self):
        geometry = self.inventory["components"][0]["geometries"][0]
        geometry.update(rectangle_rotation_expression="45[deg]", axisymmetric=False)
        with patch.object(cli, "_run", side_effect=self.simulate_comsol):
            report = self.run_check()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["model"]["profile"], "planar-boundaries-v1")
        self.assertNotIn("height_m", report["model"]["geometry"])
        self.assertNotIn("REYNOLDS_RISK", [f["code"] for f in report["findings"]])
        rules = {r["rule_id"]: r for r in report["coverage"][0]["rules"]}
        self.assertEqual(rules["MISSING_INLET"]["status"], "checked")
        self.assertEqual(rules["REYNOLDS_RISK"]["status"], "skipped")

    def test_process_nonzero_exit_includes_local_log(self):
        log = self.directory / "failed-process.log"
        with self.assertRaisesRegex(cli.CheckError, "exit code 7"):
            cli._run([sys.executable, "-c", "raise SystemExit(7)"],
                     cwd=self.directory, log=log, timeout=10)

    def test_timed_out_process_is_stopped(self):
        with patch.object(cli, "_stop_process", wraps=cli._stop_process) as stop, \
                self.assertRaisesRegex(cli.CheckError, "exceeded"):
            cli._run([sys.executable, "-c", "import time; time.sleep(20)"],
                     cwd=self.directory, log=self.directory / "timeout.log", timeout=0.1)
        self.assertIsNotNone(stop.call_args.args[0].poll())

    def test_cli_bad_input_is_a_nonzero_error_without_traceback(self):
        result = subprocess.run([sys.executable, str(ROOT / "src/flowpilot/check_model.py"),
                                 str(self.directory / "missing.mph"), "--comsol-root", str(self.comsol),
                                 "--output-dir", str(self.output)], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"Check failed", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
