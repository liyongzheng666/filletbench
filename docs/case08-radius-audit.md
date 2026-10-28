# Case 08 radius audit

This audit reads fresh native artifacts independently. Source dimensions are from the frozen reconstructed BREP, not vendor CAD.

Source SHA-256: `57ea045f7da3735141b7f21f2fbc3e3a51c39933d08a5d7c6e3374e01ab064f9`. Source: 2 faces, 0 solids. A is the unique shared X-line at y=0, z=40, length 100 mm; the original notch top is x=35..65, y=0, z=27. Thus R=13 is the theoretical touch threshold. R=15 predicts z=25 and 2 mm crossing; prediction alone is never an observed result.

| Engine | Nominal R | API | Actual after | Measured R | Wall contact rail z | Notch free-edge z | Native validity | Readback |
|---|---:|---|---|---|---|---|---|---|
| OCCT | 12 | success | 3 faces / 0 solids | 12..12 | 28 | 27 | True | matched |
| SMLib | 12 | success | 3 faces / 0 solids | 12..12 | 28 | 27 | True | matched |
| OCCT | 13 | failed | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |
| SMLib | 13 | failed | 2 faces / 0 solids (retained input) | none | none | 27 | True | matched |
| OCCT | 14 | failed | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |
| SMLib | 14 | success | 4 faces / 0 solids | 14..14 | 26 | 26 | True | matched |
| OCCT | 15 | failed | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |
| SMLib | 15 | success | 4 faces / 0 solids | 15..15 | 25 | 25 | True | matched |
| OCCT | 18 | failed | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |
| SMLib | 18 | success | 4 faces / 0 solids | 18..18 | 22 | 22 | True | matched |

SMLib R13 failure retained the unchanged two-face input, with no measured circular section. Its original z27 notch edge is not a generated fillet boundary. R15 generated two measured R15 side sections and a free edge at x35..65, y0, z25; the original z27 notch top is absent. This is actual 2 mm default-trim encroachment into the original notch outline. R13 failure with an unchanged retained input is recorded separately from a generated blend. For OCCT Build failures there is no after model, so theoretical contact positions are not reported as measurements.

Radius measurements use independent fits of actual native finite cross-section edge samples and native arc lengths. OCCT analytic cylinder radii are also read directly. SMLib D2 surface derivatives are independently reduced to principal curvatures. Nominal input radii are never copied into measured-radius fields.

Shared-rail checks use actual world curves. SMLib pcurve fractions can evaluate at different X positions; those differences are recorded but never treated as G0 gaps. Each owner surface point is checked against the same finite rail carrier and its tangent plane against the rail support. This is a sampled local G0/G1 check, not a global continuity or self-intersection proof.

These runs supply no preserve_notch option. Default trimming, unchanged-input failures, native validity, native persistence, STEP exchange and human appearance acceptance stay separate. No source special-mode equivalence or human acceptance is certified.

SMLib status: audited. Audit consistency passed: True. See `case08-radius-audit.json` for individual gates, measured edge ownership, fit residuals and artifact hashes.

## Published binding audit

The local original-case viewer has five radius views and defaults to R15. Source BREP, actual before meshes, raw and sanitized published summaries, OCCT canonical job hashes, SMLib request-file hashes, after meshes, and measured radius-validation values were cross-checked against the independent audit. R15 binds no OCCT after mesh, and its SMLib result witness exactly matches native free edge 14 at z25 with one owner. The z27 line is an auxiliary guide, and the green witness is separate from original input selection. No kernel was invoked for this publication check.

Publication binding passed: True.
