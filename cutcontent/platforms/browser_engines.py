"""Locate a separately built Qwasm engine and its successful browser test.

Engine binaries stay in application data, outside the source repository.
The browser test binds its result to the exact JavaScript and WebAssembly files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from cutcontent.core.settings import data_directory

QWASM_DIRECTORY_VARIABLE = "CUT_CONTENT_QWASM_DIR"
QWASM_SOURCE = "https://github.com/GMH-Code/Qwasm"
ENGINE_FILES = ("engine.js", "engine.wasm")


def engine_directory() -> Path:
    configured = os.environ.get(QWASM_DIRECTORY_VARIABLE, "").strip()
    return Path(configured).expanduser().resolve() if configured else data_directory() / "engines" / "qwasm"


def quake_browser_engine_status(require_verification: bool = True) -> dict:
    directory = engine_directory()
    status = {"engine": "Qwasm", "source": QWASM_SOURCE, "available": False, "tested": False, "documentation": "docs/GAME_LAUNCH.md"}
    try:
        manifest = json.loads((directory / "build.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("The engine build manifest must be a JSON object.")
        actual = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in ENGINE_FILES}
        if manifest.get("bridge_version") != 1 or manifest.get("files") != actual:
            raise ValueError("The engine files do not match their build manifest. Rebuild the engine.")
        if (directory / "engine.wasm").read_bytes()[:4] != b"\0asm":
            raise ValueError("The engine.wasm file is not a WebAssembly binary.")
    except (OSError, ValueError, TypeError) as error:
        status["reason"] = f"No compatible Qwasm build is installed. Build it with scripts/build_qwasm.py; see docs/GAME_LAUNCH.md. ({error})"
        return status
    try:
        verification = json.loads((directory / "browser-verification.json").read_text(encoding="utf-8"))
        status["tested"] = isinstance(verification, dict) and verification.get("files") == actual and verification.get("passed") is True
    except (OSError, ValueError, TypeError):
        pass
    status["build_directory"] = str(directory)
    status["available"] = status["tested"] or not require_verification
    status["reason"] = "Start the selected level in Qwasm. Progress stays in the browser; original game files are read-only." if status["available"] else "The engine has been built, but its browser test has not passed yet. Run tests/browser_game_acceptance.py."
    return status
