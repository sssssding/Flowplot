"""Synthetic numeric edge cases, not COMSOL or independent physics acceptance."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import check_model, render_report, sha256
from flowpilot.check_suite import evaluate_dataset, run_suite, validate_manifest
from flowpilot.compare_reports import compare_reports
from flowpilot.desktop_session import DesktopSession, diagnosis_view, load_completed_check
from flowpilot.diagnostics import check, diagnose_inventory, is_finite_number, normalize
from flowpilot.model_overview import build_overview
from flowpilot.report_package import export_package


class NumericSafetyTest(unittest.TestCase):
    def setUp(self):
        self.inventory = json.loads((ROOT / "data/fixtures/cases/baseline.json").read_text(encoding="utf-8-sig"))
        self.base = normalize(self.inventory)
        self.manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8-sig"))

    def model(self, *, rho=1, speed=1, height=1, mu=1):
        model = copy.deepcopy(self.base)
        for key, value in (("density", rho), ("dynamic_viscosity", mu)):
            model["material"][key].update(value=value, expression=str(value))
        model["geometry"]["height_m"] = height
        inlet = next(item for item in model["boundaries"] if item["type"] == "inlet")
        inlet["parameters"]["normal_velocity"].update(value=speed, expression=str(speed))
        return model

    def report(self, **options):
        model = self.model(**options)
        return {"model": model, **check(model)}

    def test_intermediate_underflow_no_longer_hides_large_reynolds(self):
        report = self.report(rho=1e-200, speed=1e-200, height=1e200, mu=1e-210)
        self.assertEqual(report["status"], "checked")
        self.assertEqual([item["code"] for item in report["findings"]], ["REYNOLDS_RISK"])
        self.assertEqual(report["findings"][0]["evidence"]["reynolds_height_based"], 1e10)

    def test_intermediate_overflow_no_longer_invents_risk_or_infinity(self):
        report = self.report(rho=1e200, speed=1e200, height=1e-200, mu=1e200)
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["findings"], [])  # Final Re is 1, not infinity.
        json.dumps(report, allow_nan=False)

    def test_final_overflow_is_explicit_partial_with_operand_evidence(self):
        report = self.report(rho=1e300, speed=1e100, height=1, mu=1)
        self.assertEqual(report["status"], "partial")
        self.assertEqual([item["code"] for item in report["findings"]], ["EVALUATION_UNAVAILABLE"])
        finding = report["findings"][0]
        self.assertEqual(finding["feature_tags"], ["inl1"])
        self.assertEqual(finding["boundary_ids"], [1])
        self.assertEqual(finding["evidence"]["reason"], "above_float_range")
        self.assertEqual(finding["evidence"]["density_kg_m3"], 1e300)
        self.assertEqual(finding["evidence"]["quantity"], "reynolds_height_based")
        self.assertNotIn("reynolds_height_based", finding["evidence"])
        json.dumps(report, allow_nan=False)

    def test_final_nonzero_underflow_is_partial_not_zero(self):
        report = self.report(rho=1e-300, speed=1e-100)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["findings"][0]["evidence"]["reason"], "below_nonzero_float_range")
        self.assertNotIn("INLET_DIRECTION", [item["code"] for item in report["findings"]])
        json.dumps(report, allow_nan=False)

    def test_true_zero_velocity_is_not_numerically_unavailable(self):
        report = self.report(rho=1e300, speed=0, height=1e300, mu=1e-300)
        self.assertEqual(report["status"], "checked")
        self.assertEqual([item["code"] for item in report["findings"]], ["INLET_DIRECTION"])

    def test_negative_speed_keeps_direction_warning_when_re_is_unavailable(self):
        report = self.report(rho=1e300, speed=-1e100)
        self.assertEqual(report["status"], "partial")
        self.assertEqual({item["code"] for item in report["findings"]}, {"INLET_DIRECTION", "EVALUATION_UNAVAILABLE"})

    def test_representable_subnormal_value_is_not_discarded(self):
        report = self.report(speed=5e-324)
        self.assertEqual(report["status"], "checked")
        self.assertEqual(report["findings"], [])

    def test_largest_finite_float_is_reportable(self):
        report = self.report(rho=sys.float_info.max)
        evidence = report["findings"][0]["evidence"]
        self.assertEqual(evidence["reynolds_height_based"], sys.float_info.max)
        json.dumps(report, allow_nan=False)

    def test_guarded_threshold_and_decimal_cancellation(self):
        for speed, expected in ((math.nextafter(2000, 0), False), (2000, False),
                                (math.nextafter(2000, math.inf), False), (2001, True)):
            with self.subTest(speed=speed):
                report = self.report(speed=speed)
                self.assertEqual(bool(report["findings"]), expected)
        report = self.report(rho=1000, speed=0.04, height=0.05, mu=0.001)
        self.assertEqual(report["findings"], [])  # Recorded decimal values yield exactly Re=2000.

    def test_actual_comsol_geometry_last_digit_does_not_trigger_threshold(self):
        report = self.report(rho=1000, speed=.04, height=.05000000000000001, mu=.001)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["numeric_policy"], {"reynolds_threshold_guard_ulps": 4})
        self.assertEqual(report["model"]["geometry"]["height_m"], .05000000000000001)

    def test_exact_guard_edge_and_next_representable_value(self):
        threshold = 2000.
        for steps in range(1, 7):
            speed = threshold
            for _ in range(steps):
                speed = math.nextafter(speed, math.inf)
            report = self.report(speed=speed)
            self.assertEqual(bool(report["findings"]), steps > 4)

    def test_threshold_guard_uses_configured_scale_and_remains_finite(self):
        for threshold in (1e-200, 1., 2000., 1e200, sys.float_info.max):
            with self.subTest(threshold=threshold):
                value = math.nextafter(threshold, 0)
                report = check(self.model(speed=value), reynolds_warning=threshold)
                self.assertEqual(report["findings"], [])
                json.dumps(report, allow_nan=False)
                if threshold != sys.float_info.max:
                    report = check(self.model(speed=threshold * 1.001), reynolds_warning=threshold)
                    self.assertEqual(report["findings"][0]["code"], "REYNOLDS_RISK")
                    self.assertEqual(report["findings"][0]["evidence"]["numerical_comparison_margin"],
                                     4 * math.ulp(threshold))

    def test_smallest_threshold_guard_is_explicit_not_relative_tolerance(self):
        threshold = math.ulp(0.)
        for speed, risk in ((5 * threshold, False), (6 * threshold, True)):
            report = check(self.model(speed=speed), reynolds_warning=threshold)
            self.assertEqual(bool(report["findings"]), risk)

    def test_factor_rescaling_preserves_nominal_reynolds(self):
        for exponent in (-300, -200, -150, 0, 150, 200, 300):
            with self.subTest(exponent=exponent):
                report = self.report(rho=float(f"1e{exponent}"), speed=float(f"1e{-exponent}"), mu=1e-4)
                self.assertEqual(report["status"], "checked")
                self.assertEqual(report["findings"][0]["evidence"]["reynolds_height_based"], 10000)

    def test_invalid_material_still_skips_reynolds_instead_of_dividing(self):
        for mu in (0, -1e-300):
            report = self.report(rho=1e300, speed=1e300, mu=mu)
            self.assertEqual([item["code"] for item in report["findings"]], ["INVALID_MATERIAL_PARAMETER"])

    def test_oversized_integer_evidence_is_rejected_without_overflow_exception(self):
        for field in ("density", "dynamic_viscosity"):
            model = self.model()
            model["material"][field]["value"] = 10 ** 400
            with self.assertRaisesRegex(ValueError, "finite float"):
                check(model)
            report = {"schema_version": "diagnosis-0.1", "status": "checked", "profile": model["profile"], "model": model}
            self.assertFalse(build_overview(report)["available"])

    def test_derived_geometry_overflow_is_not_a_supported_model(self):
        self.inventory["components"][0]["geometries"][0]["bounding_box"] = [-1e308, 1e308, 0, 0.05]
        report = diagnose_inventory(self.inventory)
        self.assertEqual(report["status"], "unsupported")
        self.assertIn("有限", report["reason"])

    def test_invalid_numeric_options_are_consistent_across_launchers(self):
        for value in (True, "2000", 10 ** 400, math.inf, math.nan, 0, -1):
            with self.subTest(value=str(value)[:20]):
                with self.assertRaises(ValueError):
                    check(self.model(), reynolds_warning=value)
                with self.assertRaises(ValueError):
                    check_model("unused", comsol_root="unused", output_dir="unused", reynolds_warning=value)
                with self.assertRaises(ValueError):
                    DesktopSession().start("unused", "unused", "unused", timeout=value)
                with self.assertRaises(ValueError):
                    run_suite("unused", output_dir="unused", timeout=value)
                manifest = copy.deepcopy(self.manifest)
                manifest["reynolds_warning"] = value
                with self.assertRaises(ValueError):
                    validate_manifest(manifest)

    def test_finite_number_excludes_bool_and_unrepresentable_integer(self):
        for value in (False, True, None, "1", 10 ** 400, math.inf, math.nan):
            self.assertFalse(is_finite_number(value))
        for value in (0, -1, sys.float_info.max, 5e-324, 10 ** 300):
            self.assertTrue(is_finite_number(value))

    def test_partial_numeric_report_renders_and_is_not_scored_as_clean(self):
        report = self.report(rho=1e300, speed=1e100)
        metadata = {"source": {"filename": "synthetic.mph", "sha256": "1" * 64},
                    "comsol_version": "synthetic-no-COMSOL-run", "verified_loads": 1,
                    "settings": {"reynolds_warning": 2000}}
        self.assertIn("部分检查未完成", render_report(report, metadata))
        self.assertEqual(diagnosis_view(report)["tone"], "incomplete")
        self.assertIn("无法表示的派生量", build_overview(report)["text"])
        outcomes = {case["case_id"]: {"status": "checked", "predicted_codes": case["expected_codes"]}
                    for case in self.manifest["cases"]}
        outcomes["baseline"] = {"status": "partial", "predicted_codes": ["EVALUATION_UNAVAILABLE"]}
        summary = evaluate_dataset(self.manifest, outcomes)
        self.assertEqual(summary["checked_cases"], 5)
        self.assertIsNone(summary["cases"][0]["predicted_codes"])
        self.assertIsNone(summary["meets_recall_above_90_percent"])

    def test_invalid_comparison_threshold_blocks_and_export_does_not_invent_it(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            report = self.report()
            (source / "diagnosis.json").write_text(json.dumps(report), encoding="utf-8")
            metadata = {"schema_version": "check-run-0.1", "status": "completed", "diagnosis_status": "checked",
                        "source": {"filename": "synthetic.mph", "sha256": "1" * 64},
                        "diagnosis_sha256": sha256(source / "diagnosis.json"),
                        "rule_engine_sha256": "2" * 64, "inventory_source_sha256": "3" * 64,
                        "comsol_version": "synthetic", "settings": {"reynolds_warning": 10 ** 400}}
            (source / "run.json").write_text(json.dumps(metadata), encoding="utf-8")
            self.assertEqual(compare_reports(source, source)["status"], "not_comparable")
            exported = export_package(source, Path(temporary) / "exported")
            self.assertNotIn("settings", load_completed_check(exported)["metadata"])

    def test_numeric_checks_preserve_input_and_are_repeatable(self):
        model = self.model(rho=1e-200, speed=1e-200, height=1e200, mu=1e-210)
        before = copy.deepcopy(model)
        first = check(model)
        for _ in range(5):
            self.assertEqual(check(model), first)
        self.assertEqual(model, before)


if __name__ == "__main__":
    unittest.main()
