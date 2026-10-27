# Browser dependencies

These fixed versions are served locally. The page makes no runtime CDN requests.

- Three.js 0.170.0: `three.module.min.js`, `OrbitControls.js` (MIT). Source: https://registry.npmjs.org/three/-/three-0.170.0.tgz
- PDF.js / pdfjs-dist 4.10.38: `pdf.min.mjs`, `pdf.worker.min.mjs`, `standard_fonts/` (Apache-2.0; see included notices for fonts). Source: https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-4.10.38.tgz

`OrbitControls.js` resolves its `three` import through the import map in `index.html`.
