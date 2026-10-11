"""Overview uses report evidence only; no COMSOL or Tk initialization."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.diagnostics import diagnose_inventory
from flowpilot.model_overview import build_overview
from flowpilot.desktop import DesktopApp


def inventory(name="baseline"):
    return json.loads((ROOT / f"data/fixtures/cases/{name}.json").read_text(encoding="utf-8-sig"))


class OverviewTest(unittest.TestCase):
    def test_baseline_effective_boundaries_and_units(self):
        result = build_overview(diagnose_inventory(inventory()))
        self.assertTrue(result["available"])
        self.assertEqual(result["coverage"], {"inlet": [1], "outlet": [4], "wall": [2, 3]})
        self.assertIn("1000 kg/m^3", result["text"])
        self.assertIn("0.001 Pa*s", result["text"])
        self.assertIn("x 向尺寸 L：1 m", result["text"])
        self.assertIn("y 向尺寸 H：0.05 m", result["text"])
        self.assertIn("不证明物理正确", result["text"])

    def test_fallback_wall_distinguishes_declared_and_effective(self):
        result = build_overview(diagnose_inventory(inventory()))
        wall = next(item for item in result["boundaries"] if item["role"] == "壁面")
        self.assertEqual(wall["declared"], "1, 2, 3, 4")
        self.assertEqual(wall["effective"], "2, 3")
        self.assertIn("回退壁面", wall["scope"])

    def test_all_six_real_fixture_overviews_available(self):
        for name in ("baseline", "missing_inlet", "missing_outlet", "selection_overlap", "reversed_inlet", "high_reynolds"):
            with self.subTest(name=name):
                self.assertTrue(build_overview(diagnose_inventory(inventory(name)))["available"])

    def test_missing_inlet_shows_empty_coverage_not_guessed_boundary(self):
        result = build_overview(diagnose_inventory(inventory("missing_inlet")))
        self.assertEqual(result["coverage"]["inlet"], [])
        self.assertIn("入口：空选择", result["text"])

    def test_unresolved_parameter_remains_unresolved_not_zero(self):
        data = inventory()
        inlet = next(item for item in data["components"][0]["physics"][0]["features"] if item["type"] == "Inlet")
        inlet["evaluated_parameters"]["normal_velocity"].update(status="unresolved", value=None, expression="u(x)")
        result = build_overview(diagnose_inventory(data))
        self.assertTrue(result["available"])
        self.assertIn("部分检查未完成", result["text"])
        self.assertIn("未求值", result["text"])
        self.assertIn("不能按 0 处理", result["text"])
        self.assertIn("u(x)", result["text"])

    def test_invalid_material_value_is_shown_not_silently_corrected(self):
        data = inventory()
        data["components"][0]["materials"][0]["density"]["value"] = -1
        result = build_overview(diagnose_inventory(data))
        self.assertIn("求值：-1 kg/m^3", result["text"])

    def test_unsupported_report_never_gets_invented_model_details(self):
        result = build_overview({"schema_version": "diagnosis-0.1", "status": "unsupported", "reason": "三维模型"})
        self.assertFalse(result["available"])
        self.assertIsNone(result["coverage"])
        self.assertIn("三维模型", result["text"])

    def test_legacy_missing_model_does_not_get_empty_normal_model(self):
        result = build_overview({"schema_version": "diagnosis-0.1", "status": "checked", "findings": []})
        self.assertFalse(result["available"])
        self.assertIn("不能推测", result["text"])

    def test_malformed_nonfinite_and_profile_mismatch_are_unavailable(self):
        report = diagnose_inventory(inventory())
        for mutation in (lambda data: data["model"]["geometry"].update(height_m=float("nan")),
                         lambda data: data["model"].pop("boundaries"),
                         lambda data: data.update(profile="different-profile"),
                         lambda data: data["model"]["boundaries"][0].update(mode="unsupported")):
            data = copy.deepcopy(report)
            mutation(data)
            self.assertFalse(build_overview(data)["available"])

    def test_null_declared_selection_not_confused_with_empty_selection(self):
        report = diagnose_inventory(inventory())
        report["model"]["boundaries"][0]["declared_boundary_ids"] = None
        result = build_overview(report)
        self.assertEqual(result["boundaries"][0]["declared"], "无法读取")

    def test_overview_does_not_mutate_report_or_evidence(self):
        report = diagnose_inventory(inventory("selection_overlap"))
        before = copy.deepcopy(report)
        build_overview(report)
        self.assertEqual(report, before)

    def test_clearing_result_clears_overview_and_returns_to_findings(self):
        app = DesktopApp.__new__(DesktopApp)
        app.tree, app.set_overview, app.result_tabs, app.findings_tab = Mock(), Mock(), Mock(), Mock()
        app.source, app.report_button, app.folder_button, app.compare_button = Mock(), Mock(), Mock(), Mock()
        app.export_button = Mock()
        app.current_overview = {"stale": True}
        app.tree.get_children.return_value = ()
        app.clear_result()
        self.assertIsNone(app.current_overview)
        app.set_overview.assert_called_once()
        app.result_tabs.select.assert_called_once_with(app.findings_tab)


if __name__ == "__main__":
    unittest.main()
