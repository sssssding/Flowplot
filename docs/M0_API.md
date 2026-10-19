# M0 COMSOL API evidence

M0 verifies read-only evidence extraction and coverage boundaries, not heat-transfer or multiphysics diagnostic support. The installed runtime is COMSOL Multiphysics 6.3, build 290. The baseline license availability is checked with `ModelUtil.hasProductForFile`; successful interface/coupling construction and subsequent repeated loads provide the operational evidence for those API operations. This does not enumerate licensed products or promise future checkout availability.

## Reproduce

```powershell
python scripts/verify_m0_api.py --comsol-root '<COMSOL_ROOT>' --write-fixture
```

The verifier copies the inventory implementation into a self-contained generated Java driver. COMSOL's batch class loader does not reliably resolve sibling helper classes. It runs the stock `comsolcompile.exe` and `comsolbatch.exe` in a new `outputs/m0_api/<timestamp>` directory. Logs, exact command arguments, generated driver/classes, controlled MPH copies, inventories, and summary remain there. Per-process timeouts use the existing checker process-tree cleanup. On this machine the compiler needs execution outside the restricted sandbox; the sandboxed attempt stalled before producing a class. Both compilation and batch execution must finish successfully, and batch must emit the license, per-model repeat, and final verification markers. A zero process exit code alone is insufficient: COMSOL can report Java exceptions and still return zero.

The probe reads the original baseline and five original fault models three times each. It compares complete inventory strings on each repeated load. It then loads a fresh baseline copy in memory, adds an actual `HeatTransferInFluids` interface, and saves an unsolved output copy. A second output copy adds a Common material with density but no dynamic viscosity and an empty material selection, preserving the original fluid material coverage. When available, a real `NonIsothermalFlow` coupling is saved in enabled and disabled variants. No geometry or study is solved and no source MPH file is saved. Original model SHA-256 values are compared before and after the run.

The sanitized `data/fixtures/m0_api_evidence.json` binds the verified model names, repeat markers, original model hashes, implementation hashes, canonical inventory hashes, and generated driver hash. Detailed logs and models are local output artifacts, not committed fixtures. The summary is historical evidence; rerun after changing the implementation before treating its source hashes as current.

## Additive inventory evidence

Existing `inventory-0.2` fields and successful known-flow readings are preserved. Root and component objects gain a `multiphysics` array alongside `multiphysics_tags`. Each entry contains the actual coupling tag, `getType()` result, `isActive()` state, selection dimensions/entities when readable, enumerated properties, and `read_status` (`read`, `partial`, or `unread`). Selection/property failures retain a reason. Property values are read only through their reported API value type. Unsupported types remain unread; inferred source/target physics fields are not invented. Reference properties such as interface identifiers remain under their actual enumerated names in `properties`. Each readable coupling also records the API `scope`, unique `model_path` from `resolveModelPath()`, and `component_tag`. Ownership is established by comparing that unique path with all component coupling paths, never by matching tags. A null component tag means that a component owner was not established. The root coupling list can contain aliases of component couplings; identical verified model paths identify those aliases, so they should not become unrelated global blockers. If metadata reading fails, the entry is reset to a safe unread object without partial ownership or enabled claims.

The installed Java API reference used to confirm these methods is `doc/help/wtpwebapps/ROOT/doc/com.comsol.help.comsol/api/com/comsol/model/physics/MultiphysicsCoupling.html` and the inherited `ParameterEntity` and `SelectionEntity` references. Coupling selections can be COMSOL-managed and noneditable: the probe reads the default selection rather than setting it.

Material density and viscosity reads are isolated. A missing property yields `expression: ""`, `status: "unresolved"`, `value: null`, its expected unit, and the API failure reason. The empty expression preserves the existing string contract. A missing property on one material does not discard other materials or known flow evidence. Existing fixture data is not rewritten. Generic physics-feature selection or property failures are retained locally as unread evidence, allowing independent features and physics to remain available. Unread evidence is not a detected model error.

## Coverage boundary

The added heat interface is deliberately unknown to M0's flow rule module. Its existence must produce partial coverage while retaining independently valid known-flow checks. Enabled or unread couplings conservatively block rules whose interpretation depends on the coupling. Explicitly disabled and fully readable coupling evidence can be handled separately. No result from these controlled models establishes M1 axisymmetric, M2 thermal/coupling, or M3 three-dimensional support.
