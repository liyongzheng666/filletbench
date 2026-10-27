# Third-party components

- OCCT/OCP: installed separately, not vendored. Follow upstream OCCT LGPL-2.1 with exception and OCP package notices: https://github.com/CadQuery/OCP
- SMLib: source headers/core installed separately from https://github.com/NVIDIA-Omniverse/usd-brep ; caller code preserves applicable SPDX notices. No SDK binary is distributed.
- Three.js and PDF.js: vendored browser code, versions and upstream license files under `web/vendor`.
- Siemens/Parasolid reference artwork and PDF: not distributed. Local browser import only; no vendor endorsement or original CAD equivalence is claimed.
