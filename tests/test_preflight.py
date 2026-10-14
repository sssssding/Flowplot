import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from flowpilot import preflight as module


class PreflightTest(unittest.TestCase):
    def setUp(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "outputs")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "模型.mph"
        self.payload = b"test model bytes; not real COMSOL evidence"
        self.model.write_bytes(self.payload)
        self.case = {"case_id": "baseline", "model_path": self.model.name,
                     "sha256": hashlib.sha256(self.payload).hexdigest()}
        self.manifest = self.root / "manifest.json"
        self.write_manifest([self.case])

    def write_manifest(self, cases):
        self.manifest.write_text(json.dumps({"schema_version": "case-manifest-0.1", "cases": cases}), encoding="utf-8")

    def test_complete_model_and_readonly_result(self):
        before = self.model.read_bytes()
        with patch.object(module, "check_environment", return_value=[{"status": "ok"}]):
            result = module.preflight(manifest=self.manifest, model_root=self.root)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["models"][0]["status"], "ok")
        self.assertTrue(result["readonly"])
        for key in ("license_validated", "visual_review", "expert_review"):
            self.assertFalse(result[key])
        self.assertEqual(self.model.read_bytes(), before)

    def test_modified_model_is_preserved_and_blocks(self):
        self.model.write_bytes(b"local changes")
        result = module.preflight(manifest=self.manifest, model_root=self.root)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["models"][0]["status"], "hash_mismatch")
        self.assertEqual(self.model.read_bytes(), b"local changes")

    def test_pointer_is_not_a_model(self):
        self.model.write_bytes(module.LFS_HEADER + b"\noid sha256:abc\nsize 100\n")
        self.assertEqual(module.check_models([self.case], self.root)[0]["status"], "lfs_pointer")

    def test_missing_model(self):
        absent = dict(self.case, model_path="absent.mph")
        self.assertEqual(module.check_models([absent], self.root)[0]["status"], "missing")

    def test_resolved_path_outside_root_is_not_read(self):
        # Model a symlink/junction without needing Windows symlink privileges.
        outside = self.root.parent / "external.mph"
        with patch.object(Path, "resolve", side_effect=[self.root, outside]), patch.object(Path, "open") as reader:
            result = module.check_models([self.case], self.root)
        self.assertEqual(result[0]["status"], "outside_root")
        reader.assert_not_called()

    def test_invalid_manifest_paths_and_hashes(self):
        for path in ("../outside.mph", "..\\outside.mph", "/tmp/outside.mph", "C:\\outside.mph", "model.mph:stream", "model.txt"):
            with self.subTest(path=path):
                self.write_manifest([dict(self.case, model_path=path)])
                with self.assertRaises(ValueError):
                    module.read_cases(self.manifest)
        self.write_manifest([dict(self.case, sha256="abc")])
        with self.assertRaises(ValueError):
            module.read_cases(self.manifest)

    def test_duplicates_and_oversized_json_rejected(self):
        self.write_manifest([self.case, self.case])
        with self.assertRaises(ValueError):
            module.read_cases(self.manifest)
        self.manifest.write_text('{"cases":[],"cases":[]}', encoding="utf-8")
        with self.assertRaises(ValueError):
            module.read_cases(self.manifest)
        self.manifest.write_bytes(b" " * 65537)
        with self.assertRaises(ValueError):
            module.read_cases(self.manifest)

    def test_comsol_files_do_not_prove_license(self):
        checks = module.check_environment(self.root)
        self.assertEqual(next(x for x in checks if x["name"] == "comsol")["status"], "error")
        folder = self.root / "bin/win64"
        folder.mkdir(parents=True)
        for name in ("comsolcompile.exe", "comsolbatch.exe"):
            (folder / name).write_bytes(b"fake, never run")
        self.assertEqual(next(x for x in module.check_environment(self.root) if x["name"] == "comsol")["status"], "ok")

    def test_missing_dependencies_block_and_no_comsol_is_warning(self):
        with patch.object(module.importlib, "import_module", side_effect=ImportError):
            result = module.preflight(manifest=self.manifest, model_root=self.root)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(sum(x["status"] == "error" for x in result["environment"]), 2)
        with patch.object(module, "check_environment", return_value=[{"status": "warning"}]):
            result = module.preflight(manifest=self.manifest, model_root=self.root)
        self.assertEqual(result["status"], "ready_with_warnings")

    def test_invalid_manifest_is_reported_not_fixed(self):
        self.manifest.write_text("not json", encoding="utf-8")
        result = module.preflight(manifest=self.manifest, model_root=self.root)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("manifest_error", result)
        self.assertEqual(self.manifest.read_text(encoding="utf-8"), "not json")

    def test_cli_json_and_exit_code(self):
        command = [sys.executable, "-X", "utf8", str(ROOT / "src/flowpilot/preflight.py"),
                   "--manifest", str(self.manifest), "--model-root", str(self.root), "--json"]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["models"][0]["status"], "ok")
        self.model.write_bytes(b"changed")
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(json.loads(completed.stdout)["models"][0]["status"], "hash_mismatch")


if __name__ == "__main__":
    unittest.main()
