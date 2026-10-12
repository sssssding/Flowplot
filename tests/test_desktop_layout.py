"""Pure sizing/model-copy checks, not screenshots or professional review."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from flowpilot.check_model import CheckError
from flowpilot.desktop import initial_window_size
from scripts.smoke_desktop import resolve_models


class LayoutTest(unittest.TestCase):
    def test_standard_window_and_small_screen_fit(self):
        self.assertEqual(initial_window_size(1920, 1080), (1100, 850))
        self.assertEqual(initial_window_size(1024, 768), (944, 668))
        self.assertEqual(initial_window_size(800, 600), (720, 500))

    def test_invalid_screen_dimensions(self):
        for width, height in ((0, 768), (1024, -1), (True, 768), (1024, 1.5)):
            with self.subTest(size=(width, height)), self.assertRaises(ValueError):
                initial_window_size(width, height)

    def test_smoke_accepts_only_matching_copy_and_preserves_changes(self):
        (ROOT / "outputs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            root = Path(directory).resolve()
            model = root / "copy.mph"
            model.write_bytes(b"mock model, no actual COMSOL")
            cases = [{"case_id": "baseline", "model_path": model.name,
                      "sha256": hashlib.sha256(model.read_bytes()).hexdigest()}]
            self.assertEqual(resolve_models(root, cases), {"baseline": model})
            model.write_bytes(b"local change")
            with self.assertRaises(CheckError):
                resolve_models(root, cases)
            self.assertEqual(model.read_bytes(), b"local change")


if __name__ == "__main__":
    unittest.main()
