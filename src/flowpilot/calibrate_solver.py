"""Explicit calibration on independent copies of the canonical baseline only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.check_model import CheckError, _run, _write_json, sha256
from flowpilot.recommend import CANDIDATES, environment_id, fit, read_json
from flowpilot.review_baseline import MANIFEST, REFERENCE
from flowpilot.solve_baseline import JAVA_SOURCE, _read_payload, analyze_solve


def driver(candidate):
    if candidate not in CANDIDATES:
        raise ValueError("Configuration not allowlisted")
    source = JAVA_SOURCE.read_text(encoding="utf-8-sig")
    needle = '      model.sol("sol1").clearSolutionData();'
    if source.count("public class BaselineSolve") != 1 or source.count(needle) != 1:
        raise CheckError("Baseline driver changed; review calibration adapter")
    source = source.replace("public class BaselineSolve", "public class CandidateSolve")
    injection = ('      model.sol("sol1").feature("s1").set("control", "user");\n'
                 f'      model.sol("sol1").feature("s1").set("stol", "{candidate["stol"]:g}");\n'
                 '      if (!"user".equals(model.sol("sol1").feature("s1").getString("control")))\n'
                 '        throw new IllegalStateException("Tolerance control was not applied");\n'
                 '      System.out.println("FLOWPLOT_TOLERANCE " + model.sol("sol1").feature("s1").getDouble("stol"));\n')
    return source.replace(needle, injection + needle)


def calibrate(*, model_path, comsol_root, output_dir, timeout=300):
    if type(timeout) not in (int, float) or not 0 < timeout <= 3600:
        raise ValueError("Timeout must be finite and from 0 to 3600 seconds")
    baseline = next(case for case in read_json(MANIFEST)["cases"] if case["case_id"] == "baseline")
    model = Path(model_path).resolve(strict=True)
    original = sha256(model)
    if original != baseline["sha256"].lower():
        raise CheckError("Calibration only accepts the committed baseline; preserve local edits")
    sources = {"driver": sha256(JAVA_SOURCE), "reference": sha256(REFERENCE)}
    reference = read_json(REFERENCE)["runs"][0]
    comsol = Path(comsol_root).resolve(strict=True)
    compiler, batch = (comsol / "bin/win64" / name for name in ("comsolcompile.exe", "comsolbatch.exe"))
    if not compiler.is_file() or not batch.is_file():
        raise FileNotFoundError("Missing COMSOL compiler/batch")
    output = Path(output_dir)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise FileExistsError("Calibration output must be a new directory")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dataset = {"schema_version": "solver-calibration-0.1", "status": "running", "repeats": 3,
               "source_sha256": original, "environment_id": environment_id(), "sources": sources,
               "started_at": datetime.now(timezone.utc).isoformat(), "observations": []}
    try:
        compiled = {}
        for candidate in CANDIDATES:
            directory = output / candidate["id"]
            directory.mkdir()
            java = directory / "CandidateSolve.java"
            with java.open("x", encoding="utf-8") as stream:
                stream.write(driver(candidate))
            _run([str(compiler), str(java)], cwd=directory, log=directory / "compile.log", timeout=timeout)
            bytecode = directory / "CandidateSolve.class"
            if not bytecode.is_file() or not bytecode.stat().st_size:
                raise CheckError("Missing compiled candidate driver")
            compiled[candidate["id"]] = bytecode
        # Rotate run order to reduce startup/background-load bias; run sequentially.
        for repeat in (1, 2, 3):
            order = CANDIDATES[repeat-1:] + CANDIDATES[:repeat-1]
            for candidate in order:
                child = output / candidate["id"] / f"repeat-{repeat}"
                child.mkdir()
                snapshot = child / "input.mph"
                shutil.copyfile(model, snapshot)
                if sha256(snapshot) != original:
                    raise CheckError("Input changed during snapshot")
                console, native = child / "console.log", child / "batch.log"
                started = time.monotonic()
                _run([str(batch), "-inputfile", str(compiled[candidate["id"]]), "-nosave",
                      "-batchlog", str(native), "-batchlogout", "-np", str(candidate["threads"])],
                     cwd=child, log=console, timeout=timeout)
                elapsed = time.monotonic() - started
                payload = _read_payload(console)
                config = [line for line in console.read_text(encoding="utf-8", errors="replace").splitlines()
                          if line.startswith("FLOWPLOT_TOLERANCE ")]
                if len(config) != 1 or float(config[0].split()[1]) != candidate["stol"]:
                    raise CheckError("Missing/ambiguous actual tolerance evidence")
                analysis = analyze_solve(payload, reference)
                solved = child / "solved.mph"
                if not solved.is_file() or solved.stat().st_size <= 128 or not native.is_file() or not native.stat().st_size:
                    raise CheckError("Missing solve artifacts")
                if sha256(snapshot) != original or sha256(model) != original:
                    raise CheckError("Source/snapshot changed; refusing calibration")
                row = {"candidate": candidate, "repeat": repeat, "evidence": payload, "analysis": analysis,
                       "process_seconds": elapsed, "solved_sha256": sha256(solved),
                       "console_sha256": sha256(console), "batch_sha256": sha256(native)}
                _write_json(child / "observation.json", row)
                dataset["observations"].append(row)
                print(f"{candidate['id']} repeat {repeat}: {payload['solve_seconds']:.3f}s; "
                      f"quality={analysis['engineering_checks_passed']}", flush=True)
        if sources != {"driver": sha256(JAVA_SOURCE), "reference": sha256(REFERENCE)}:
            raise CheckError("Calibration sources changed")
        dataset.update(status="completed", finished_at=datetime.now(timezone.utc).isoformat())
        learned = fit(dataset)
        _write_json(output / "dataset.json", dataset)
        _write_json(output / "model.json", learned)
        return learned
    except Exception as error:
        dataset.update(status="failed", error=str(error))
        raise
    except KeyboardInterrupt:
        dataset.update(status="cancelled")
        raise
    finally:
        _write_json(output / "run.json", dataset)


def main():
    parser = argparse.ArgumentParser(description="FlowPlot: calibrate solver candidates on copies (runs COMSOL)")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--comsol-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    try:
        calibrate(model_path=args.model, comsol_root=args.comsol_root, output_dir=args.output_dir, timeout=args.timeout)
    except (OSError, ValueError, TypeError, KeyError, CheckError) as error:
        parser.exit(1, f"Calibration failed: {error}\n")
    print("Local calibration completed; not independent performance validation.")


if __name__ == "__main__":
    main()
