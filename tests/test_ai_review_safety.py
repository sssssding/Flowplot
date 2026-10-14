"""Report snapshot regression tests; synthetic files, no Tk or COMSOL required."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import recommend as ai
from flowpilot.check_model import CheckError, sha256
from flowpilot.desktop import DesktopApp
from flowpilot.desktop_session import load_completed_check
from flowpilot.diagnostics import normalize, check
from flowpilot.recommend_ui import RecommendationApp


class SnapshotSafetyTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.model = normalize(ai.read_json(ROOT / "data/fixtures/cases/baseline.json"))
        self.source_hash = ai.read_json(ai.MANIFEST)["cases"][0]["sha256"].lower()
        self.publish()

    def publish(self, threshold=2000, *, filename="synthetic.mph"):
        report = {"model": self.model, **check(self.model, reynolds_warning=threshold)}
        (self.directory / "diagnosis.json").write_text(json.dumps(report), encoding="utf-8")
        metadata = {"schema_version": "check-run-0.1", "status": "completed",
                    "source": {"filename": filename, "sha256": self.source_hash},
                    "diagnosis_status": report["status"],
                    "diagnosis_sha256": sha256(self.directory / "diagnosis.json"),
                    "settings": {"reynolds_warning": threshold}}
        (self.directory / "run.json").write_text(json.dumps(metadata), encoding="utf-8")

    def identity(self, loaded):
        return loaded["run_sha256"], loaded["diagnosis_sha256"]

    def app(self):
        app = RecommendationApp.__new__(RecommendationApp)
        app.session = SimpleNamespace(busy=False)
        app.learned_model = ai.DEFAULT_PORTABLE_MODEL
        app.ai_result = None
        app._displayed_report_fingerprints = None
        app.set_ai_text = Mock()
        app.ai_text = object()
        return app

    def show(self, app, loaded):
        def show_parent(snapshot):
            app.current_view = snapshot["view"]
            app.artifact_directory = snapshot["directory"]
        with patch.object(DesktopApp, "show_result", side_effect=show_parent):
            app.show_result(loaded)

    def test_unchanged_snapshot_recommends_and_binds_both_fingerprints(self):
        loaded = load_completed_check(self.directory)
        result = ai.recommend_report(self.directory, expected_fingerprints=self.identity(loaded))
        self.assertEqual(result["status"], "recommended")
        self.assertEqual((result["run_sha256"], result["diagnosis_sha256"]), self.identity(loaded))

    def test_same_model_changed_diagnosis_is_rejected_before_learning_model_read(self):
        loaded = load_completed_check(self.directory)
        self.publish(100)
        self.assertEqual(load_completed_check(self.directory)["metadata"]["source"]["sha256"], self.source_hash)
        with patch.object(ai, "read_regular_file", side_effect=AssertionError("must not read ranker")):
            with self.assertRaisesRegex(CheckError, "重新读取报告"):
                ai.recommend_report(self.directory, expected_fingerprints=self.identity(loaded))

    def test_metadata_only_change_is_rejected_even_when_diagnosis_is_identical(self):
        loaded = load_completed_check(self.directory)
        self.publish(3000)
        self.assertEqual(load_completed_check(self.directory)["diagnosis_sha256"], loaded["diagnosis_sha256"])
        with self.assertRaises(CheckError):
            ai.recommend_report(self.directory, expected_fingerprints=self.identity(loaded))

    def test_rejected_warning_report_also_binds_snapshot_without_reading_ranker(self):
        self.publish(100)
        loaded = load_completed_check(self.directory)
        with patch.object(ai, "read_regular_file", side_effect=AssertionError("must not read ranker")):
            result = ai.recommend_report(self.directory, expected_fingerprints=self.identity(loaded))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual((result["run_sha256"], result["diagnosis_sha256"]), self.identity(loaded))

    def test_initial_display_cannot_mix_old_warning_with_new_clean_recommendation(self):
        self.publish(100)
        warning = load_completed_check(self.directory)
        self.publish()
        app = self.app()
        self.show(app, warning)
        self.assertEqual(app.current_view["items"][0]["code"], "REYNOLDS_RISK")
        self.assertIsNone(app.ai_result)
        self.assertIn("重新读取报告", app.set_ai_text.call_args.args[0])

    def test_manual_refresh_checks_displayed_fingerprints_and_clears_old_ai(self):
        app = self.app()
        self.show(app, load_completed_check(self.directory))
        self.assertEqual(app.ai_result["status"], "recommended")
        self.publish(100)
        app.refresh_recommendation()
        self.assertIsNone(app.ai_result)
        self.assertIn("重新读取报告", app.set_ai_text.call_args.args[0])

    def test_manual_refresh_rejects_metadata_only_change(self):
        app = self.app()
        self.show(app, load_completed_check(self.directory))
        self.publish(filename="renamed.mph")
        app.refresh_recommendation()
        self.assertIsNone(app.ai_result)

    def test_refresh_of_unchanged_snapshot_and_explicit_reread_work(self):
        app = self.app()
        self.show(app, load_completed_check(self.directory))
        app.refresh_recommendation()
        self.assertEqual(app.ai_result["status"], "recommended")
        self.publish(100)
        self.show(app, load_completed_check(self.directory))
        self.assertEqual(app.ai_result["status"], "unavailable")
        self.publish()
        self.show(app, load_completed_check(self.directory))
        self.assertEqual(app.ai_result["status"], "recommended")

    def test_clear_forgets_identity_and_cannot_refresh_old_result(self):
        app = self.app()
        self.show(app, load_completed_check(self.directory))
        with patch.object(DesktopApp, "clear_result"):
            app.clear_result()
        self.assertIsNone(app._displayed_report_fingerprints)
        with patch("flowpilot.recommend_ui.recommend_report", side_effect=AssertionError("no snapshot")):
            app.refresh_recommendation()
        self.assertIsNone(app.ai_result)


if __name__ == "__main__":
    unittest.main()
