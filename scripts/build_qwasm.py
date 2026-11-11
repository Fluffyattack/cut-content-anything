#!/usr/bin/env python3
"""Build the pinned Qwasm engine outside the checkout (requires Emscripten).

Usage: python3 scripts/build_qwasm.py --source /path/to/Qwasm
Activate Emscripten in the calling shell first. No game data is bundled.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cutcontent.core.settings import data_directory, write_json_atomically

QWASM_COMMIT = "f56b5e71e4be8effede29bae1785a5306dcc0249"


def build(source: Path, output: Path, compiler: str) -> None:
    source, output = source.expanduser().resolve(), output.expanduser().resolve()
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if commit != QWASM_COMMIT:
        raise ValueError(f"Expected Qwasm commit {QWASM_COMMIT}; found {commit}.")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise ValueError("Use a clean Qwasm source checkout for a reproducible build.")
    compiler = shutil.which(compiler) or compiler
    version = subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, EMCC_CORES="1", BINARYEN_CORES="1")
    bridge = output / "qwasm_bridge.o"
    subprocess.run([compiler, "-O2", "-I", str(source / "WinQuake"), "-c", str(Path(__file__).with_name("qwasm_bridge.c")), "-o", str(bridge)], check=True, env=environment)
    flags = (
        "-O2 -sUSE_SDL=2 -sINITIAL_MEMORY=64MB -sSTACK_SIZE=2MB -sALLOW_MEMORY_GROWTH -sDYNAMIC_EXECUTION=0 "
        "-sEXPORTED_RUNTIME_METHODS=FS,UTF8ToString,ccall,addRunDependency,removeRunDependency "
        "-sEXPORTED_FUNCTIONS=_main,_cutcontent_runtime_state -lidbfs.js " + shlex.quote(str(bridge))
    )
    (output / "engine.js").unlink(missing_ok=True)  # relink if only the bridge or link flags changed
    subprocess.run(["make", "-C", str(source / "WinQuake"), "-f", "Makefile.emscripten", "-j1", f"CC={shlex.quote(compiler)}", f"TARGET={output / 'engine.js'}", f"LDFLAGS={flags}"], check=True, env=environment)
    files = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in ("engine.js", "engine.wasm")}
    write_json_atomically(output / "build.json", {"bridge_version": 1, "source": "https://github.com/GMH-Code/Qwasm", "source_commit": commit, "compiler": version, "files": files})
    print(f"Engine built in {output}. Next: run tests/browser_game_acceptance.py to verify and enable it.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=data_directory() / "engines" / "qwasm")
    parser.add_argument("--emcc", default="emcc")
    options = parser.parse_args()
    build(options.source, options.output, options.emcc)
