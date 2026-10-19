"""Verify M3 retains pinned planar behavior using six fresh reads and fourteen historical inventories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_m0_regression as baseline

SOURCES = tuple(sorted(set(baseline.SOURCES) | {"scripts/verify_m3_regression.py"}))


def verify(args):
    original = baseline.SOURCES
    try:
        baseline.SOURCES = SOURCES
        result = baseline.verify(args)
    finally:
        baseline.SOURCES = original
    result.update(schema_version="m3-planar-regression-1",
                  scope="M3 planar regression: six real CLI reads under the current extractor and engine, plus fourteen historical inventory replays, compared with pinned 1241c27 planar behavior. No solve or new COMSOL execution by this verifier.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("reports-root", "family-root", "baseline-root", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--write-fixture", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = verify(args)
    baseline._write_json(args.output / "summary.json", result)
    if args.write_fixture:
        (ROOT / "data/fixtures/m3_planar_regression.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "cases": result["case_count"], "status": result["status"]}))


if __name__ == "__main__":
    main()
