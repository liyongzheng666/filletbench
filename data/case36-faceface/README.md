# Case 36: finite-input face-face fillets and four end policies

The source remains the exact two separated finite faces `c88672...fbc5a1`:
vertical width14 at y0/z5..25, horizontal width25 at z0/y5..23. R8 is a
declared reconstruction test radius, not a dimension recovered from the PDF.
Both nominal contact rails lie within the supplied finite support domains.

The four primary views compare **OCCT7.9.3 explicit constructions** with
**SMLib10.0.0 native surface/surface trim calls**. A fifth view independently
records **OCCT7.8.1 native rolling-ball walking/AppSurf**. That native route has
no four-trim enum; its naturally short-like end is not four native trim passes.

| End policy | OCCT explicit result | SMLib native result |
|---|---|---|
| to_walls | Vertical rail x±7, horizontal rail x±12.5; interpolated UV end boundaries | BEVEL measured with the same two endpoint ranges |
| no | Declared finite working interval x±20 | NONE actually returns x±14; no caller post-crop |
| short | Both rails x±7 | MINIMAL actually returns both rails x±7 |
| long | Both rails x±12.5 | MAXIMAL actually returns both rails x±12.5 |

The results are independent blend patches, not assembled solids or modified
wall sheets. Gray wall boundaries in the viewer are source reference guides.
Matching to_walls endpoints do not mean identical end curves:8193 read-only
native queries per end reveal an observed same-theta X difference of about
0.05614980mm. This sampled correspondence difference is not a certified
continuous maximum or Hausdorff distance. The complete comparison is hash-bound
separately and applies only to the actual measured BREP/SMB geometries.
Native SMLib base_trim0 nevertheless splits the wall **call copies' topology**;
their area, bounds and finite-domain samples remain preserved. Immutable source
files and input representations before the call are recorded separately.

Actual BREP/STEP or SMB readback, native geometry exports, sampled radius/G0/G1
and physical end domains are independently measured. Local endpoint conditions
passing does not certify general Parasolid trim-law equivalence, all surface
self-intersections or human appearance. In particular, the explicit to_walls
law is a declared UV interpolation for these rectangular supports.

`protocol.json` binds all nine executed records and public meshes to the source,
parameters and independent audit. A partial replay registers its own real index;
it cannot claim that cached results were executed by a short partial index.

See the repository README for the separate OCCT composition, native control and
SMLib replay commands. The older small-radius admission checks remain available
in `data/case36-input`; they are historical checks, not the current R8 result.
