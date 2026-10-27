# FilletBench viewer

A buildless static viewer. Serve the **web** directory over HTTP:

```sh
python3 -m http.server 8080 --directory web
```

Open http://localhost:8080/#case=08. GitHub Pages can serve the directory unchanged, including from a repository subpath. All browser dependencies are pinned in `vendor/`; no CDN is required.

## Data

The entry point is `data/catalog.json`. Each catalog case links to a case definition; mesh paths are relative to the web root. Mesh JSON uses `vertices`, `triangles`, optional `face_ids`, and optional polyline `edges`. Missing or invalid meshes show an explanation and never a substitute shape.

A result is only displayed as passed when its status explicitly says `pass`, `passed`, or `accepted`. `ok`, `generated`, and `valid` remain “已生成”. A generated ordinary fillet is not acceptance of the reference's advanced semantics.

## Private local references

The public site contains no original PDF, reference screenshots, or composites containing reference imagery. Users may select a PDF or image they own. PDF.js renders locally. The viewer stores the selected PDF and case-specific images in IndexedDB; page and crop mappings are stored in localStorage. No upload endpoint exists. “清除本地文件” removes the selected local file.

`reference.page` is a 1-based physical PDF page. `reference.suggested_crop` is `[x0,y0,x1,y1]` in top-left normalized page coordinates. A suggested crop is used only when the selected PDF SHA-256 equals `reference.expected_pdf_sha256` (the case's `source_sha256` identifies geometry, not the PDF). Users can choose a page and draw a crop in the local reference dialog. Those mappings are bound to the selected file's hash.

## Controls

- Drag: rotate. Scroll: zoom. Right-drag: pan.
- “同步视角”: synchronize the two kernel cameras.
- “建模前 / 目标边”: switch both kernels to their pre-operation or common input mesh; target sample curves appear in magenta.
- Expand button: large single view. Escape: return.
- `/`: search cases. Left/right arrow: adjacent cases.
- Hash links: `#case=08&variant=VARIANT_ID`.
