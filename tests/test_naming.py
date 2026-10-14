"""Display-name migration and legacy entry compatibility; no physical acceptance."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from branding_evidence import BRANDING_ONLY_SOURCES, historical_digest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import render_report


class NamingTest(unittest.TestCase):
    def test_visible_python_literals_use_current_application_name(self):
        names = BRANDING_ONLY_SOURCES | {"src/flowpilot/acceptance_result.py", "src/flowpilot/acceptance_bundle.py"}
        for name in names:
            with self.subTest(source=name):
                tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
                strings = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
                self.assertTrue(any("FlowPlot" in value for value in strings))
                self.assertFalse(any("FlowPilot" in value for value in strings))

    def test_entrypoints_have_identical_behavior_and_legacy_file_is_unchanged(self):
        legacy = (ROOT / "FlowPilot.cmd").read_bytes()
        self.assertEqual((ROOT / "FlowPlot.cmd").read_bytes(), legacy)
        self.assertNotIn(b"\r", legacy)
        stored = json.loads((ROOT / "data/fixtures/desktop_visible_review.json").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(legacy).hexdigest(), stored["source_sha256"]["FlowPilot.cmd"])

    @unittest.skipUnless(sys.platform == "win32", "Windows .cmd entrypoint check")
    def test_both_windows_entrypoints_work_from_another_directory(self):
        environment = dict(os.environ, FLOWPILOT_PYTHON=sys.executable, FLOWPILOT_NO_PAUSE="1")
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            for option in ("--check-env", "--help"):
                results = []
                for name in ("FlowPlot.cmd", "FlowPilot.cmd"):
                    command = f'""{ROOT / name}" {option}"'
                    # A raw command line avoids list2cmdline escaping cmd.exe's /s /c quotes.
                    executable = subprocess.list2cmdline([os.environ.get("COMSPEC", "cmd.exe")])
                    result = subprocess.run(executable + " /d /s /c " + command,
                        cwd=directory, env=environment, capture_output=True, encoding="utf-8", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("FlowPlot", result.stdout)
                    self.assertNotIn("FlowPilot", result.stdout)
                    results.append((result.returncode, result.stdout, result.stderr))
                self.assertEqual(results[0], results[1])

    def test_historical_guard_allows_only_the_name_not_unrelated_edits(self):
        stored = json.loads((ROOT / "data/fixtures/desktop_visible_review.json").read_text(encoding="utf-8"))
        for name in ("src/flowpilot/desktop.py", "src/flowpilot/launcher.py"):
            raw = (ROOT / name).read_bytes()
            expected = stored["source_sha256"][name]
            self.assertNotEqual(hashlib.sha256(raw).hexdigest(), expected)
            self.assertEqual(historical_digest(name, raw), expected)
            self.assertNotEqual(historical_digest(name, raw + b"\n# unrelated change\n"), expected)
        # Non-allowlisted sources are never normalized by the historical guard.
        raw = b"FlowPlot"
        self.assertEqual(historical_digest("other.py", raw), hashlib.sha256(raw).hexdigest())

    def test_report_title_changes_without_changing_diagnosis(self):
        report = {"schema_version": "diagnosis-0.1", "status": "checked", "findings": []}
        before = json.dumps(report, sort_keys=True)
        metadata = {"source": {"filename": "synthetic.mph", "sha256": "0" * 64},
                    "comsol_version": "synthetic; no COMSOL execution", "verified_loads": 2,
                    "settings": {"reynolds_warning": 2000}}
        rendered = render_report(report, metadata)
        self.assertTrue(rendered.startswith("# FlowPlot 检查报告"))
        self.assertNotIn("FlowPilot", rendered)
        self.assertEqual(json.dumps(report, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
