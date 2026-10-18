"""M0 report consumers preserve history and expose incomplete coverage."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import CheckError, render_report, sha256
from flowpilot.check_suite import read_outcome
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop_session import diagnosis_view, load_completed_check
from flowpilot.diagnostics import diagnose_inventory
from flowpilot.engine_fingerprint import ENGINE_SOURCES, engine_fingerprint
from flowpilot.model_overview import build_overview
from flowpilot.recommend import recommend_report
from flowpilot.report_package import export_package


class M0ReportCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inventory = json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))

    def save(self, report, name="report", digest=None):
        directory = self.root / name
        directory.mkdir()
        (directory / "diagnosis.json").write_text(json.dumps(report), encoding="utf-8")
        metadata = {"schema_version": "check-run-0.1", "status": "completed",
                    "diagnosis_status": report["status"], "diagnosis_sha256": sha256(directory / "diagnosis.json"),
                    "source": {"filename": "test.mph", "sha256": "1" * 64},
                    "rule_engine_sha256": digest or engine_fingerprint(),
                    "inventory_source_sha256": sha256(ROOT / "src/comsol/ModelInventory.java"),
                    "settings": {"reynolds_warning": 2000}, "verified_loads": 1, "comsol_version": "6.3"}
        (directory / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
        return directory, metadata

    def test_historical_report_is_not_upgraded_or_given_coverage(self):
        old = {"schema_version": "diagnosis-0.1", "status": "checked", "findings": []}
        directory, _ = self.save(old)
        loaded = load_completed_check(directory)
        self.assertEqual(loaded["report"], old)
        self.assertIsNone(loaded["view"]["coverage"])
        self.assertNotIn("检查覆盖", loaded["view"]["detail"])

    def test_partial_empty_findings_visible_in_every_export_consumer(self):
        self.inventory["components"].append({"tag": "comp2", "physics": [{"tag": "es", "type": "Electrostatics", "enabled": True}]})
        report = diagnose_inventory(self.inventory)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["findings"], [])
        directory, metadata = self.save(report)
        loaded = load_completed_check(directory)
        self.assertEqual(loaded["view"]["tone"], "incomplete")
        self.assertIn("检查覆盖", loaded["view"]["detail"])
        self.assertIn("检查覆盖", build_overview(report)["text"])
        markdown = render_report(report, metadata)
        self.assertNotIn("当前规则未发现问题。", markdown)
        self.assertIn("unsupported", markdown)
        package = export_package(directory, self.root / "export")
        self.assertEqual(load_completed_check(package)["report"], report)
        self.assertIn("检查覆盖", (package / "report.md").read_text(encoding="utf-8"))
        comparison = compare_reports(directory, package)
        self.assertEqual(comparison["status"], "not_comparable")
        result = read_outcome(directory, {"sha256": "1" * 64}, 2000)
        self.assertEqual(result["status"], "partial")
        with patch("flowpilot.recommend.read_regular_file", side_effect=AssertionError("No learner should load")):
            self.assertEqual(recommend_report(directory)["status"], "unavailable")

    def test_new_report_is_strict_and_requires_engine_provenance(self):
        report = diagnose_inventory(self.inventory)
        malformed = copy.deepcopy(report)
        malformed.pop("coverage")
        with self.assertRaises(CheckError):
            diagnosis_view(malformed)
        directory, metadata = self.save(report)
        metadata.pop("rule_engine_sha256")
        (directory / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises(CheckError):
            load_completed_check(directory)

    def test_checked_single_flow_keeps_original_recommendation_scope(self):
        report = diagnose_inventory(self.inventory)
        directory, _ = self.save(report)
        learned = self.root / "learned.json"
        learned.write_text(json.dumps({"schema_version": "solver-ranker-0.2"}), encoding="utf-8")
        expected = {"status": "recommended", "selected": "safe-test-candidate"}
        with patch("flowpilot.portable_recommend.rank", return_value=expected) as ranker:
            result = recommend_report(directory, learned)
        self.assertEqual(result["status"], "recommended")
        self.assertEqual(ranker.call_args.args[1], report["model"])

    def test_different_contracts_are_not_comparable_even_with_same_engine_hash(self):
        report = diagnose_inventory(self.inventory)
        modern, _ = self.save(report)
        legacy = {"schema_version": "diagnosis-0.1", "status": "checked", "findings": [],
                  "profile": report["profile"]}
        old, _ = self.save(legacy, name="old")
        result = compare_reports(old, modern)
        self.assertEqual(result["status"], "not_comparable")
        self.assertTrue(any("契约" in reason for reason in result["blocking_reasons"]))

    def test_every_engine_module_and_schema_changes_fingerprint(self):
        for name in ENGINE_SOURCES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        initial = engine_fingerprint(self.root)
        for name in ENGINE_SOURCES:
            target = self.root / name
            original = target.read_bytes()
            target.write_bytes(original + b"\n")
            self.assertNotEqual(initial, engine_fingerprint(self.root), name)
            target.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
