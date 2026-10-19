"""Callback contract tests, not visible-window or new-user acceptance."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.recommend_ui import RecommendationApp
from flowpilot.check_model import CheckError


class ReportButtonTest(unittest.TestCase):
    def app(self):
        app = RecommendationApp.__new__(RecommendationApp)
        app.artifact_directory = Path("existing-report")
        app._open = Mock()
        app.session = SimpleNamespace(busy=False)
        app.show_result = Mock()
        app.result_tabs = Mock()
        app.ai_tab = object()
        app.clear_result = Mock()
        app.status = Mock()
        return app

    def test_zero_argument_button_opens_current_markdown_without_import_or_inference(self):
        app = self.app()
        with patch("flowpilot.recommend_ui.load_completed_check", side_effect=AssertionError("no import")):
            app.open_report()
        app._open.assert_called_once_with(Path("existing-report/report.md"))
        app.show_result.assert_not_called()

    def test_zero_argument_without_current_report_does_nothing(self):
        app = self.app()
        app.artifact_directory = None
        app.open_report()
        app._open.assert_not_called()

    def test_explicit_directory_keeps_verified_preview_and_never_opens_default_app(self):
        app = self.app()
        loaded = {"synthetic": "verified-reader-return"}
        with patch("flowpilot.recommend_ui.load_completed_check", return_value=loaded) as read:
            app.open_report(Path("new-report"))
        read.assert_called_once_with(Path("new-report"))
        app.show_result.assert_called_once_with(loaded)
        app.result_tabs.select.assert_called_once_with(app.ai_tab)
        app._open.assert_not_called()

    def test_failed_explicit_preview_still_clears_old_results(self):
        app = self.app()
        with patch("flowpilot.recommend_ui.load_completed_check", side_effect=CheckError("synthetic bad report")):
            with self.assertRaises(CheckError):
                app.open_report("bad-report")
        app.clear_result.assert_called_once()
        app._open.assert_not_called()

    def test_busy_explicit_preview_remains_blocked(self):
        app = self.app()
        app.session.busy = True
        with patch("flowpilot.recommend_ui.load_completed_check", side_effect=AssertionError("no read while busy")):
            with self.assertRaises(CheckError):
                app.open_report("other-report")
        app.show_result.assert_not_called()


if __name__ == "__main__":
    unittest.main()
