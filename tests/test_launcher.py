"""Launcher fault injection, not visible UI or real COMSOL acceptance."""
from contextlib import redirect_stderr, redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import launcher


class LauncherTest(unittest.TestCase):
    def ready(self):
        return [{"name": "python", "status": "ok", "version": "test"},
                {"name": "jsonschema", "status": "ok", "version": "test"},
                {"name": "tkinter", "status": "ok", "version": "test"},
                {"name": "comsol", "status": "warning"}]

    def invoke(self, arguments, checks=None, result=0, error=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(launcher, "check_environment", return_value=checks or self.ready()), \
                patch.object(launcher.subprocess, "run", return_value=Mock(returncode=result), side_effect=error) as runner, \
                redirect_stdout(output), redirect_stderr(errors):
            code = launcher.launch(arguments)
        return code, output.getvalue(), errors.getvalue(), runner

    def test_environment_only_does_not_open_window(self):
        code, output, errors, runner = self.invoke(["--check-env"])
        self.assertEqual(code, 0)
        self.assertIn("no window or COMSOL", output)
        self.assertEqual(errors, "")
        runner.assert_not_called()

    def test_missing_jsonschema_gives_actionable_error_without_installing(self):
        checks = self.ready()
        checks[1]["status"] = "error"
        code, output, errors, runner = self.invoke([], checks)
        self.assertEqual(code, 1)
        self.assertIn("requirements-dev.txt", errors)
        self.assertIn("FLOWPILOT_PYTHON", errors)
        self.assertNotIn("Traceback", errors)
        runner.assert_not_called()

    def test_missing_tk_blocks_launch(self):
        checks = self.ready()
        checks[2]["status"] = "error"
        code, _, errors, runner = self.invoke([], checks)
        self.assertEqual(code, 1)
        self.assertIn("Tcl/Tk", errors)
        runner.assert_not_called()

    def test_desktop_arguments_are_literal_and_same_interpreter(self):
        arguments = ["--model", "模型 with spaces & punctuation.mph", "--comsol-root", "COMSOL with spaces"]
        code, _, _, runner = self.invoke(arguments)
        self.assertEqual(code, 0)
        runner.assert_called_once_with([sys.executable, "-X", "utf8", str(launcher.DESKTOP), *arguments],
                                       cwd=ROOT, check=False)

    def test_desktop_failure_code_propagates(self):
        self.assertEqual(self.invoke([], result=7)[0], 7)

    def test_launch_failure_is_reported(self):
        code, _, errors, runner = self.invoke([], error=OSError("synthetic process failure"))
        self.assertEqual(code, 1)
        self.assertIn("could not launch", errors)
        runner.assert_called_once()

    def test_unverified_python_is_warning_not_fake_license_validation(self):
        checks = self.ready()
        checks[0]["status"] = "warning"
        code, output, _, runner = self.invoke(["--check-env"], checks)
        self.assertEqual(code, 0)
        self.assertIn("python: warning", output)
        self.assertIn("does not validate", output)
        runner.assert_not_called()

    def test_versioned_visible_review_keeps_acceptance_boundaries_and_sources(self):
        stored = json.loads((ROOT / "data/fixtures/desktop_visible_review.json").read_text(encoding="utf-8"))
        self.assertTrue(stored["visual_review"])
        self.assertEqual(stored["reviewer_kind"], "coding_agent")
        for key in ("new_user_timing_validated", "expert_review", "comsol_gui_settings_reviewed", "model_solver_run"):
            self.assertFalse(stored[key])
        self.assertEqual(stored["unseen_models_validated"], 0)
        self.assertTrue(stored["original_local_model_unchanged"])
        self.assertEqual(set(stored["source_sha256"]), {"FlowPilot.cmd", "src/flowpilot/desktop.py", "src/flowpilot/launcher.py"})
        for name, expected in stored["source_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
