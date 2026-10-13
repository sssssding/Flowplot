"""Synthetic bytes/review strings exercise preparation only, not physical acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_acceptance_dataset as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import acceptance_dataset as dataset, acceptance_preflight as preflight


class AcceptancePreflightTest(unittest.TestCase):
    save_manifest = fixtures.AcceptanceDatasetTest.save_manifest

    def setUp(self):
        fixtures.AcceptanceDatasetTest.setUp(self)

    def inspect(self):
        return preflight.inspect_manifest(self.manifest_path, model_root=self.models)

    def codes(self, result):
        return {issue["code"] for issue in result["issues"]}

    def test_prepared_synthetic_inputs_are_readonly_not_an_acceptance_result(self):
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = self.inspect()
        self.assertEqual(result["status"], "ready_to_freeze")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["summary"], {"case_count": 10, "declared_group_count": 2,
                                           "matching_model_count": 10, "issue_count": 0})
        for name in ("software_authenticates_reviewers", "formal_acceptance_completed", "freeze_created"):
            self.assertIs(result[name], False)
        self.assertTrue(result["readonly"])
        self.assertNotIn("recall", json.dumps(result).lower())
        self.assertEqual(result["manifest_sha256"], hashlib.sha256(before[self.manifest_path]).hexdigest())
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        self.assertFalse(self.output.exists())

    def test_lists_multiple_case_and_dataset_review_issues_without_filling_fields(self):
        self.manifest.pop("acceptance_declaration")
        self.manifest.update(independent_acceptance_set=False, label_status="pending")
        self.manifest["cases"][0].pop("reviewed_by")
        self.manifest["cases"][0].update(reviewed_date="2099-01-01", used_for_rule_development=True)
        self.manifest["cases"][1].pop("created_by")
        self.save_manifest()
        before = self.manifest_path.read_bytes()
        result = self.inspect()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue({"declaration_missing", "independent_set_not_declared", "expert_review_pending",
                         "review_text_required", "review_date_invalid", "development_usage_not_excluded",
                         "freeze_validation_failed"} <= self.codes(result))
        self.assertTrue(any(item.get("case_id") == "case-001" and item["field"] == "created_by" for item in result["issues"]))
        self.assertEqual(result["summary"]["matching_model_count"], 10)
        self.assertEqual(self.manifest_path.read_bytes(), before)

    def test_false_truthy_declarations_are_not_confirmations(self):
        for value in (1, "true", False, None):
            for field in dataset.DECLARATIONS:
                self.manifest["acceptance_declaration"][field] = value
            self.save_manifest()
            result = self.inspect()
            self.assertEqual(sum(item["code"] == "declaration_not_confirmed" for item in result["issues"]), 3)
            self.assertEqual(result["status"], "blocked")

    def test_all_text_fields_share_freeze_validator_limits(self):
        original = copy.deepcopy(self.manifest)
        for value in (None, "", " ", True, "x" * 1001, "bad\x00name"):
            self.manifest = copy.deepcopy(original)
            self.manifest["cases"][0]["origin_reference"] = value
            self.save_manifest()
            result = self.inspect()
            self.assertIn("review_text_required", self.codes(result))
            self.assertEqual(result["status"], "blocked")

    def test_dates_use_same_canonical_past_date_requirement(self):
        for value in (True, "2099-01-01", "20000101", "not a date", None):
            self.manifest["cases"][0]["reviewed_date"] = value
            self.manifest["acceptance_declaration"]["independence_reviewed_date"] = value
            self.save_manifest()
            result = self.inspect()
            self.assertEqual(sum(item["code"] == "review_date_invalid" for item in result["issues"]), 2)

    def test_all_file_failures_are_collected_and_other_models_checked(self):
        (self.models / "case-000.mph").unlink()
        (self.models / "case-001.mph").write_bytes(b"changed synthetic input")
        (self.models / "case-002.mph").write_bytes(dataset.LFS_HEADER + b"\noid sha256:test\n")
        (self.models / "case-003.mph").write_bytes(b"")
        result = self.inspect()
        self.assertEqual([row["model_status"] for row in result["cases"][:4]],
                         ["missing", "hash_mismatch", "invalid_file", "invalid_file"])
        self.assertEqual(result["summary"]["matching_model_count"], 6)
        self.assertTrue({"model_missing", "model_hash_mismatch", "model_file_invalid"} <= self.codes(result))
        self.assertEqual(result["status"], "blocked")

    def test_file_read_errors_do_not_prevent_remaining_checks(self):
        original = dataset.sha256
        def denied(path):
            if path == self.models / "case-000.mph":
                raise PermissionError("synthetic private local path, do not disclose")
            return original(path)
        with patch.object(dataset, "sha256", side_effect=denied):
            result = self.inspect()
        self.assertEqual(result["cases"][0]["model_status"], "read_error")
        self.assertEqual(result["summary"]["matching_model_count"], 9)
        self.assertNotIn("private local path", json.dumps(result))

    def test_known_original_and_variant_hashes_block_preparation(self):
        known = sorted(dataset.fingerprints()[1])
        self.manifest["cases"][0]["sha256"] = known[0]
        self.manifest["cases"][1]["sha256"] = known[-1]
        self.save_manifest()
        result = self.inspect()
        self.assertEqual(sum(item["code"] == "known_development_model" for item in result["issues"]), 2)
        self.assertEqual(result["status"], "blocked")

    def test_development_manifest_remains_blocked_even_when_files_match(self):
        result = preflight.inspect_manifest(ROOT / "data/fixtures/cases/manifest.json", model_root=ROOT)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("known_development_model", self.codes(result))
        self.assertIn("too_few_cases", self.codes(result))
        self.assertFalse(result["formal_acceptance_completed"])

    def test_minimum_count_coverage_negative_and_group_hints(self):
        self.manifest["cases"] = self.manifest["cases"][:6]
        for case in self.manifest["cases"]:
            case.update(expected_codes=["MISSING_INLET"], independence_group="Same Group")
        self.save_manifest()
        result = self.inspect()
        self.assertTrue({"too_few_cases", "rules_not_covered", "negative_control_missing",
                         "independent_groups_insufficient"} <= self.codes(result))

    def test_group_normalization_and_robustness_cases_are_not_independent(self):
        for case in self.manifest["cases"]:
            case["independence_group"] = " GROUP " if case["case_id"].endswith("0") else "group"
        self.manifest["cases"][0]["expected_codes"] = ["EVALUATION_UNAVAILABLE"]
        self.save_manifest()
        result = self.inspect()
        self.assertEqual(result["summary"]["declared_group_count"], 1)
        self.assertTrue({"independent_groups_insufficient", "robustness_case_not_formal"} <= self.codes(result))

    def test_case_insensitive_id_and_path_collisions_are_explained(self):
        self.manifest["cases"][1]["case_id"] = "CASE-000"
        self.manifest["cases"][1]["model_path"] = "CASE-000.MPH"
        self.save_manifest()
        result = self.inspect()
        self.assertTrue({"case_id_collision", "model_path_collision"} <= self.codes(result))

    def test_unsafe_paths_are_never_passed_to_model_reader(self):
        original = copy.deepcopy(self.manifest)
        for value in ("../escape.mph", "/escape.mph", "C:escape.mph", "C:\\escape.mph"):
            self.manifest = copy.deepcopy(original)
            self.manifest["cases"][0]["model_path"] = value
            self.save_manifest()
            with patch.object(dataset, "_model", wraps=dataset._model) as reader:
                result = self.inspect()
            # A drive-less rooted path is classified differently by Windows/POSIX
            # at the basic gate; the strict relative-path gate must reject either.
            self.assertIn(result["status"], ("invalid", "blocked"))
            self.assertTrue(all(call.args[1] != value for call in reader.call_args_list))

    def test_non_mph_or_alternate_stream_paths_are_blocked_case_by_case(self):
        for value in ("wrong.txt", "case-000.mph:secret", "bad\x00name.mph"):
            self.manifest["cases"][0]["model_path"] = value
            self.save_manifest()
            result = self.inspect()
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["cases"][0]["model_status"], "unsafe_path")
            self.assertIn("model_path_invalid", self.codes(result))

    def test_missing_or_link_root_never_reads_model_files(self):
        with patch.object(dataset, "_model") as reader:
            result = preflight.inspect_manifest(self.manifest_path, model_root=self.root / "missing-root")
        reader.assert_not_called()
        self.assertEqual(result["status"], "blocked")
        self.assertIn("model_root_invalid", self.codes(result))
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda path: path == self.models):
            self.assertIn("model_root_invalid", self.codes(self.inspect()))

    def test_model_links_and_junctions_are_rejected_without_following(self):
        target = self.models / "case-000.mph"
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == target):
            result = self.inspect()
        self.assertEqual(result["cases"][0]["model_status"], "invalid_file")
        self.assertEqual(result["summary"]["matching_model_count"], 9)

    def test_json_bounds_duplicates_nonfinite_and_depth_rejected(self):
        for payload in (b" " * 65537, b'{"cases":[],"cases":[]}', b'{"bad":NaN}', b"[" * 70 + b"0" + b"]" * 70):
            self.manifest_path.write_bytes(payload)
            result = self.inspect()
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(result["cases"], [])

    def test_unavailable_or_link_manifest_has_no_exception_details(self):
        self.manifest_path.unlink()
        result = self.inspect()
        self.assertEqual(result["status"], "invalid")
        self.assertNotIn(str(self.root), json.dumps(result))
        self.save_manifest()
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == self.manifest_path):
            self.assertEqual(self.inspect()["status"], "invalid")

    def test_missing_program_registry_fails_closed(self):
        with patch.object(dataset, "fingerprints", side_effect=ValueError("synthetic registry failure")), \
                patch.object(dataset, "_model") as reader:
            result = self.inspect()
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(self.codes(result), {"registry_unavailable"})
        reader.assert_not_called()

    def test_real_freeze_gate_cannot_be_overridden_by_hints(self):
        with patch.object(dataset, "validate_acceptance", side_effect=ValueError("synthetic stricter gate")):
            result = self.inspect()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.codes(result), {"freeze_validation_failed"})

    def test_changes_to_manifest_programs_or_registries_are_not_ready(self):
        original = dataset.fingerprints
        first = original()
        changed = (dict(first[0], **{"changed-source": "0" * 64}), first[1])
        with patch.object(dataset, "fingerprints", side_effect=[first, changed]):
            self.assertIn("inputs_changed", self.codes(self.inspect()))
        validate = dataset.validate_acceptance
        def mutate(*args, **kwargs):
            self.manifest_path.write_bytes(self.manifest_path.read_bytes() + b"\n")
            return validate(*args, **kwargs)
        with patch.object(dataset, "validate_acceptance", side_effect=mutate):
            self.assertIn("inputs_changed", self.codes(self.inspect()))

    def test_private_review_text_is_not_copied_into_hints_or_rendered_report(self):
        for case in self.manifest["cases"]:
            case.update(reviewed_by="PRIVATE_REVIEWER", origin_reference="PRIVATE_ORIGIN_PATH")
        self.manifest["acceptance_declaration"].update(dataset_id="PRIVATE_DATASET", independence_reviewed_by="PRIVATE_PERSON")
        self.save_manifest()
        result = self.inspect()
        self.assertEqual(result["status"], "ready_to_freeze")
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertNotIn("PRIVATE_", preflight.render_preflight(result))

    def test_cli_exit_codes_json_and_different_working_directory(self):
        command = [sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/acceptance_preflight.py"),
                   "--manifest", str(self.manifest_path), "--model-root", str(self.models)]
        result = subprocess.run(command + ["--json"], cwd=self.root, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ready_to_freeze")
        (self.models / "case-000.mph").unlink()
        result = subprocess.run(command, capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertIn("FlowPlot", result.stdout)
        self.assertIn("文件哈希匹配", result.stdout)
        self.assertIn("case-000", result.stdout)
        self.manifest_path.write_bytes(b"invalid JSON")
        result = subprocess.run(command + ["--json"], capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
