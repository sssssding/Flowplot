"""Synthetic export faults/limits; not independent physics or execution evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_report_package as fixtures
from flowpilot import report_package as package, package_integrity as integrity
from flowpilot.desktop_session import load_completed_check
from flowpilot.check_model import CheckError
from flowpilot.engine_fingerprint import engine_fingerprint


class ReportExportSafetyTest(unittest.TestCase):
    save = fixtures.ReportPackageTest.save

    def setUp(self):
        fixtures.ReportPackageTest.setUp(self)

    def make_boundary_source(self):
        # A compact, valid source run fits exactly; pretty portable encoding
        # adds whitespace, so the exported run no longer fits the reader limit.
        value = {"schema_version": "check-run-0.1", "status": "completed",
                 "source": {"filename": "", "sha256": "1" * 64},
                 "diagnosis_status": self.report["status"],
                 "rule_engine_sha256": engine_fingerprint(),
                 "diagnosis_sha256": hashlib.sha256((self.source / "diagnosis.json").read_bytes()).hexdigest()}
        def encode():
            return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        value["source"]["filename"] = "n" * (package.MAX_METADATA_BYTES - len(encode()))
        raw = encode()
        self.assertEqual(len(raw), package.MAX_METADATA_BYTES)
        (self.source / "run.json").write_bytes(raw)
        self.assertEqual(load_completed_check(self.source)["report"], self.report)

    def rebind_files(self, *names):
        path = self.output / "package.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for name in names:
            raw = (self.output / name).read_bytes()
            manifest["files"][name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        path.write_bytes(package._json_bytes(manifest))

    def after_integrity(self, action):
        original = package.verify_package
        def verify(path):
            result = original(path)
            action()
            return result
        return patch.object(package, "verify_package", side_effect=verify)

    def test_source_at_reader_limit_cannot_export_an_unreadable_metadata_file(self):
        self.make_boundary_source()
        before = (self.source / "run.json").read_bytes()
        with self.assertRaisesRegex(CheckError, "运行元数据"):
            package.export_package(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual((self.source / "run.json").read_bytes(), before)

    def test_package_manifest_limit_is_checked_before_output_creation(self):
        loaded = load_completed_check(self.source)
        diagnosis = package._json_bytes(loaded["report"])
        portable = package._json_bytes(package._portable_metadata(loaded["metadata"], loaded["report"], diagnosis))
        self.assertLessEqual(len(portable), 1024)
        with patch.object(package, "MAX_METADATA_BYTES", 1024), self.assertRaisesRegex(CheckError, "包清单"):
            package.export_package(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_output_link_or_junction_rejected_before_resolving_target(self):
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            if path == self.output:
                raise AssertionError("linked destination must not be resolved")
            return original(path, *args, **kwargs)
        for predicate in ("is_symlink", "is_junction"):
            with patch.object(Path, predicate, autospec=True, side_effect=lambda path: path == self.output), \
                    patch.object(Path, "resolve", autospec=True, side_effect=resolve), \
                    self.assertRaises(FileExistsError):
                package.export_package(self.source, self.output)
            self.assertFalse(self.output.exists())

    def test_existing_file_or_directory_is_never_reused(self):
        self.output.write_bytes(b"existing user-owned test file")
        with self.assertRaises(FileExistsError):
            package.export_package(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing user-owned test file")
        directory = self.root / "existing-dir"
        directory.mkdir()
        with self.assertRaises(FileExistsError):
            package.export_package(self.source, directory)
        self.assertEqual(list(directory.iterdir()), [])

    def test_nested_destination_still_does_not_mutate_input(self):
        before = {path.name: path.read_bytes() for path in self.source.iterdir()}
        with self.assertRaises(CheckError):
            package.export_package(self.source, self.source / "nested")
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.source.iterdir()})

    def test_structurally_unreadable_portable_metadata_fails_final_reimport(self):
        original = package._portable_metadata
        def wrong(*args):
            result = original(*args)
            result["diagnosis_status"] = "unsupported"
            return result
        with patch.object(package, "_portable_metadata", side_effect=wrong), self.assertRaises(CheckError):
            package.export_package(self.source, self.output)
        # Its byte manifest is valid, proving why integrity alone was insufficient.
        integrity.verify_package(self.output)
        with self.assertRaises(CheckError):
            load_completed_check(self.output)

    def test_rebound_valid_metadata_cannot_silently_change_exported_identity(self):
        def change():
            path = self.output / "run.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["source"]["filename"] = "synthetic-other-model.mph"
            path.write_bytes(package._json_bytes(value))
            self.rebind_files("run.json")
        with self.after_integrity(change), self.assertRaisesRegex(CheckError, "不一致"):
            package.export_package(self.source, self.output)
        self.assertEqual(load_completed_check(self.output)["metadata"]["source"]["filename"], "synthetic-other-model.mph")

    def test_rebound_diagnosis_cannot_change_the_requested_snapshot(self):
        def change():
            path = self.output / "diagnosis.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["findings"][0]["explanation"] = "synthetic change after integrity check"
            path.write_bytes(package._json_bytes(value))
            run = self.output / "run.json"
            metadata = json.loads(run.read_text(encoding="utf-8"))
            metadata["diagnosis_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            run.write_bytes(package._json_bytes(metadata))
            self.rebind_files("diagnosis.json", "run.json")
        with self.after_integrity(change), self.assertRaisesRegex(CheckError, "不一致"):
            package.export_package(self.source, self.output)
        self.assertNotEqual(load_completed_check(self.output)["report"], self.report)
        self.assertEqual(load_completed_check(self.source)["report"], self.report)

    def test_metadata_numeric_type_changes_are_not_silently_equated(self):
        def change():
            path = self.output / "run.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["verified_loads"] = float(value["verified_loads"])
            path.write_bytes(package._json_bytes(value))
            self.rebind_files("run.json")
        with self.after_integrity(change), self.assertRaisesRegex(CheckError, "不一致"):
            package.export_package(self.source, self.output)
        self.assertIs(type(load_completed_check(self.output)["metadata"]["verified_loads"]), float)

    def test_final_reader_failure_is_an_export_failure_not_success(self):
        loaded = load_completed_check(self.source)
        with patch.object(package, "load_completed_check", side_effect=[loaded, OSError("synthetic final read failure")]), \
                self.assertRaises(OSError):
            package.export_package(self.source, self.output)
        self.assertTrue(self.output.exists())  # Retain files for diagnosis; never auto-delete.

    def test_success_reimports_exact_portable_metadata_and_diagnosis(self):
        with patch.object(package, "load_completed_check", wraps=load_completed_check) as read:
            result = package.export_package(self.source, self.output)
        self.assertEqual(read.call_count, 2)
        loaded = load_completed_check(result)
        expected = package._portable_metadata(self.metadata, self.report, package._json_bytes(self.report))
        self.assertEqual(loaded["report"], self.report)
        self.assertEqual(loaded["metadata"], expected)
        for path in self.output.iterdir():
            self.assertNotIn("PRIVATE_PATH", path.read_text(encoding="utf-8"))

    def test_completed_run_remains_last_written_payload(self):
        original = Path.open
        writes = []
        def open_file(path, *args, **kwargs):
            if args == ("xb",):
                writes.append(path.name)
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", open_file):
            package.export_package(self.source, self.output)
        self.assertEqual(writes[-1], "run.json")
        self.assertEqual(set(writes), integrity.PACKAGE_FILES | {"package.json"})

    def test_cli_does_not_claim_exported_for_metadata_limit_failure(self):
        self.make_boundary_source()
        result = subprocess.run([sys.executable, "-X", "utf8", str(fixtures.ROOT / "src/flowpilot/report_package.py"),
                                 str(self.source), "--output-dir", str(self.output)], capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Exported:", result.stdout)
        self.assertIn("64 KiB", result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
