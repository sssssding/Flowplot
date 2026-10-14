"""Report-directory/link guards; mocked links are not OS junction integration tests."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_report_reader as reader_fixtures
import test_check_suite as suite_fixtures
import test_acceptance_dataset as frozen_fixtures
from flowpilot import desktop_session as desktop, package_integrity as integrity
from flowpilot import check_suite as suite, report_package as packages
from flowpilot import acceptance_dataset as frozen


class ReportDirectoryBoundaryTest(unittest.TestCase):
    save = reader_fixtures.ReportReaderTest.save
    assert_rejected_everywhere = reader_fixtures.ReportReaderTest.assert_rejected_everywhere

    def setUp(self):
        reader_fixtures.ReportReaderTest.setUp(self)

    def test_plain_report_root_symlink_rejected_by_all_consumers(self):
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == self.source):
            self.assert_rejected_everywhere()

    def test_plain_report_root_junction_rejected_by_all_consumers(self):
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda path: path == self.source):
            self.assert_rejected_everywhere()

    def test_root_link_is_checked_before_resolution_and_file_reads(self):
        for predicate in ("is_symlink", "is_junction"):
            with patch.object(Path, predicate, autospec=True, side_effect=lambda path: path == self.source), \
                    patch.object(Path, "resolve", side_effect=AssertionError("link must not be resolved")), \
                    patch.object(desktop, "read_regular_file") as read, self.assertRaises(desktop.CheckError):
                desktop.load_completed_check(self.source)
            read.assert_not_called()

    def test_package_root_symlink_is_rejected_before_manifest_read(self):
        target = packages.export_package(self.source, self.root / "package")
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == target), \
                patch.object(integrity, "read_regular_file") as read, self.assertRaises(ValueError):
            integrity.read_verified_package(target)
        read.assert_not_called()

    def test_package_root_junction_is_rejected_by_common_and_direct_readers(self):
        target = packages.export_package(self.source, self.root / "package")
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda path: path == target):
            with self.assertRaises(ValueError):
                integrity.verify_package(target)
            with self.assertRaises(desktop.CheckError):
                desktop.load_completed_check(target)
            self.assertEqual(suite.read_outcome(target, self.case, 2000)["status"], "unscored")

    def test_regular_and_complete_packaged_reports_are_still_equivalent(self):
        target = packages.export_package(self.source, self.root / "package")
        self.assertEqual(desktop.load_completed_check(target)["report"], desktop.load_completed_check(self.source)["report"])
        self.assertEqual(suite.read_outcome(target, self.case, 2000)["status"], "checked")

    def test_export_from_link_does_not_create_destination_or_mutate_target(self):
        before = {path.name: path.read_bytes() for path in self.source.iterdir()}
        target = self.root / "not-created"
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == self.source), \
                self.assertRaises(desktop.CheckError):
            packages.export_package(self.source, target)
        self.assertFalse(target.exists())
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.source.iterdir()})


class BatchDirectoryBoundaryTest(unittest.TestCase):
    write_report = suite_fixtures.CheckSuiteTest.write_report
    offline = suite_fixtures.CheckSuiteTest.offline

    def setUp(self):
        suite_fixtures.CheckSuiteTest.setUp(self)
        quiet = patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_linked_batch_root_rejected_before_case_reads_or_output(self):
        for predicate in ("is_symlink", "is_junction"):
            with patch.object(Path, predicate, autospec=True, side_effect=lambda path: path == self.reports), \
                    patch.object(suite, "read_outcome") as read, self.assertRaises(ValueError):
                self.offline()
            read.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_linked_case_is_unscored_without_reading_target_payload(self):
        target = self.reports / "baseline"
        original = desktop.read_regular_file
        reads = []
        def read(path, **kwargs):
            reads.append(Path(path))
            return original(path, **kwargs)
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == target), \
                patch.object(desktop, "read_regular_file", side_effect=read):
            result = self.offline()
        self.assertEqual(result["checked_cases"], 5)
        self.assertEqual(result["cases"][0]["status"], "unscored")
        self.assertFalse(any(path.is_relative_to(target) for path in reads))
        self.assertEqual(json.loads((self.output / "run.json").read_text(encoding="utf-8"))["status"], "incomplete")

    def test_nested_output_is_rejected_without_mutating_input_reports(self):
        before = {path: path.read_bytes() for path in self.reports.rglob("*") if path.is_file()}
        for output in (self.reports / "new-batch", self.reports / "baseline/new-batch"):
            self.output = output
            with patch.object(suite, "read_outcome") as read, self.assertRaises(ValueError):
                self.offline()
            read.assert_not_called()
            self.assertFalse(output.exists())
        self.assertEqual(before, {path: path.read_bytes() for path in self.reports.rglob("*") if path.is_file()})

    def test_output_inside_complete_capsule_is_rejected_without_breaking_package(self):
        capsule = packages.export_package(self.reports / "baseline", self.directory / "capsule")
        original = integrity.verify_package(capsule)
        with self.assertRaises(ValueError):
            suite.run_suite(suite.DEVELOPMENT_MANIFEST, reports_root=capsule, output_dir=capsule / "batch")
        self.assertEqual(integrity.verify_package(capsule), original)
        self.assertFalse((capsule / "batch").exists())

    def test_resolved_output_alias_into_reports_root_is_rejected(self):
        original = Path.resolve
        target = self.reports / "nested"
        with patch.object(Path, "resolve", autospec=True,
                          side_effect=lambda path, *a, **kw: target if path == self.output else original(path, *a, **kw)), \
                self.assertRaises(ValueError):
            self.offline()
        self.assertFalse(target.exists())
        self.assertFalse(self.output.exists())

    def test_broken_junction_output_is_rejected_before_resolution(self):
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda path: path == self.output), \
                self.assertRaises(FileExistsError):
            self.offline()
        self.assertFalse(self.output.exists())

    def test_input_root_becoming_link_stops_before_next_case_read(self):
        original = suite.read_outcome
        linked = False
        calls = []
        def read(*args, **kwargs):
            nonlocal linked
            value = original(*args, **kwargs)
            calls.append(args[0])
            linked = True
            return value
        with patch.object(suite, "read_outcome", side_effect=read), \
                patch.object(Path, "is_junction", autospec=True, side_effect=lambda path: linked and path == self.reports), \
                self.assertRaises(suite.CheckError):
            self.offline()
        self.assertEqual(len(calls), 1)
        run = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["attempted_cases"], 1)
        self.assertFalse((self.output / "summary.json").exists())

    def test_case_becoming_link_after_scoring_fails_publication(self):
        original = suite.evaluate_dataset
        linked = False
        target = self.reports / "baseline"
        def evaluate(*args, **kwargs):
            nonlocal linked
            value = original(*args, **kwargs)
            linked = True
            return value
        with patch.object(suite, "evaluate_dataset", side_effect=evaluate), \
                patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: linked and path == target), \
                self.assertRaises(suite.CheckError):
            self.offline()
        run = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "failed")
        self.assertFalse(run["input_stability_verified"])
        self.assertFalse((self.output / "summary.json").exists())


class FrozenDirectoryBoundaryTest(unittest.TestCase):
    save_manifest = frozen_fixtures.AcceptanceDatasetTest.save_manifest

    def setUp(self):
        frozen_fixtures.AcceptanceDatasetTest.setUp(self)

    def test_formal_output_inside_reports_is_rejected_before_creating_any_files(self):
        frozen.freeze_dataset(self.manifest_path, model_root=self.models, output_dir=self.output)
        output = self.reports_root / "nested-run"
        with patch.object(frozen, "run_suite") as backend, self.assertRaises(ValueError):
            frozen.run_frozen(self.output, output_dir=output, reports_root=self.reports_root)
        backend.assert_not_called()
        self.assertFalse(output.exists())
        self.assertEqual(list(self.reports_root.iterdir()), [])

    def test_formal_linked_reports_root_is_rejected_before_output_or_backend(self):
        frozen.freeze_dataset(self.manifest_path, model_root=self.models, output_dir=self.output)
        output = self.root / "not-created"
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda path: path == self.reports_root), \
                patch.object(frozen, "run_suite") as backend, self.assertRaises(ValueError):
            frozen.run_frozen(self.output, output_dir=output, reports_root=self.reports_root)
        backend.assert_not_called()
        self.assertFalse(output.exists())

    def test_shared_new_output_guard_rejects_broken_junction_before_resolution(self):
        with patch.object(Path, "is_junction", autospec=True, side_effect=lambda path: path == self.output), \
                patch.object(Path, "resolve", side_effect=AssertionError("must not resolve linked output")), \
                self.assertRaises(FileExistsError):
            frozen._new_output(self.output, self.models)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
