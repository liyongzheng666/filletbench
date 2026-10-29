# FilletBench blue UI selection prototype

Question: which information hierarchy and blue visual style should become the
main benchmark viewer? Three structurally different layouts use the existing
viewer route, real case data, actual meshes and validation states.

- A: white/cobalt laboratory with a conventional case sidebar.
- B: compact dark navy engineering workstation.
- C: full-width paper report with a horizontal case-number navigator.

Run `python tools/serve_blue_prototype.py --port 8742`, then open
`http://127.0.0.1:8742/?variant=A#series=original&case=36&variant=trim-to_walls-r8`.
Switch A/B/C using the floating bottom bar or arrow keys. The case/radius stays
in the hash. Original PDF import and actual model interactions remain available.

Optional: `--reference-dir /path/to/local/reference-images` shows locally held
reference PNGs. These files are read only on localhost and are not copied into
the branch. Without that option, use the existing local PDF/image picker.

This is a throwaway selection prototype, not a production implementation.
No benchmark inputs, results, pass/fail status or provenance files are changed.
The main collection is presented as 基准案例, with the existing original-series
data; the competing collection selector is removed from the primary UI.

Decision: the user selected A (蓝白实验室) with the message “蓝白实验室吧”.
The production implementation should retain A's blue/white hierarchy and case
sidebar, use 基准案例 as the main entry, and remove the prototype switcher and
alternate layouts. Alternatives B/C remain on this throwaway branch as context.
Do not merge the prototype wholesale.
