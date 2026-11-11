"""Where Cut Content Anything stores its own files.

Game folders are only ever read. Everything the tool writes (reports, settings,
agent evidence, demo data) lives in a separate data directory:

- ``CUT_CONTENT_DATA_DIR`` if set, otherwise
- ``$XDG_DATA_HOME/cut-content-anything`` or ``~/.local/share/cut-content-anything``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APPLICATION_NAME = "cut-content-anything"


def data_directory() -> Path:
    configured = os.environ.get("CUT_CONTENT_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    base = os.environ.get("XDG_DATA_HOME")
    base_path = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return base_path / APPLICATION_NAME


def ensure_data_directory() -> Path:
    directory = data_directory()
    for subdirectory in ("reports", "evidence", "demo"):
        (directory / subdirectory).mkdir(parents=True, exist_ok=True)
    return directory


def settings_file() -> Path:
    return data_directory() / "settings.json"


def load_settings() -> dict:
    path = settings_file()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    ensure_data_directory()
    write_json_atomically(settings_file(), settings)


def write_json_atomically(path: Path, content: object) -> None:
    """Writes JSON to a temporary file first so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(content, handle, ensure_ascii=False, indent=1)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
