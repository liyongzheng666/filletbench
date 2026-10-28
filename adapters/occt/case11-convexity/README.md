# Case 11 convex shoulder candidate

This isolated reconstruction corrects actual material side, including the red
outer shoulder and the visible pre-existing curved band. Dimensions and hidden
connections are inferred; the source PDF is not bundled or copied to web assets.

Use the repository's pinned `cadquery-ocp` runtime (see `adapters/occt/requirements.txt`)
and Pillow for the raster preview. No FreeCAD, private checkout or absolute local
runtime path is required by these scripts.

## Current suite entry

From a clean checkout, create a Python environment and install the pinned OCCT
binding. The suite route and native three-radius run do not require Pillow.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r adapters/occt/requirements.txt
.venv/bin/python tools/run_original_suite.py --case 11 --out runs/case11-current-repro
```

`python bench.py original --case 11` forwards to the same route when run in that
environment. The direct suite script also accepts `--case11` as a shortcut.
Both this selection and `--all` read `data/case11-convexity/revision.json`, run
R1/R3/R6 on its exact public canonical BREP in an isolated output directory.
The suite passes `--source-brep data/case11-convexity/candidate-v6.brep` and
`--expected-source-sha256` to the builder. It verifies the canonical input and
the output `before.brep` against the registered SHA; the builder retains the
original input bytes. Missing metadata or a mismatch fails explicitly.
This mode is `frozen_exact_revision_input`; no parametric base reconstruction
is executed during the same-input kernel comparison.
The suite's `suite-index.json` records that comparison and points to the
controller log. Each radius has an `attempt.json` under `case11-convexity/`.

For case 11, `--variant` records a requested selection and prints a notice; it
does not limit the three-radius native batch or select a historical source.
An exit code of zero means the controller and source check completed. Read the
individual attempt gates for native BREP/STEP quality: R3/R6 can remain invalid
even when the native builder reports `IsDone=true`.

## Frozen historical replay

The rejected `9959...` reconstruction and its original request bundle remain
available for explicit historical reproduction. They are excluded from current
case 11 and `--all` suite selection. Use a fresh output directory:

```sh
python adapters/occt/original/run.py --requests adapters/occt/original/requests.json --case 11 --output runs/case11-frozen-history
```

The equivalent direct same-input run is:

```sh
python adapters/occt/case11-convexity/build.py --revision candidate-v6 --source-brep data/case11-convexity/candidate-v6.brep --expected-source-sha256 db6c6a783a9e19b1a705a6be8677db296592a0d4a72471a2044261e369b51301 --output runs/case11-canonical-repro
```

## Independent parametric reconstruction and geometry review

Install Pillow in the same environment only when creating the raster HTML
preview. Running `build.py` without `--source-brep` constructs the geometry
parametrically. Different platforms can serialize that reconstruction to
different BREP bytes, even with the pinned binding. Such an output requires
independent geometry and material-side audits and does not automatically
replace the canonical input or enter the same-input comparison.

Use a separate output directory for this reconstruction and its review:

```sh
python adapters/occt/case11-convexity/audit_old.py
python adapters/occt/case11-convexity/build.py --revision candidate-v6 --output runs/case11-parametric-local
python adapters/occt/case11-convexity/audit_final.py runs/case11-parametric-local
python adapters/occt/case11-convexity/preview.py runs/case11-parametric-local
```

The review result is `runs/case11-parametric-local/index.html`. The original red
shoulder remains the unique straight edge with endpoints `(50,0,0)` and
`(50,-60.6,0)` mm. World geometry stays Cartesian; drawing directions affect
only the orthonormal viewer camera. Native ordinary R1/R3/R6 attempts retain all
invalid results and do not claim `repair_fa_X` equivalence or shape acceptance.

Revisions v1-v3 are rejected exploratory history: each had three edges with four
face owners because the wall and panel joined only along curves. OCP BRepCheck
and the selected BOP checks did not flag this. V4 joins the full panel end-cap
and additionally requires exactly two distinct face owners and two loop uses
for every edge. V5 aligns the left opening and B front lip, and preserves the
source's visible A/T junction as a coplanar face partition. V6 closes a small
white projected triangle using a real inferred front web, while preserving the
exposed tongue end face. Independent reference and solid audits favor V6;
human shape acceptance is pending. Earlier reports include the later discovery and are ineligible
for comparison. None of these scripts modifies frozen inputs, old review state,
jobs, SDK sources or published assets.
