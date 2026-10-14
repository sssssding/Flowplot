"""Portable ranking unit tests use synthetic measurements, not physical acceptance."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import portable_recommend as portable
from flowpilot import recommend as legacy
from flowpilot.benchmark_portable import make_case
from flowpilot.diagnostics import normalize


def sample_data():
    original = legacy.read_json(legacy.DEFAULT_MODEL)["dataset"]
    # Real schema shape, but explicit synthetic timings/metrics below; no local outputs needed in CI.
    diagnostic = normalize(legacy.read_json(ROOT / "data/fixtures/cases/baseline.json"))
    cases = []
    for index, (length,height) in enumerate(((.5,.02),(1.,.05),(2.,.1)), 1):
        m = copy.deepcopy(diagnostic)
        m["geometry"] = {"length_m":length,"height_m":height}
        rows = copy.deepcopy(original["observations"])
        for row in rows:
            row["evidence"]["metrics"] = {"mass_in_kg_m_s": 10*height,"mass_out_kg_m_s":10*height*.9999,
                                           "max_speed_m_s":.015,"wall_interior_speed_m_s":0.,"min_u_m_s":0.,"pressure_drop_pa":.1}
            row["evidence"]["solve_seconds"] = 4. if row["candidate"]["id"]=="strict-2" else 2.
            row["process_seconds"] = 20.
        cases.append(make_case(f"synthetic-{index}",str(index)*64,m,rows,"a"*64))
    return {"schema_version":"solver-transfer-data-0.1","status":"completed","development_only":True,
            "independent_validation":False,"cases":cases}


class PortableTest(unittest.TestCase):
    def setUp(self):
        self.data=sample_data()
        self.target=copy.deepcopy(self.data["cases"][1]["diagnostic_model"])

    def result(self, *, cpus=8, target=None, data=None):
        return portable.rank(portable.fit(data or self.data),target or self.target,"f"*64,logical_cpus=cpus)

    def test_unseen_hash_and_environment_are_not_hard_gates(self):
        result=self.result()
        self.assertEqual(result["status"],"recommended")
        self.assertFalse(result["machine_hash_required"])
        self.assertTrue(result["requires_local_validation"])
        self.assertIsNone(result["absolute_runtime_prediction"])
        self.assertFalse(result["independent_validation"])
        self.assertEqual(result["selected"]["id"],"balanced-2")
        self.assertAlmostEqual(result["ranking"][0]["predicted_relative_runtime"],.5)

    def test_one_cpu_never_suggests_two_threads(self):
        result=self.result(cpus=1)
        self.assertEqual(result["selected"]["threads"],1)
        self.assertTrue(all(r["candidate"]["threads"]==1 for r in result["ranking"]))

    def test_missing_cpu_capacity_abstains(self):
        for value in (0, True, "4", -1):
            self.assertEqual(self.result(cpus=value)["status"],"unavailable")

    def test_intermediate_features_can_match_without_any_file_identity(self):
        target=copy.deepcopy(self.target)
        target["geometry"]={"length_m":.75,"height_m":.035}
        result=self.result(target=target)
        self.assertEqual(result["status"],"recommended")
        self.assertGreater(result["feature_distance"],0)

    def test_outside_geometry_re_or_version_abstains(self):
        for mutation in (lambda m:m["geometry"].update(height_m=.2),
                         lambda m:m["source"].update(comsol_version="COMSOL Multiphysics 6.4"),
                         lambda m:m["boundaries"][0].update(mode="Slip")):
            target=copy.deepcopy(self.target); mutation(target)
            self.assertEqual(self.result(target=target)["status"],"unavailable")

    def test_measurements_are_normalized_per_model_not_in_seconds_across_machines(self):
        expected=self.result()
        changed=copy.deepcopy(self.data)
        for case in changed["cases"]:
            for row in case["observations"]:
                row["evidence"]["solve_seconds"] *= 10
                row["process_seconds"] *= 10
            case["environment_id"]="b"*64
        actual=self.result(data=changed)
        self.assertEqual(actual["ranking"], expected["ranking"])

    def test_duplicate_sources_or_no_feature_diversity_rejected(self):
        for mutation in (lambda d:d["cases"][1].update(source_sha256=d["cases"][0]["source_sha256"]),
                         lambda d:d["cases"].pop(),lambda d:d.update(independent_validation=True)):
            data=copy.deepcopy(self.data); mutation(data)
            with self.assertRaises(ValueError): portable.fit(data)

    def test_forged_features_or_quality_cannot_train(self):
        for mutation in (lambda d:d["cases"][0]["features"].update(reynolds=999),
                         lambda d:d["cases"][0]["observations"][0]["quality"].update(passed=False),
                         lambda d:d["cases"][0]["observations"][0].update(repeat=True)):
            data=copy.deepcopy(self.data); mutation(data)
            with self.assertRaises(ValueError): portable.fit(data)

    def test_bad_reference_blocks_training_not_merely_candidate(self):
        data=copy.deepcopy(self.data)
        case=data["cases"][1]
        row=next(r for r in case["observations"] if r["candidate"]["id"]=="strict-2")
        row["evidence"]["solver_warning"]="unreviewed"
        row["quality"]=portable.solution_checks(row["evidence"],case["reference_metrics"],case["features"])
        with self.assertRaises(ValueError): portable.fit(data)

    def test_bad_candidate_dropped_without_being_promoted(self):
        data=copy.deepcopy(self.data)
        case=data["cases"][1]
        for row in case["observations"]:
            if row["candidate"]["id"]=="balanced-2":
                row["evidence"]["solver_warning"]="warning"
                row["quality"]=portable.solution_checks(row["evidence"],case["reference_metrics"],case["features"])
        self.assertNotIn("balanced-2",[r["candidate"]["id"] for r in self.result(data=data)["ranking"]])

    def test_reference_cannot_be_forged_or_swapped(self):
        data=copy.deepcopy(self.data)
        data["cases"][0]["reference_metrics"]["pressure_drop_pa"] *= 2
        with self.assertRaises(ValueError): portable.fit(data)

    def test_display_does_not_invent_absolute_seconds(self):
        result=self.result()
        text=portable.render(result)
        self.assertIn("相对耗时",text)
        self.assertIn("不是当前电脑的秒数",text)
        self.assertNotIn("预测 2.000s",text)

    def test_shipped_portable_model_has_three_real_geometry_points(self):
        model=legacy.read_json(legacy.DEFAULT_PORTABLE_MODEL)
        cases=portable.validate_data(model["data"])
        self.assertEqual(len(cases),3)
        self.assertEqual(sum(len(c["observations"]) for c in cases),36)
        for case in cases:
            result=portable.rank(model,case["diagnostic_model"],"e"*64,logical_cpus=8)
            self.assertEqual(result["status"],"recommended")
            self.assertTrue(result["requires_local_validation"])

    def test_different_platform_does_not_restore_machine_gate(self):
        from unittest.mock import patch
        with patch("platform.system",return_value="Linux"), patch("os.cpu_count",return_value=2):
            result=portable.rank(portable.fit(self.data),self.target,"e"*64)
        self.assertEqual(result["status"],"recommended")
        self.assertFalse(result["machine_hash_required"])

    def test_known_failed_file_abstains_even_when_features_match_training(self):
        registry=legacy.read_json(ROOT/"data/fixtures/ai_development_registry.json")
        rejected=next(c["source_sha256"] for c in registry["cases"] if c.get("recommendation_blocked"))
        result=portable.rank(portable.fit(self.data),self.target,rejected,logical_cpus=8)
        self.assertEqual(result["status"],"unavailable")
        self.assertIsNone(result["selected"])


if __name__=="__main__": unittest.main()
