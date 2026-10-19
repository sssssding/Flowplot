"""Synthetic consumer contract tests; real COMSOL evidence is verified separately."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import _write_json, render_report, sha256
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop_session import diagnosis_view, load_completed_check
from flowpilot.diagnostics import diagnose_inventory
from flowpilot.engine_fingerprint import engine_fingerprint
from flowpilot.model_overview import build_overview
from flowpilot.portable_recommend import model_features
from flowpilot.recommend import recommend_report
from flowpilot.report_package import export_package


def synthetic_axis_inventory():
    data = json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))
    geometry = data["components"][0]["geometries"][0]
    geometry.update(axisymmetric=True, rectangle_rotation_expression="0", bounding_box=[0, .025, 0, 1], axisymmetric_evidence={
        "read_status": "read", "coordinate_names": ["Rg", "PHIg", "Zg"], "spatial_coordinate_names": ["r", "phi", "z"], "boundaries": [
            {"boundary_id": 1, "domain_ids": [1], "sample_coordinates": [[0, 0], [0, .5], [0, 1]]},
            {"boundary_id": 2, "domain_ids": [1], "sample_coordinates": [[0, 0], [.0125, 0], [.025, 0]]},
            {"boundary_id": 3, "domain_ids": [1], "sample_coordinates": [[0, 1], [.0125, 1], [.025, 1]]},
            {"boundary_id": 4, "domain_ids": [1], "sample_coordinates": [[.025, 0], [.025, .5], [.025, 1]]}]})
    features = data["components"][0]["physics"][0]["features"]
    for feature in features:
        if feature["type"] in {"Inlet", "Outlet", "Wall", "WallBC"}:
            entity = {"Inlet": 2, "Outlet": 3, "Wall": 4, "WallBC": 4}[feature["type"]]
            feature.update(selected_entity_ids=[entity], declared_entity_ids=[entity])
    features.append({"tag": "axi1", "label": "测试轴线", "type": "AxialSymmetry", "enabled": True,
                     "selection_dimensions": [1], "selected_entity_ids": [1], "declared_entity_ids": [1, 2, 3, 4],
                     "named_selection": "", "child_feature_count": 0, "parameters": {}, "evaluated_parameters": {}})
    return data


class AxisConsumerTest(unittest.TestCase):
    def setUp(self):
        self.inventory = synthetic_axis_inventory()

    def report(self):
        return diagnose_inventory(self.inventory)

    def write_run(self, path, report):
        path.mkdir()
        _write_json(path / "diagnosis.json", report)
        metadata = {"schema_version": "check-run-0.1", "status": "completed", "diagnosis_status": report["status"],
                    "source": {"filename": "synthetic-axis.mph", "sha256": "1" * 64},
                    "diagnosis_sha256": sha256(path / "diagnosis.json"), "rule_engine_sha256": engine_fingerprint(),
                    "inventory_source_sha256": "2" * 64, "comsol_version": "COMSOL Multiphysics 6.3 test-only",
                    "verified_loads": 1, "settings": {"reynolds_warning": 2000}}
        _write_json(path / "run.json", metadata)
        return metadata

    def test_axis_coordinates_and_managed_axis_selection(self):
        report = self.report()
        self.assertEqual(report["status"], "checked")
        before = copy.deepcopy(report)
        overview = build_overview(report)
        self.assertTrue(overview["available"])
        self.assertEqual(overview["coverage"], {"inlet": [2], "outlet": [3], "wall": [4], "axis": [1]})
        self.assertIn("径向 r：[0, 0.025]", overview["text"])
        self.assertIn("轴向 z：[0, 1]", overview["text"])
        self.assertIn("已核验圆管直径 D：0.05 m", overview["text"])
        axis = next(item for item in overview["boundaries"] if item["tag"] == "axi1")
        self.assertEqual((axis["declared"], axis["effective"]), ("1, 2, 3, 4", "1"))
        self.assertIn("回退轴线", axis["scope"])
        self.assertEqual(report, before)

    def test_unverified_mode_and_unread_selection_are_displayed_honestly(self):
        inlet = next(f for f in self.inventory["components"][0]["physics"][0]["features"] if f["type"] == "Inlet")
        inlet["parameters"]["BoundaryCondition"] = "UnsupportedTestMode"
        inlet["selected_entity_ids"] = None
        report = self.report()
        overview = build_overview(report)
        self.assertEqual(report["status"], "partial")
        self.assertTrue(overview["available"])
        self.assertIsNone(overview["coverage"]["inlet"])
        self.assertIn("UnsupportedTestMode（未核验模式", overview["text"])
        self.assertIn("入口：无法读取", overview["text"])
        self.assertIn("封闭或未核验", overview["text"])

    def test_missing_topology_does_not_invent_diameter_or_axis(self):
        self.inventory["components"][0]["geometries"][0].pop("axisymmetric_evidence")
        overview = build_overview(self.report())
        self.assertTrue(overview["available"])
        self.assertIn("圆管直径：未核验，不从包围盒推定", overview["text"])
        self.assertIn("r = 0 轴线边界：无法读取", overview["text"])

    def test_axis_findings_show_source_nodes_entities_and_action(self):
        axis = next(f for f in self.inventory["components"][0]["physics"][0]["features"] if f["type"] == "AxialSymmetry")
        axis.update(selected_entity_ids=[4], declared_entity_ids=[4])
        report = self.report()
        items = diagnosis_view(report)["items"]
        item = next(item for item in items if item["code"] == "AXIS_SELECTION_INCONSISTENT" and item["nodes"] == "axi1")
        self.assertEqual(item["title"], "轴线选择不一致")
        self.assertEqual(item["boundaries"], "4")
        self.assertIn("COMSOL 定位：comp1 / geom1 / spf", item["detail"])
        self.assertIn("相关节点：axi1", item["detail"])
        self.assertIn("建议：在对应组件和几何中核对 r = 0", item["detail"])

    def test_export_import_compare_and_recommendation_boundaries(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
            directory = Path(temporary)
            report = self.report()
            metadata = self.write_run(directory / "axis", report)
            package = export_package(directory / "axis", directory / "package")
            self.assertEqual(load_completed_check(package)["report"], report)
            self.assertIn("径向 r", (package / "overview.txt").read_text(encoding="utf-8"))
            self.assertEqual(compare_reports(directory / "axis", package)["status"], "compared")
            result = recommend_report(package, directory / "must-not-load-learned-model.json")
            self.assertEqual(result["status"], "unavailable")
            self.assertIn("原二维矩形", result["reason"])
            self.assertEqual(result["ranking"], [])
            legacy_envelope = {"schema_version": "diagnosis-0.1", "status": "checked", "findings": [],
                               "model": report["model"], "profile": report["profile"]}
            self.write_run(directory / "legacy_axis", legacy_envelope)
            self.assertEqual(recommend_report(directory / "legacy_axis", directory / "must-not-load.json")["status"], "unavailable")
            with self.assertRaisesRegex(ValueError, "rectangle profile"):
                model_features(report["model"])
            planar = diagnose_inventory(json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig")))
            self.write_run(directory / "planar", planar)
            comparison = compare_reports(directory / "planar", directory / "axis")
            self.assertEqual(comparison["status"], "not_comparable")
            self.assertIn("两份报告的检查模板不同。", comparison["blocking_reasons"])
            markdown = render_report(report, metadata)
            self.assertIn("轴对称", markdown)
            self.assertNotIn("以通道高度 H 计算", markdown)


if __name__ == "__main__":
    unittest.main()
