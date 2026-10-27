# OCCT separate derivative and G2 composition protocols

These drivers make cases 27, 28, 30, 35 and 36 independently runnable through
explicit input preparation and, for case 35, an explicit G2 construction. They
do not replace or relabel the 104 ordinary paired requests. Each trial has its
own `protocol_id`, method, source hash, actual before/result BREP, mesh, and
native readback validity. A derivative is not evidence that the original native
face-face feature protocol was implemented.

## Reproduce

Install the pinned dependency as described in [occt.md](occt.md), then run from
the repository root:

```sh
python adapters/occt/special/run.py --output runs/my-occt-special --timeout 120
python adapters/occt/special/run.py --case 35 --output runs/my-case35 --timeout 120
```

No FreeCAD, pythonocc, PDF, screenshot, external model directory, or local
absolute path is required. Inputs are the published `data/models/NN.brep` files.
`run.py` is the bounded outer driver and constructor; `geometry.py` contains
native mesh/export and actual readback seam/profile checks. One isolated worker
per case has a 120-second default wall-clock limit. Failures and process exit
codes remain visible in per-trial summaries and `process-index.json`.

## Fresh trials recorded on 2026-10-27

All 19 trials below executed and produced valid native BREP results and valid
BREP readbacks. They are derivative/composition results, separate from the
ordinary score table.

| Case | Portable construction / trial | Count | Remaining original-feature protocol gap |
| --- | --- | ---: | --- |
| 27 A | Sew the original two finite support faces; native edge fillets R4/R8 | 2 | Native face-face and trimming controls |
| 27 B | Remove the boss bottom and overlapping floor footprint, sew an open skin; native root fillets R2/R4 | 2 | Propagation semantics; original boss solid is not retained |
| 28 | Clip the two crossing source faces into four sign-defined y/z quadrants, sew and fillet R4 | 4 | Geometric quadrant derivatives are not native left/right-sense calls |
| 30 A/B | Sew original single-row / multi-row partitions and fillet their three shared spine edges R4/R8 | 4 | Partition topology is retained; native master-face selection is not encoded |
| 35 | Same sewn original walls: native R13 and native R13 with internal C2 | 2 | Both are G1 circular controls, and both fail G2-to-planar-support |
| 35 | Three degree-9 Bézier G2 sheets at fixed contact d13, proxy alpha .03/.30/.49 | 3 | Explicit composition; no numeric Parasolid softness law or native softness API |
| 36 | Extend the source support planes to their theoretical line; crop to common 14mm width; native fillets R4/R8 | 2 | Original finite domains change; original four trim modes are not encoded |

For case 36 the untouched source faces are separated and have unequal widths.
The derivative expressly changes their finite domains. Its valid fillet does
not demonstrate `trim_to_walls`, no-trim, short-trim or long-trim on those
original separated faces. Case 27 B likewise exposes the source and derivative
as different surface/solid models.

## Case 35: fixed-contact G2 composition

All five case-35 trials use exactly the same operation-input BREP SHA-256:
`16aaea9628567308664bf05963daf6e2429cbe9828ec426421b590730813fdab`.
Triangulations are omitted from these deterministic BREP exports. The source
dimensions remain width 20, wall height 18 and floor depth 17; the contacts stay
at `(x,0,13)` and `(x,13,0)` for every trial. Remaining wall/floor patches have
height 5 and depth 4.

The composition is linear in x and a degree-9 Bézier profile in yz. With d=13,
h=alpha*d and q=d-2h, its ten profile control points are:

```text
(0,d), (0,d-h),
(q*k/5, q*(1-k/5)) for k=0..5,
(d-h,0), (d,0)
```

The first and last three controls have zero second difference. The endpoints
therefore have nonzero tangent speed and zero profile curvature, matching the
flat supports. Actual readback checks verify the construction rather than
treating this analytic fact or an API setting as full acceptance:

- Both actual common seams are evaluated at 49 interior points through their
  native pcurves. G0, oriented G1, fixed d13 contact position and both principal
  curvatures are checked at the actual seam.
- The readback Bézier surface is sampled at 11 width stations and 257 points
  per profile. Its D2 derivatives provide speed and curvature; a separate
  Bernstein evaluation checks position. Every profile is regular, monotone,
  stays within the contact box, and has zero endpoint curvature within 1e-6.
- The three compositions pass these sampled G0/G1/planar-support G2 checks.
  The maximum observed contact principal-curvature magnitude is below
  5.1e-14 mm^-1. Native circular R13 and internal-C2 R13 both measure
  0.0769230769231 mm^-1 at the contact while the planar support has curvature 0;
  both therefore fail the same G2 test.

The historical softness labels 0.1, 1 and 10 map here to local illustrative
alpha values .03, .30 and .49. This mapping is not a verified Parasolid numeric
softness law, and the generated sheet is not a native MakeFillet softness
result. BREP validity, these sampled readback checks and visible meshes still
do not constitute an independent-kernel global self-intersection check or human
appearance acceptance.

## Provenance and API boundary

The portable OCP code adapts the actual earlier construction methods recorded
in `prepare-d.py`, `build_compositions.py`, `independent-check.py` and
`g2-audit-helpers.py`; their hashes and adaptation details are retained in
`adapters/occt/special/provenance.json`. It reconstructs and reruns the methods
from the published source BREP rather than copying historical result geometry.

The fixed [OCCT 7.9.3 MakeFillet public header](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_9_3/src/BRepFilletAPI/BRepFilletAPI_MakeFillet.hxx)
describes edge contours, radii and internal continuity. This adapter has no
encoding for the original master/propagation/sense/trim/numeric-softness
protocols. That implementation boundary is not a conclusion about all lower
level OCCT algorithms or commercial extensions.

Fresh output is indexed under `runs/fresh-occt-special/`; each trial contains
`source.mesh.json`, `before.mesh.json` and `result.mesh.json`, alongside the
corresponding BREP files. The source view and operation-input view are distinct
so that preparation changes remain inspectable.
