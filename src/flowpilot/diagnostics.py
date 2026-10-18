"""Schedule evidence-scoped modules; preserve the legacy flow model API."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, ValidationError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flowpilot.diagnostic_modules import MODULES
from flowpilot.diagnostic_modules.flow import (
    UnsupportedModel, check, normalize, validate, is_finite_number,
    REYNOLDS_THRESHOLD_GUARD_ULPS, _reynolds_number,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schema" / "diagnostic-model.schema.json"
DIAGNOSIS_SCHEMA = ROOT / "schema" / "diagnosis.schema.json"



def _coupling_coverage(scope, component_tag, pointer):
    """Legacy tag-only coupling evidence is deliberately unknown, never absent."""
    tags = scope.get("multiphysics_tags")
    details = scope.get("multiphysics", [])
    if tags is None:
        tags = ["@unrecorded"]
    if not isinstance(tags, list) or not isinstance(details, list):
        raise ValueError("coupling tags/details must be arrays")
    by_tag = {}
    for index, item in enumerate(details):
        if not isinstance(item, dict) or not isinstance(item.get("tag"), str):
            raise ValueError("invalid coupling detail")
        if item["tag"] in by_tag:
            raise ValueError("duplicate coupling tags")
        by_tag[item["tag"]] = (item, f"{pointer}/multiphysics/{index}")
    entries, blockers = [], []
    for tag in sorted(set(tags) | set(by_tag)):
        item, ref = by_tag.get(tag, ({}, f"{pointer}/multiphysics_tags"))
        inactive = item.get("enabled") is False and item.get("read_status") == "read"
        entry = {"kind": "coupling", "module": "unsupported",
                 "source": {"component_tag": component_tag, "coupling_tag": tag},
                 "status": "skipped" if inactive else "unknown", "applicable": not inactive,
                 "reason": "API 明确记录耦合已禁用；不影响当前规则。" if inactive else
                           "M0 未验证该耦合语义或读取证据；作用域内依赖流动语义的规则跳过。",
                 "evidence_refs": [ref], "rules": []}
        entries.append(entry)
        if not inactive:
            blockers.append(ref)
    return entries, blockers



def _scoped_couplings(inventory):
    """Deduplicate root aliases only with matching API model-path ownership.

    A root tag alone never proves component scope. Both listings must record the
    same unique path and component owner; missing/contradictory evidence remains
    global so no dependent component silently runs uncoupled.
    """
    roots, _ = _coupling_coverage(inventory, "", "")
    locals_by_component = {}
    details_by_ref = {}
    for index, detail in enumerate(inventory.get("multiphysics", [])):
        details_by_ref[f"/multiphysics/{index}"] = detail
    for ci, component in enumerate(inventory["components"]):
        entries, _ = _coupling_coverage(component, component["tag"], f"/components/{ci}")
        locals_by_component[component["tag"]] = entries
        for index, detail in enumerate(component.get("multiphysics", [])):
            details_by_ref[f"/components/{ci}/multiphysics/{index}"] = detail
    retained_roots = []
    for root in roots:
        root_ref = root["evidence_refs"][0]
        detail = details_by_ref.get(root_ref, {})
        owner, path = detail.get("component_tag"), detail.get("model_path")
        candidates = []
        if detail.get("read_status") in {"read", "partial"} and isinstance(path, str) and path and owner in locals_by_component:
            for component_tag, entries in locals_by_component.items():
                for entry in entries:
                    local = details_by_ref.get(entry["evidence_refs"][0], {})
                    if local.get("model_path") == path:
                        candidates.append((component_tag, entry, local))
        if (len(candidates) == 1 and candidates[0][0] == owner
                and candidates[0][2].get("component_tag") == owner
                and candidates[0][2].get("read_status") in {"read", "partial"}):
            entry = candidates[0][1]
            entry["evidence_refs"].append(root_ref)
            if root["applicable"]:
                entry.update(applicable=True, status="unknown", reason=root["reason"])
        else:
            retained_roots.append(root)
    entries = retained_roots + [entry for local in locals_by_component.values() for entry in local]
    global_blockers = [ref for entry in retained_roots if entry["applicable"] for ref in entry["evidence_refs"]]
    local_blockers = {tag: [ref for entry in local if entry["applicable"] for ref in entry["evidence_refs"]]
                      for tag, local in locals_by_component.items()}
    return entries, global_blockers, local_blockers


def diagnose_inventory(inventory, **options):
    """Run registered modules per instance, reporting unsupported evidence scopes."""
    if inventory.get("schema_version") != "inventory-0.2":
        raise ValueError("需要 inventory-0.2 API 证据")
    if set(options) - {"reynolds_warning"}:
        raise TypeError("unknown diagnosis options")
    threshold = options.get("reynolds_warning", 2000.0)
    if not is_finite_number(threshold) or threshold <= 0:
        raise ValueError("Reynolds warning threshold must be finite and positive")
    coverage, global_blockers, scoped_blockers = _scoped_couplings(inventory)
    findings, modules = [], []
    components = inventory["components"]
    component_tags = [c["tag"] for c in components]
    if len(set(component_tags)) != len(component_tags):
        raise ValueError("duplicate component tags")
    for ci, component in enumerate(components):
        local_blockers = scoped_blockers[component["tag"]]
        physics_tags = [p["tag"] for p in component["physics"]]
        if len(set(physics_tags)) != len(physics_tags):
            raise ValueError("duplicate physics tags in component")
        for pi, physics in enumerate(component["physics"]):
            source = {"component_tag": component["tag"], "physics_tag": physics["tag"]}
            geometries = component.get("geometries", [])
            if len(geometries) == 1:
                source["geometry_tag"] = geometries[0]["tag"]
            refs = [f"/components/{ci}/physics/{pi}"]
            module = MODULES.get(physics["type"])
            entry = {"kind": "physics", "module": module.MODULE_ID if module else "unsupported",
                     "source": source, "applicable": physics.get("enabled") is not False,
                     "evidence_refs": refs, "rules": []}
            if physics.get("enabled") is False:
                entry.update(status="skipped", reason="API 明确记录物理场已禁用；未检查。")
            elif module is None:
                entry.update(status="unknown", reason="M0 没有该物理场类型的已验证规则模块: " + physics["type"])
            elif physics.get("enabled") is not True:
                entry.update(status="unknown", reason="缺少明确的物理场启用证据。")
            else:
                result = module.run_instance(inventory, ci, pi, global_blockers + local_blockers, **options)
                for key in ("status", "reason", "evidence_refs", "rules"):
                    entry[key] = result[key]
                module_result = {"module": module.MODULE_ID, "source": source,
                                 "status": "checked" if result["status"] == "checked" else "partial" if any(
                                     r["status"] == "checked" for r in result["rules"]) else "unsupported"}
                if "model" in result:
                    module_result["model"] = result["model"]
                modules.append(module_result)
                findings.extend({**finding, "module": module.MODULE_ID, "source": source}
                                for finding in result["findings"])
            coverage.append(entry)
    if not coverage:
        coverage.append({"kind": "physics", "module": "unsupported",
                         "source": {"component_tag": "", "physics_tag": "@unrecorded"},
                         "status": "unknown", "applicable": True,
                         "reason": "没有可枚举的物理场实例，检查覆盖未知。", "evidence_refs": ["/components"], "rules": []})
    report = {"schema_version": "diagnosis-0.2", "run_status": "completed",
              "status": _coverage_status(coverage),
              "coverage": coverage, "modules": modules,
              "findings": sorted(findings, key=lambda f: (f["source"]["component_tag"],
                                 f["source"]["physics_tag"], f["code"], f["feature_tags"]))}
    if report["status"] == "unsupported":
        report["reason"] = "；".join(dict.fromkeys(c["reason"] for c in coverage if c["applicable"])) or "没有可检查的启用物理场实例。"
    # Preserve the original single-flow consumer contract only for one instance.
    physics_entries = [c for c in coverage if c["kind"] == "physics"]
    original_single_scope = (len(components) == 1 and len(components[0]["physics"]) == 1
                             and len(components[0]["materials"]) == 1)
    if original_single_scope and len(physics_entries) == 1 and len(modules) == 1 and modules[0]["module"] == "flow" and "model" in modules[0]:
        report["model"] = modules[0]["model"]
        report["profile"] = report["model"]["profile"]
        report["numeric_policy"] = {"reynolds_threshold_guard_ulps": REYNOLDS_THRESHOLD_GUARD_ULPS}
    validate_diagnosis_report(report)
    return report


def _coverage_status(coverage):
    active = [entry for entry in coverage if entry["applicable"]]
    checked = sum(rule["status"] == "checked" for entry in active for rule in entry["rules"])
    if not checked:
        return "unsupported"
    return "checked" if all(entry["status"] == "checked" for entry in active) else "partial"


def validate_diagnosis_report(report):
    """Validate the new envelope and semantic status/source consistency."""
    schema = json.loads(DIAGNOSIS_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    if report["status"] != _coverage_status(report["coverage"]):
        raise ValueError("diagnosis status contradicts coverage")
    seen = set()
    for entry in report["coverage"]:
        source = entry["source"]
        key = (entry["kind"], source["component_tag"], source.get("physics_tag"), source.get("coupling_tag"))
        if key in seen:
            raise ValueError("duplicate coverage source")
        seen.add(key)
        if entry["kind"] == "physics" and "physics_tag" not in source:
            raise ValueError("physics coverage requires physics source")
        if entry["kind"] == "coupling" and "coupling_tag" not in source:
            raise ValueError("coupling coverage requires coupling source")
        rules = entry["rules"]
        registered = next((m for m in MODULES.values() if m.MODULE_ID == entry["module"]), None)
        if rules and registered is None:
            raise ValueError("rule coverage requires a registered module")
        if rules and {r["rule_id"] for r in rules} != {r[0] for r in registered.RULES}:
            raise ValueError("module rule coverage is incomplete")
        for rule in rules:
            cases = rule.get("cases", [])
            if len({case["feature_tag"] for case in cases}) != len(cases):
                raise ValueError("duplicate rule case source")
            if rule["status"] == "checked" and any(case["status"] != "checked" for case in cases):
                raise ValueError("checked rule has skipped cases")
        if len({r["rule_id"] for r in rules}) != len(rules):
            raise ValueError("duplicate rule coverage")
        if entry["status"] == "checked" and (not rules or any(r["status"] != "checked" for r in rules)):
            raise ValueError("checked scope must have all rules checked")
        if rules and entry["status"] != "checked" and all(r["status"] == "checked" for r in rules):
            raise ValueError("scope status contradicts rule coverage")
        if not entry["applicable"] and (entry["status"] != "skipped" or rules):
            raise ValueError("inactive scope must be explicitly skipped")
    module_sources = set()
    for module in report["modules"]:
        source = module["source"]
        key = ("physics", source["component_tag"], source["physics_tag"], None)
        if key not in seen or key in module_sources:
            raise ValueError("module source absent or duplicated in coverage")
        module_sources.add(key)
        entry = next((c for c in report["coverage"] if c["kind"] == "physics" and c["source"] == source), None)
        if entry is None:
            raise ValueError("module source differs from coverage source")
        expected = "checked" if entry["status"] == "checked" else "partial" if any(r["status"] == "checked" for r in entry["rules"]) else "unsupported"
        if module["status"] != expected or module["module"] != entry["module"]:
            raise ValueError("module status contradicts coverage")
        if "model" in module:
            registered = next((m for m in MODULES.values() if m.MODULE_ID == module["module"]), None)
            if registered is None:
                raise ValueError("module model requires registered module")
            registered.validate(module["model"])
            if any(module["model"]["source"][k] != source[k] for k in ("component_tag", "physics_tag")):
                raise ValueError("module model source mismatch")
    expected_module_sources = {("physics", c["source"]["component_tag"], c["source"]["physics_tag"], None)
                               for c in report["coverage"] if c["kind"] == "physics" and c["rules"]}
    if module_sources != expected_module_sources:
        raise ValueError("module results must match all module rule scopes")
    for finding in report["findings"]:
        source = finding["source"]
        key = ("physics", source["component_tag"], source["physics_tag"], None)
        if key not in module_sources:
            raise ValueError("finding source lacks a module result")
        entry = next((c for c in report["coverage"] if c["kind"] == "physics" and c["source"] == source), None)
        if entry is None:
            raise ValueError("finding source differs from coverage source")
        rule = next((r for r in entry["rules"] if r["rule_id"] == finding["code"]), None)
        executed_tags = {case["feature_tag"] for case in rule.get("cases", [])
                         if case["status"] == "checked"} if rule else set()
        matched_cases = bool(finding["feature_tags"]) and set(finding["feature_tags"]) <= executed_tags
        if entry["module"] != finding["module"] or rule is None or (rule["status"] != "checked" and not matched_cases):
            raise ValueError("finding lacks executed coverage for its specific rule or node cases")
    if "model" in report:
        if len(report["modules"]) != 1 or report["modules"][0]["module"] != "flow" or report["modules"][0].get("model") != report["model"]:
            raise ValueError("legacy model alias must identify the single module model")
        validate(report["model"])
        if report.get("profile") != report["model"]["profile"]:
            raise ValueError("profile contradicts model")
    # JSON Schema accepts NaN as a Python number; exported evidence never may.
    json.dumps(report, allow_nan=False)


validate_diagnosis = validate_diagnosis_report


def main():
    parser = argparse.ArgumentParser(description="Check COMSOL inventory JSON without solving or changing an MPH file")
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reynolds-warning", type=float, default=2000)
    args = parser.parse_args()
    # Fail before overwriting any user report.
    if args.output.exists():
        parser.error("output already exists; choose a new report path")
    try:
        result = diagnose_inventory(json.loads(args.inventory.read_text(encoding="utf-8-sig")),
                                    reynolds_warning=args.reynolds_warning)
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        parser.error("invalid inventory or options: " + str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"{result['status']}: {len(result['findings'])} findings; {args.output}")


if __name__ == "__main__":
    main()
