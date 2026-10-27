# SMLib adapter

The adapter rebuilds the selected **1-based** `component_index` from the published
exact rational NURBS fixture, validates the native input and its readback, checks
independent Cox-de Boor sample evaluations and source area/volume/bounds, and runs
one native fillet process per job. It performs no automatic healing, stitching,
thickening or component merging. The JSON fixture is an explicit exchange format;
this route does not use NVIDIA's USD importer.

## Dependency and build

Python 3.10+ and a C++17 GCC/Clang-compatible toolchain are required. The consumer
build supports macOS and Linux; the macOS arm64 path has been exercised. No
architecture is forced. Windows/MSVC and Linux have not been exercised here.
SDK headers and shared libraries are supplied by the user and are not included
in this repository.

The reference source is [NVIDIA USD-BRep](https://github.com/NVIDIA-Omniverse/usd-brep)
at commit [`c9c5979f04cea8c38213004d4f04df0dcfb40d05`](https://github.com/NVIDIA-Omniverse/usd-brep/tree/c9c5979f04cea8c38213004d4f04df0dcfb40d05),
whose `SmConfig.h` reports SMLib `10.0.0`. Build the standalone core and native API
closure used by this adapter with CMake 3.20+:

```sh
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/NVIDIA-Omniverse/usd-brep.git ../usd-brep
git -C ../usd-brep checkout c9c5979f04cea8c38213004d4f04df0dcfb40d05
export SMLIB_ROOT="$(cd ../usd-brep && pwd)"
cmake -S adapters/smlib/core -B .cache/smlib-core \
  -DSMLIB_ROOT="$SMLIB_ROOT" -DCMAKE_BUILD_TYPE=Release
cmake --build .cache/smlib-core --parallel 4

# macOS:
export SMLIB_LIBRARY="$PWD/.cache/smlib-core/libsmlib_filletbench.dylib"
# Linux instead:
# export SMLIB_LIBRARY="$PWD/.cache/smlib-core/libsmlib_filletbench.so"
```

Run these commands from the FilletBench repository root. `CXX` can select the
consumer compiler; `CXXFLAGS` and `LDFLAGS` add shell-style argument lists. For the
core build, select its compiler with CMake's `-DCMAKE_CXX_COMPILER=...`. Consumer
and core must have compatible C++ ABI, architecture and `SM_GRAPHICS_CALLBACKS=1`
configuration. The standalone build compiles `source/SMLib/src` and
`source/SM_API/src`, excluding the unused USD-dependent `SmApiImportExport.cpp`.
It does not build USD or Python bindings. NVIDIA's complete product build is
described in its own README and is a separate route.

`SMLIB_ROOT` points to the source checkout root, containing `source/SMLib/inc` and
`source/SM_API/inc`. `SMLIB_LIBRARY` points to a matching existing shared core
library. Missing configuration, headers, compiler or library produces
`missing_dependency`; the adapter never substitutes recorded results.

## Run a job or the matrix

```sh
python3 adapters/smlib/run.py data/jobs/01.part01.ordinary_control.r8.json \
  --output runs/example-smlib

python3 adapters/smlib/batch.py --include-blocked --workers 4 \
  --output runs/fresh-smlib
```

Each output directory must be fresh. The batch can use `--resume` to preserve
existing summaries and run missing jobs. Default batch scope includes jobs with
`runnable_by_selected_edge_runner=true`; `--include-blocked` additionally emits
explicit `adapter_not_ready` summaries. Neither option makes an unsupported
surface-pair or source-feature contract executable.

The runner verifies job-declared BREP and fixture SHA256 values before importing.
`source_brep` and `source_fixture_json` are resolved relative to repository root;
absolute or escaping source paths are rejected. Native input is rebuilt at run
time; `input_smb` from an old run is never accepted as the job's input. Consumers
and inputs are cached under ignored `.cache/`. The input cache identity includes
fixture SHA256, component index, core-library SHA256, importer-binary SHA256,
encoder-source SHA256 and verifier-source SHA256; the cached native file is
checked before reuse. Remove `.cache/smlib-inputs` to force every input to be
constructed again. Every fillet operation uses a fresh native process.

The import and fillet subprocesses each have a watchdog, default and maximum
60 seconds. Complete stdout/stderr, native phases, candidate files, selection,
raw API statuses, native readback, junction samples and mesh evidence are kept,
including on failure where available. Native signals and timeouts remain visible.
`SM_SUCCESS` is tested as the SDK enum value (observed `1000`), not assumed zero.

## Evidence and limits

`summary.json` records the engine, header-reported version, source commit, core
and consumer hashes, source lineage, import gates, geometric selection and
operation/readback outcomes. `binary-provenance.json` distinguishes the version
in the compile-time headers from the shared library's hash identity; a version
string alone does not establish a library build's provenance.

The main outcomes are `missing_dependency`, `adapter_not_ready`, `import_failed`,
`selection_failed`, `native_candidate`, `native_api_failed_candidate`,
`native_phase_crash` and `timeout`. A successful API call is a candidate result.
It does not certify protected finite regions, global self-intersection, source
special features or G1/G2 continuity. Sampled equivalence is not a global analytic
proof. Full feature acceptance remains false until its independent contract
oracles are supplied and evaluated.

The portable validation run exercised all 104 published jobs: 86 reached the
native fillet call after input admission, and 18 returned `adapter_not_ready`.
Of the 86 native calls, 61 returned API success, 23 returned API failure with a
retained candidate, and 2 crashed in the native phase. These are execution
outcomes, not 61 feature acceptance passes. The initial importer used an area
wrapper whose precision clamp caused false admission rejections; the delivered
importer instead integrates actual trimmed faces directly with
`ComputePreciseProperties` at relative `1e-9` and preserves the original metrics
thresholds. The final matrix had no import-gate rejection.

After rebuilding the viewer, validate every published native input/result mesh
and its raw-summary SHA256 lineage with:

```sh
python3 adapters/smlib/check_mesh_lineage.py
```

The check compares complete published mesh payloads with their respective raw
`before.mesh.json`/`result.mesh.json` and geometry-edge records. It permits an
unchanged failed candidate; input/output equality alone is not evidence of a
mapping error. The recorded matrix passed all 312 lineage checks. A temporary
R18 input-to-result misbinding was also injected and detected by this check.

All generated binaries, native SMB files and machine build logs remain local in
ignored output/cache folders. The public repository contains adapter source,
fixtures, jobs and shareable evidence; it does not require or include source-PDF
images. Keep source references browser-local when loading the optional PDF.
