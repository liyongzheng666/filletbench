# OCCT ordinary-edge adapter

This adapter runs fresh constant-radius and explicitly bound two-end-radius
`BRepFilletAPI_MakeFillet` calls on the
published source BREP, with the same world-space target descriptions and radius
as each paired SMLib request. It does not implement the source illustrations'
special controls or certify those effects.

## Install and reproduce

Use Python 3.10 or later. The recorded binding is pinned; changing it requires
a new result set.

```sh
python -m venv .venv-occt
source .venv-occt/bin/activate
python -m pip install -r adapters/occt/requirements.txt
python adapters/occt/run.py data/jobs/01.part01.ordinary_control.r8.json --output runs/my-occt/01.part01.ordinary_control.r8
python adapters/occt/run_all.py --jobs data/jobs --output runs/my-occt --workers 4 --timeout 120
```

The version used locally is `cadquery-ocp 7.9.3.1.1` (`OCP.__version__` reports
`7.9.3.1`), corresponding to OCCT 7.9.3. No FreeCAD installation is required.
The runner refuses a different binding version.

## Input and selection

`source_brep` and `source_fixture_json` must be repository-relative files. Their
SHA-256 hashes must match the job. `source_part_indices` select the 0-based direct
children of the original compound, retaining their world placement. A single
selected part is passed to the native API directly. No stitching, healing,
thickening, sewing, radius reduction, or input reconstruction is performed.

Each target resolves to exactly one finite native edge using:

1. Unordered endpoint matching within the declared coverage tolerance.
2. Projection of every world-space sample onto the finite native curve, within
   the declared selector tolerance; finite endpoints are included in minima.
3. Exact length when the job supplies a non-approximate length.
4. Line/circle geometry, including 65 native-to-target samples for a NURBS
   representation, and circle center/radius/normal when supplied. A circle target
   without center/normal requires a native analytic circle.
5. The required number of distinct adjacent support faces.

Documentary source edge aliases never select a native edge. Native edge indices
in summaries are diagnostics produced after geometric selection. Missing and
ambiguous matches are rejected before `Build()`. A requested split-chain
fallback is currently unsupported and is explicitly reported; this adapter does
not guess a subset. OCCT can automatically propagate a selected edge through a
tangent contour; the actual contours and their native edges are recorded.

## Two-end variable-radius controls

Jobs with `variable_start_mm`, `variable_end_mm`, `variable_physical_start` and
`variable_physical_end` call `Add(R1,R2,edge)`. The scalar `radius_mm` is not used
as a constant-radius substitute. Missing fields, unknown variable-law fields,
unmatched endpoints, non-straight edges, non-orthogonal/non-planar supports and
automatically extended contours are rejected explicitly before `Build()`.
The supported scope is one straight edge between two orthogonal planar supports.

Physical endpoints must match the finite native curve ends uniquely. The
driver records the actual first/last points and passed radii, reverses radius
order when required, and verifies that the generated contour's first/last
vertices have the same physical orientation. Case 33 runs from x=-12 to +12;
case 34 runs natively from z=24 to 0, so its native R1/R2 order is reversed.
The actual overload and effective parameters, default internal C1 and rational
fillet representation are recorded for every executed constant or variable job.

Both variable results are read back from exported BREP. The two actual
blend/support contact curves are measured at seven fixed physical spine
stations. Case 33's contact distance changes from 2.4330533365 to 8.6199603936 mm;
case 34's changes from 16.8573826450 at z=0 to 12.2768452001 mm at z=24. Both
physical endpoint pairs match within 1e-4 mm and both outputs are nonconstant.

These rows use `pairing_status=same_physical_two_endpoint_constraints_only`.
The default native interior interpolation is not claimed to match a complete
linear contact-distance law: the measured maximum differences from that linear
reference are 0.2320090146 mm and 0.2453859346 mm respectively. The actual samples
remain in `variable_radius_validation`, and
`full_variable_law_equivalence_verified` is false. The two-end `passed` field
means endpoint and nonconstant-output verification only; the separate
`full_linear_contact_law_passed` field is false for both rows.

