# Original OCC composition replay

These drivers reproduce the recorded original review recipes, using the frozen
`data/original-occ` source BREP bytes and original variant IDs. They are separate
from the ordinary radius matrix. They execute geometry operations from source to
new results; historical results are used only as independent comparison oracles.

The fresh runtime is pinned `cadquery-ocp==7.9.3.1.1` / OCCT 7.9.3. The original
runtime was FreeCAD 1.2 with local OCCT 7.8.1. This port preserves recorded source
hashes, selected entities, parameters and mathematical recipes; it does not claim
the original runtime was rerun. Original script hashes and any version gap remain
in the per-execution summaries.

Run from the repository root using a Python environment with the pinned OCCT
requirements installed. Choose new output directories for repeat execution:

```sh
python adapters/occt/original-compositions/run.py --case 18 --variant sheet-r8 --output runs/replay-case18-sheet-r8
```

The umbrella CLI accepts cases 16/17/18/19/20/21/23/33/34. Omit `--variant` to
verify every original review view for the chosen case. Its static
`protocol-manifest.json` maps all 33 original variant IDs to immutable driver
hashes, arguments and expected result summaries, without requiring old run
directories. Variant selection controls the reported view; the existing drivers
retain their original batch execution scope, recorded in `routing-summary.json`.
Cases33/34 therefore execute their seven shared recipes even when one view is
requested. Success requires the requested summaries, actual valid BREP readback
and native meshes; a zero process exit code is insufficient.

The direct immutable driver commands remain available:

```sh
python adapters/occt/original-compositions/case16_23.py --out runs/original-occ-compositions
python adapters/occt/original-compositions/case17_19.py --output runs/original-occ-compositions
python adapters/occt/original-compositions/case33_34.py --out runs/original-occ-compositions
python adapters/occt/original-compositions/build_index.py
```

`runs/original-occ-compositions/index.json` binds each recorded review variant to
its actual fresh summary and result artifacts. Every successful execution has
before/result BREP and standard native-triangulation meshes. A comparison view
may use two executions; an alternate clean view may reuse one execution. The
index counts these views separately from unique executions.

| Original case | Recorded procedure | Fresh verification |
| --- | --- | --- |
| 16 | Native single-edge R6 removal tools, exact A6/B14/C3 stop-box clipping, sequential subtraction | Analytic stopped-cylinder volume, retained vertex and vertical-edge distance probes, historical trim-curve distances and area/volume |
| 17 | Partition at the existing x29 cap, native left-root fillet, fuse untouched right body | Analytic added volume and symmetric Boolean difference against original result |
| 18 | Native left-root addition clipped by the actual independent plane or folded sheet | Finite cap containment, actual cap faces and required sheet-fold crossing, symmetric historical difference |
| 19 | Declared support, slot-mouth extensions, real finite edge/face intersection and retained-side clipping | Intersection at [29,22,20], R5 refusal control with 2mm finite-entity gap, symmetric historical difference |
| 20 | Fresh side and full-front native references; No from side-removal; Yes from measured bridge subtraction | Geometry against fresh native references and original results; independently constructed patch algorithm remains false |
| 21 | Fresh native free-propagation tools, split left/right and clip declared associations at tangent topology y18 | Analytic cap areas/count, torus and vertical-extra counts, rear-region identity and historical geometry |
| 23 | Exact revolved quarter-circle additions, genuine overlap union, recorded secondary seam fillets | Actual common volume, footprint overlap, analytic notch and normal jump, historical geometry; secondary R1 failures retained |
| 33 | Original two distinct variable rational quarter-ellipse ranges | Actual surface readback versus independent rational Bernstein evaluation and historical geometry |
| 34 | Original absolute rho .25/.5/.75 and relative .5 rational profiles | Actual surface readback versus independent rational Bernstein evaluation and historical geometry |

For 16/20/21/23 the historical check samples 17 points on every actual trim edge
in both directions and measures distance to the other BREP, with independent
area/volume differences. For 17–19 the comparison performs both Boolean
differences. For 33–34 it also checks sampled trimmed surface positions and the
original mathematical profile. These are sampled or numerical gates, not exact
geometric proofs.

The recorded source-feature controls are still false: these compositions do not
expose native automatic `cap_data`, `limit_topols`, `limit_topols_unders`, patch,
`ov_smooth`, asymmetric ranges or rho APIs. Radius values and dimensions were
chosen demonstrations where the source did not specify them. The case21 front
vertical propagation remains a source-uncertain extra range. Case23 secondary
fillet export is distinct from G1 or self-intersection acceptance. No STEP
roundtrip, new human appearance approval, or SMLib parity is claimed here.

The completed run binds 33 original review views to 31 unique executions. All
33 views have a successful fresh result. Across the full 37 execution attempts,
35 succeeded and the two extra case23 secondary R1 fillets failed. The index
keeps those attempts separate from the original current review views.

For cases17–19, all 10 results (nine compositions and the R5 control) are valid
single solids with BREP readback and native meshes. Their fresh-versus-historical
Boolean differences in both directions are 0mm³. The largest total-volume
residual is about 4.91e-7mm³ for sheet R8. Case18 actual cap faces lie within the
finite supplied cap; sheet R8 crosses the required fold. Case19 R5's finite-edge
and finite-face tests both find no intersection and a 2mm distance. The
`direction-right` result remains the recorded counterexample, not a recovered
source fin direction.

Case33/34 frozen numerical parameters come from original execution summaries.
Later `parameters.json` files were overwritten by source-fit schemas; the
contract preserves the original execution values and their summary hashes.
Case33 constructs a degree-1-by-degree-2 rational quarter-ellipse surface with
independent linear a/b laws and finite planar supports, yielding the original
three-face open shell. Case34 keeps the original contact law and minimal hidden
closure proxy. Absolute rho .25/.5/.75 use middle weights 1/3, 1 and 3; relative
rho .5 uses sqrt(1/2), the symmetric 90-degree circular special case. General
relative-rho mapping remains unclaimed.

Case33 `asymmetric-clean` reuses the `asymmetric-ranges` execution.
Case34 `rho-050-compare` displays `relative-050` and `absolute-050` together.
Those seven review views use five unique composition executions. The native
controls add two more executions and two more views. Case33's native control
uses original operation-input edge1 with endpoint radii
2.433053336500925 and 8.619960393556429. Case34's native control uses original
edge4 and the original contour top-to-bottom endpoint radii
12.276845200098565 and 16.857382645040378. Orientation mismatches are rejected;
radii are not silently swapped.

All five case33/34 compositions passed 715 actual surface readback samples
against independent rational Bernstein evaluation, with maximum positional
residual below 8e-15mm. Historical trimmed-shape distance samples agree within
1.1e-14mm and area/volume deltas are zero. Both native controls passed actual
seam pcurve G0/G1 checks; case34 end caps correctly require only G0. Their
historical sampled distances are below 5.5e-14mm. The original linked main
scripts exist and are hashed, but their historical execution summaries did not
record a main-script hash. Their provenance status remains
`source_present_without_recorded_main_hash`; no exact source-version match is
invented.
