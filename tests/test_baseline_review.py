"""Review-data validation; synthetic samples/mocked exports are not COMSOL evidence."""
import copy
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import review_baseline as review


class BaselineReviewTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.reference = json.loads(review.REFERENCE.read_text(encoding="utf-8-sig"))["runs"][0]
        self.payload = {"schema_version": "baseline-review-0.1", "solver_run": False,
                        "comsol_version": "COMSOL 6.3.0.290", "height_m": 0.05, "inlet_velocity_m_s": 0.01,
                        "metrics": {key: self.reference[key] for key in review.METRICS}, "sections": []}
        for x in review.SECTIONS:
            y = [0.05 * i / 100 for i in range(101)]
            u = [0.014 * 4 * (i / 100) * (1 - i / 100) for i in range(101)]
            self.payload["sections"].append({"x_m": x, "y_m": y, "u_m_s": u, "speed_m_s": u[:],
                                              "v_m_s": [0.0] * 101, "pressure_pa": [0.07 * (1-x)] * 101})
        self.model = self.directory / "baseline copy.mph"
        self.model.write_bytes(b"synthetic model bytes for an offline orchestration test")
        self.manifest = self.directory / "manifest.json"
        self.manifest.write_text(json.dumps({"cases": [{"case_id": "baseline", "model_path": str(self.model),
                                                        "sha256": review.sha256(self.model)}]}), encoding="utf-8")
        self.comsol = self.directory / "COMSOL"
        binaries = self.comsol / "bin/win64"
        binaries.mkdir(parents=True)
        for name in ("comsolcompile.exe", "comsolbatch.exe"):
            (binaries / name).touch()
        self.output = self.directory / "run"

    def simulate(self, command, *, cwd, log, timeout):
        if Path(command[0]).name == "comsolcompile.exe":
            (cwd / "BaselineReview.class").write_bytes(b"compiled")
            Path(log).touch()
        else:
            self.assertIn("-nosave", command)
            self.assertIn("-graphics", command)
            Path(log).write_text("FLOWPILOT_REVIEW_JSON " + json.dumps(self.payload)
                                 + "\nFLOWPILOT_REVIEW_VERIFIED\n", encoding="utf-8")
            # Header fixtures test export validation only, not actual image generation.
            for name, size in (("velocity.png", (1600, 400)), ("profiles.png", (1200, 800))):
                (cwd / name).write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13)
                                         + b"IHDR" + struct.pack(">II", *size))
            (cwd / "baseline_with_review_plots.mph").write_bytes(b"mock review model" * 20)

    def run_review(self):
        with patch.object(review, "MANIFEST", self.manifest), patch.object(review, "_run", side_effect=self.simulate):
            return review.review_baseline(comsol_root=self.comsol, output_dir=self.output)

    def test_reference_checks_never_grant_expert_approval(self):
        result = review.analyze_samples(self.payload, self.reference)
        self.assertTrue(result["engineering_checks_passed"])
        self.assertEqual(result["review_status"], "expert_review_pending")
        self.assertFalse(result["solver_run"])
        self.assertAlmostEqual(result["metrics"]["mass_relative_error"], self.reference["mass_relative_error"])

    def test_versioned_real_samples_recompute_the_recorded_review(self):
        payload = json.loads((ROOT / "data/fixtures/baseline_review_samples.json").read_text(encoding="utf-8"))
        stored = json.loads((ROOT / "data/fixtures/baseline_review.json").read_text(encoding="utf-8"))
        computed = review.analyze_samples(payload, self.reference)
        for key in ("metrics", "reference_match", "engineering_checks", "sections", "review_status"):
            self.assertEqual(computed[key], stored[key])
        manifest = json.loads((ROOT / "data/fixtures/cases/manifest.json").read_text(encoding="utf-8"))
        baseline = next(case for case in manifest["cases"] if case["case_id"] == "baseline")
        self.assertEqual(payload["source"]["sha256"].lower(), baseline["sha256"].lower())
        self.assertEqual(stored["source"], payload["source"])
        review._verify_png(ROOT / "docs/assets/baseline_velocity.png", (1600, 400))
        review._verify_png(ROOT / "docs/assets/baseline_profiles.png", (1200, 800))

    def test_reference_drift_is_reported(self):
        self.payload["metrics"]["pressure_drop_pa"] *= 1.01
        result = review.analyze_samples(self.payload, self.reference)
        self.assertFalse(result["engineering_checks_passed"])
        self.assertFalse(result["reference_match"]["pressure_drop_pa"])

    def test_reverse_flow_or_bad_walls_fail_engineering_checks(self):
        self.payload["metrics"]["min_u_m_s"] = -0.001
        self.payload["sections"][0]["speed_m_s"][0] = 0.002
        result = review.analyze_samples(self.payload, self.reference)
        self.assertFalse(result["engineering_checks"]["no_reverse_u_above_tolerance"])
        self.assertFalse(result["engineering_checks"]["section_walls_below_1e_8"])

    def test_profile_asymmetry_is_flagged(self):
        self.payload["sections"][0]["u_m_s"][20] *= 0.5
        result = review.analyze_samples(self.payload, self.reference)
        self.assertFalse(result["engineering_checks"]["profile_symmetry_below_1_percent"])

    def test_zero_mass_flow_is_not_a_zero_error_pass(self):
        self.payload["metrics"].update(mass_in_kg_m_s=0, mass_out_kg_m_s=0)
        result = review.analyze_samples(self.payload, self.reference)
        self.assertIsNone(result["metrics"]["mass_relative_error"])
        self.assertFalse(result["engineering_checks"]["mass_balance_below_1e_3"])
        self.assertFalse(result["engineering_checks"]["positive_mass_flow"])

    def test_malformed_field_samples_are_rejected(self):
        mutations = (
            lambda p: p.update(solver_run=True),
            lambda p: p.update(height_m=1),
            lambda p: p["metrics"].update(max_speed_m_s=math.nan),
            lambda p: p["sections"][0]["u_m_s"].pop(),
            lambda p: p["sections"][0]["y_m"].__setitem__(0, 0.001),
            lambda p: p["sections"][0]["u_m_s"].__setitem__(1, math.inf),
            lambda p: p["sections"].pop(),
        )
        for mutation in mutations:
            payload = copy.deepcopy(self.payload)
            mutation(payload)
            with self.subTest(mutation=mutation), self.assertRaises(review.CheckError):
                review.analyze_samples(payload, self.reference)

    def test_missing_or_duplicate_completion_marker_is_rejected(self):
        log = self.directory / "console.log"
        payload = "FLOWPILOT_REVIEW_JSON " + json.dumps(self.payload) + "\n"
        for value in (payload, payload + "FLOWPILOT_REVIEW_VERIFIED\n" * 2,
                      payload * 2 + "FLOWPILOT_REVIEW_VERIFIED\n"):
            log.write_text(value, encoding="utf-8")
            with self.assertRaises(review.CheckError):
                review._read_payload(log)

    def test_export_preserves_source_and_provenance(self):
        before = self.model.read_bytes()
        result = self.run_review()
        self.assertEqual(self.model.read_bytes(), before)
        self.assertEqual(result["source"]["sha256"], review.sha256(self.model))
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "completed")
        markdown = (self.output / "report.md").read_text(encoding="utf-8")
        self.assertIn("专业审核待完成", markdown)
        self.assertIn("(velocity.png)", markdown)
        self.assertIn("(profiles.png)", markdown)

    def test_wrong_source_hash_refuses_launch(self):
        self.model.write_bytes(b"uncommitted model edits")
        with patch.object(review, "MANIFEST", self.manifest), patch.object(review, "_run") as run, \
                self.assertRaisesRegex(review.CheckError, "committed baseline hash"):
            review.review_baseline(comsol_root=self.comsol, output_dir=self.output)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_existing_review_directory_is_preserved(self):
        self.output.mkdir()
        existing = self.output / "report.md"
        existing.write_bytes(b"previous review")
        with self.assertRaises(FileExistsError):
            self.run_review()
        self.assertEqual(existing.read_bytes(), b"previous review")

    def test_missing_image_cannot_publish_completed_review(self):
        simulate = self.simulate
        def without_image(command, **kwargs):
            simulate(command, **kwargs)
            if Path(command[0]).name == "comsolbatch.exe":
                (kwargs["cwd"] / "velocity.png").unlink()
        with patch.object(review, "MANIFEST", self.manifest), patch.object(review, "_run", side_effect=without_image), \
                self.assertRaises(FileNotFoundError):
            review.review_baseline(comsol_root=self.comsol, output_dir=self.output)
        metadata = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "failed")
        self.assertFalse((self.output / "review.json").exists())

    def test_wrong_png_header_or_dimensions_is_rejected(self):
        image = self.directory / "wrong.png"
        for content in (b"not an image", b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13)
                        + b"IHDR" + struct.pack(">II", 1, 1)):
            image.write_bytes(content)
            with self.assertRaises(review.CheckError):
                review._verify_png(image, (1600, 400))


if __name__ == "__main__":
    unittest.main()
