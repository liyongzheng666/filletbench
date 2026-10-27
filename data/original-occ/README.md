# Original OCC series

This is the frozen source suite from the original individually reviewed OCC
pages. It is independent of the later ordinary-radius/SMLib catalog.

The source revision is
`c4e90452d792e28b1b5a0c5a5237ba7043a235c98abffde445b2dbe70c0f8fa5`.
There are 35 numbered records: 34 model groups and the explanation-only page 32.
Page 29 remains excluded by its original record. The 50 variants explicitly
listed on the original pages retain their IDs and order. Pages without variants
expand their original part/radius plans in order, producing 129 variant records
in total. Planned but unattempted radii retain `not_executed`.

- `index.json` lists case paths, source identities and model/variant counts.
- `cases/NN.json` keeps human notes, original parameter descriptions, method
  distinctions, local reference coordinates and historical evidence.
- `fixtures/<sha256>.brep` contains deduplicated historical reconstructed BREP
  bytes. These are public reconstructed inputs/results, not vendor CAD.
- `history/<original-sha256>.json` contains a sanitized historical JSON record.
  Its filename and `original_sha256` identify the private original JSON bytes;
  `sanitized_sha256` in the manifest identifies the distributed derivative.
- `manifest.json` maps every copied BREP and archived JSON to original hashes
  and sanitized `history:` provenance references.
- `selection-samples.json` stores SHA-bound read-only samples from finite
  source edges. Case 15's two closed circles each have 65 points evaluated from
  their actual source BREP parameter intervals.

`source_brep` is the current reconstructed base. Each variant's
`operation_inputs` identifies its actual saved preparation separately, with its
own hash. `selection.base` and `selection.operation` are bound to those hashes.
World-space target samples are not screen overlays. Component-local topology
IDs and body-to-packet coordinates are labelled explicitly. The annotations for
case 1's upper cliff boundary and case 8's notch outline remain available under
`base_annotation_groups`; they are not additional fillet targets.

Specialized variants are not replaced by smaller ordinary fillets. Native API
controls, explicit OCC compositions, API failures, export failures, failed
quality gates and human acceptance keep separate fields. In particular, case
22 retains generated BREP plus its failed STEP validation, and case 31's blade
input is preserved without an operation. Older ordinary runs whose source
revision differs from the current base remain separate under
`historical_ordinary` and in the full archived summaries.

No fillet is executed by this importer. Historical records are not fresh
runs, and passing a historical geometry check does not certify a source feature
or human appearance acceptance. Reference artwork, screenshots, composite
images, machine absolute paths and SDK binaries are not distributed. The
`reference` object only carries client-local PDF identity and crop coordinates
already present in the public case metadata.

To regenerate from the authorized private source tree:

```sh
python3 tools/import_original_occ.py --source-root <private-source-root>
```

The importer checks the pinned review hash before writing and verifies that the
source remains unchanged afterward. It does not modify the source tree. A fresh
circle-sample extraction needs an OCP Python runtime; subsequent imports can use
the distributed samples only when the source SHA and edge identity match.
