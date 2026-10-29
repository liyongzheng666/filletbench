# Case 36 exact-input admission correction

This is the retained small-radius admission baseline. Since v0.5 the current
viewer uses the separately executed R8 face-face results in
`data/case36-faceface`. This admission audit is not a claim that those newer
face-face calls were blocked or never executed.

The active original-series input is the exact frozen BREP `c88672...fbc5a1`.
Its two finite faces remain separate: the vertical face is 14 mm wide and starts
at z=5; the horizontal face is 25 mm wide and starts at y=5. Their shortest gap
is sqrt(50) mm. There is no shared native edge.

The former extended/common-band control changed both finite domains and cropped
the floor to 14 mm. It is preserved as historical derivative evidence by the
viewer, not used as the current input or as evidence for the original trim modes.

R0.5, R1 and R2 are retained. Their positive-quadrant circular contact points lie
outside both original finite faces. The ordinary shared-edge selector admits no
edge; no fillet API is called. `blocked_no_shared_edge` is a runner applicability
result, not a native API failure or a claim that the kernel cannot blend disjoint
faces. No face-face or four-mode trim capability is certified here.

## Reproduce

Install the repository's pinned OCP requirement, then run from its root:

```sh
python tools/run_case36_input.py --output runs/my-case36-exact-input
python tools/audit_case36_input.py
```

The first command copies `before.brep` byte for byte, creates its actual mesh,
measures finite geometry, and records admission for all three radii. A zero
controller exit means those input checks completed; the outcome still records no
native fillet call. Existing evidence directories cannot be overwritten.

`protocol.json` binds the frozen source and case definition, the independently
measured geometry audit, the retained radii/IDs, and the canonical actual summary
hashes. Its `definition_sha256` excludes run bindings to avoid a hash cycle.
Fresh replay directories have their own index and do not rewrite this protocol.

The second command checks current public source/operation equality, displayed
finite domains, parameter identity, actual-summary content, absence of native
calls or fabricated results, and preservation of the superseded derivative.
It does not execute a geometry kernel or accept the source drawing's appearance.
