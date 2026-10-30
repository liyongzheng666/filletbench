# Blue Lab viewer

The user selected proposal A, 蓝白实验室. The alternative prototypes and the
selection are retained on branch `prototype/blue-layouts-20261029`, commit
`a01f74d`, rather than shipped as alternate production themes.

The main corpus is presented as **基准案例**. Its existing `original` route and
all model, request and evidence identities remain intact. The competing corpus
selector is removed from the main page. Historical experiment URLs still open
their own records and provide a return-to-benchmark action.

The production design uses a white case sidebar, cobalt controls, navy text,
white model canvases and a horizontal PDF/input/OCC/SMLib comparison. Titles and
result status occupy separate header lines. Narrow screens retain horizontal
navigation; enlarged views and evidence drawers keep their existing behavior.

Blue is the interface accent. Failure and warning colors retain their meaning.
Actual result-face colors and selected geometry remain semantic overlays; no
model geometry, numerical result or acceptance state is changed by this skin.
Local PDF/image import remains browser-only. The prototype's local reference
server, theme switcher and alternative CSS are not part of the production site.

The normal address remains `/filletbench/`. The selected benchmark case and
variant are remembered locally and in the current history entry, so refresh
retains the exact selection. Explicit legacy links take precedence, load their
original target, and then clear the address. The copy-location action creates a
compact share link such as `#31/body-r7`; historical experiment links use the
`#history/` prefix and do not replace the last benchmark saved for a fresh visit.
