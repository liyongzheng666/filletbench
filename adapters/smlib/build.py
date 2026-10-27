"""Build only FilletBench consumers; SDK headers/libraries stay outside the repo."""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


class MissingDependency(RuntimeError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configuration():
    if platform.system() not in ("Darwin", "Linux"):
        raise MissingDependency("This consumer build currently supports macOS/Linux C++17 toolchains")
    root_env = os.environ.get("SMLIB_ROOT")
    library_env = os.environ.get("SMLIB_LIBRARY")
    if not root_env or not library_env:
        raise MissingDependency("Set SMLIB_ROOT to the USD-BRep checkout and SMLIB_LIBRARY to its built core shared library")
    root, library = Path(root_env).expanduser().resolve(), Path(library_env).expanduser().resolve()
    includes = [root / "source/SMLib/inc", root / "source/SM_API/inc"]
    if not all(p.is_dir() for p in includes):
        raise MissingDependency("SMLIB_ROOT lacks source/SMLib/inc or source/SM_API/inc")
    if not library.is_file():
        raise MissingDependency("SMLIB_LIBRARY is not an existing shared library")
    compiler = shlex.split(os.environ.get("CXX", "c++"))
    if not compiler or not shutil.which(compiler[0]):
        raise MissingDependency("CXX does not name an available C++ compiler")
    version_header = (includes[0] / "SmConfig.h").read_text()
    version = re.search(r'SM_VERSION_STRING\s+_T\("([^\"]+)"\)', version_header)
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=False)
    return dict(root=root, library=library, includes=includes, compiler=compiler,
                cxxflags=shlex.split(os.environ.get("CXXFLAGS", "")),
                ldflags=shlex.split(os.environ.get("LDFLAGS", "")),
                engine_version=version.group(1) if version else "unverified",
                sdk_source_commit=commit.stdout.strip() if commit.returncode == 0 else None,
                core_library_sha256=sha(library))


def build(config):
    compiler_version = subprocess.run(config["compiler"] + ["--version"],
                                      capture_output=True, text=True, check=True).stdout.splitlines()[0]
    sources = [HERE / n for n in ("ingest.cpp", "smlib_common.h", "native_runner.cpp", "json_value.h", "build.py")]
    header_hash = hashlib.sha256()
    for include in config["includes"]:
        for path in sorted(include.glob("*.h")):
            header_hash.update(path.name.encode())
            header_hash.update(path.read_bytes())
    provenance = dict(engine="SMLib", engine_version=config["engine_version"],
                      version_source="SDK SmConfig.h used to compile the consumers; library identity is its SHA256",
                      sdk_source_commit=config["sdk_source_commit"],
                      core_library_sha256=config["core_library_sha256"],
                      sdk_headers_sha256=header_hash.hexdigest(), compiler=compiler_version,
                      platform=platform.system(), architecture=platform.machine(),
                      consumer_source_sha256={p.name: sha(p) for p in sources},
                      extra_cxxflags=config["cxxflags"], extra_ldflags=config["ldflags"])
    signature = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    build_dir = REPO / ".cache/smlib" / signature[:20]
    build_dir.mkdir(parents=True, exist_ok=True)
    binaries = {}
    with (build_dir / "compile.lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        for target, source in (("ingest", "ingest.cpp"), ("native_fillet_runner", "native_runner.cpp")):
            binary = build_dir / target
            if not binary.exists():
                cmd = config["compiler"] + ["-std=c++17", "-O2", "-DNDEBUG", "-DNOMINMAX", "-DSM_API_EXPORTS",
                      "-DSM_GRAPHICS_CALLBACKS=1", "-Wno-overloaded-virtual", "-Wno-deprecated-declarations"]
                cmd += config["cxxflags"] + ["-I" + str(p) for p in config["includes"]]
                cmd += [str(HERE / source), str(config["library"]), "-Wl,-rpath," + str(config["library"].parent)]
                cmd += config["ldflags"] + ["-o", str(binary)]
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                for suffix, value in (("stdout", result.stdout), ("stderr", result.stderr)):
                    (build_dir / (target + "." + suffix + ".log")).write_text(value)
                if result.returncode:
                    raise RuntimeError("consumer compilation failed; inspect .cache/smlib build logs")
            binaries[target] = binary
    provenance["consumer_binary_sha256"] = {name: sha(p) for name, p in binaries.items()}
    (build_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return binaries, provenance
