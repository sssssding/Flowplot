# FlowPlot MVP Scope

## Supported

- COMSOL 2D models
- Laminar Flow
- Single fluid domain
- Stationary study
- Boundary types:
  - Inlet
  - Outlet
  - Wall

## Boundary checks

1. Missing inlet
2. Missing outlet
3. Conflicting boundary settings
4. Abnormal inlet velocity direction
5. Parameter range risk

## Not supported in MVP

- Turbulent flow
- Multiphase flow
- Time-dependent simulation
- 3D geometry
- Heat transfer coupling
- Fluid-structure interaction
- Moving mesh

## Goal of MVP

Given a supported COMSOL model, the system should:

1. Identify the flow physics.
2. Read all relevant boundaries.
3. Read the parameters attached to each boundary.
4. Build a structured representation.
5. Detect the predefined boundary-condition problems.