The earlier matrix is preserved under `runs/occt-before-variable-fix` with its
historical adapter snapshot. That matrix incorrectly ran these two variable
requests as constant radius, so those archived rows are not parameter-equivalent
paired evidence. Current `runs/fresh-occt` records come from a full fresh rerun
with a single updated adapter hash; the other 84 executed request outcomes and
geometric metrics are compared against the archive explicitly.

`runnable_by_selected_edge_runner` preserves the historical paired-track
admission policy. A blocked request is recorded as `blocked_by_pairing_policy`,
with no native call. This is not a finding that OCCT lacks the capability.
`sheet` is accepted as the historical synonym for `shell`.

## Results and limits

Each output directory contains `summary.json`, captured process logs, and,
after input validation, `before.brep` and `before.mesh.json`. A completed native
result also produces `result.brep` and `result.mesh.json`. The summary records
source/request/adapter hashes, binding and kernel versions, radius, geometric
selection, actual API status, native BREP validity, counts, area, volume, bounds,
BREP write/readback status, and any protected solid-point probes. Volume has no
closed-solid interpretation for a shell.

The outer runner starts one isolated worker and kills it after the configured
wall-clock limit (default 120 seconds). Checkpoints preserve whether the native
call had begun. Timeouts, signals, exceptions, rejected inputs, failed selection,
native rejection, invalid results, and valid ordinary outputs remain distinct.
Reusing an output directory replaces the adapter's prior BREP/mesh artifacts;
fresh execution never reads a historical result.

Meshes contain `vertices` as XYZ triples, 0-based `triangles`, one `face_ids`
entry per triangle, sampled `edges`, and `selected_edges`. They are actual native
triangulations, with face orientation corrected. Mesh errors are reported
separately and do not rewrite native API status. BREP validity is the native
`BRepCheck_Analyzer` check, including geometry checks. No independent kernel,
STEP round trip, global self-intersection oracle, special-feature oracle,
G2 measurement, or human appearance acceptance is implied by an `ok` outcome.

## Recorded fresh run (2026-10-27)

`runs/fresh-occt/index.json` indexes 104 recorded requests, with at most four
workers and a 120-second limit per worker:

| Observation | Count |
| --- | ---: |
| Actual native Build calls | 86 |
| API completed | 65 |
| Native valid ordinary results | 64 |
| Native API rejected | 21 |
| API completed, invalid BREP result | 1 |
| Blocked by paired-track input policy, no native call | 18 |
| Selection failures, exceptions, crashes, or timeouts | 0 |

`24.part01.ordinary_challenge.r12` is the completed-but-invalid result. Its
invalidity remains observable after writing and reading the result BREP. All
86 executed inputs have a before mesh; all 65 completed outputs, including the
invalid one, have a result mesh. All native triangulations completed and mesh
indices were checked for bounds. Protected probes supplied by the jobs showed
no recorded failures; these limited probes are not a whole-shape oracle.

Ten adversarial runner tests passed: a displaced interior sample, a wrong
source part, and a wrong source hash all prevented a native call; a forced
timeout was explicit; and exact line/circle geometry stored as BSplines resolved
to eight unique edges without input reconstruction. Additional tests reject
partial and unhandled variable requests and unmatched physical endpoints, and
measure both forward and reversed endpoint binding with nonconstant output.

```sh
python adapters/occt/test_runner.py
```

## Primary references

- [OCCT 7.9.3 MakeFillet header](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_9_3/src/BRepFilletAPI/BRepFilletAPI_MakeFillet.hxx):
  shell/solid input, constant-radius Add, tangent contour construction, and Build.
- [Pinned OCP release](https://pypi.org/project/cadquery-ocp/7.9.3.1.1/):
  the Python wrapper distribution used for the fresh run.
- [OCCT 7.9.3 fillet-spine law implementation](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_9_3/src/ChFiDS/ChFiDS_FilSpine.cxx):
  native endpoint-radius law construction. Actual output interpolation is
  reported from measurements rather than inferred from the overload name.
