"""Which folders Cut Content Anything may read, and the check that enforces it.

The web interface may only open files inside *allowed folders*. A folder becomes
allowed in exactly one of these ways:

1. ``CUT_CONTENT_ROM_DIR`` (one or more paths separated by ``os.pathsep``).
2. A ROM folder on an already mounted retro-gaming partition labelled "SHARE",
   e.g. ``/userdata/roms`` on the gaming system itself or ``/media/<user>/SHARE/roms``
   when that partition is mounted on another Linux machine. Only these fixed
   patterns are checked; there is no search across the whole disk.
3. ``cutcontent folders add <path>`` (stored in the settings file).
4. The tool's own demo folder (self-made and openly licensed test data).

The web interface cannot add folders by itself.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from pathlib import Path

from cutcontent.core.settings import data_directory, load_settings, save_settings

ROM_FOLDER_ENVIRONMENT_VARIABLE = "CUT_CONTENT_ROM_DIR"

# Fixed, shallow patterns for ROM folders on an already mounted "SHARE" partition.
MOUNTED_ROM_SHARE_PATTERNS = (
    "/userdata/roms",
    "/media/*/SHARE/roms",
    "/run/media/*/SHARE/roms",
    "/mnt/SHARE/roms",
    "/mnt/*/SHARE/roms",
)


@dataclass
class AllowedFolder:
    path: Path
    source: str
    exists: bool
    readable: bool

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "source": self.source,
            "exists": self.exists,
            "readable": self.readable,
        }


def demo_folder() -> Path:
    return data_directory() / "demo"


def environment_rom_folders() -> list[Path]:
    value = os.environ.get(ROM_FOLDER_ENVIRONMENT_VARIABLE, "")
    return [Path(part).expanduser() for part in value.split(os.pathsep) if part.strip()]


def detect_mounted_rom_share_folders() -> list[Path]:
    found = []
    for pattern in MOUNTED_ROM_SHARE_PATTERNS:
        for match in sorted(glob.glob(pattern)):
            if os.path.isdir(match):
                found.append(Path(match))
    return found


def configured_folders() -> list[Path]:
    return [Path(entry) for entry in load_settings().get("allowed_folders", [])]


def allowed_folders(include_demo: bool = True) -> list[AllowedFolder]:
    candidates: list[tuple[Path, str]] = []
    candidates += [(path, f"environment variable {ROM_FOLDER_ENVIRONMENT_VARIABLE}") for path in environment_rom_folders()]
    candidates += [(path, "mounted SHARE partition ROM folder") for path in detect_mounted_rom_share_folders()]
    candidates += [(path, "added with 'cutcontent folders add'") for path in configured_folders()]
    if include_demo:
        candidates.append((demo_folder(), "demo data of Cut Content Anything"))

    result: list[AllowedFolder] = []
    seen: set[str] = set()
    for path, source in candidates:
        resolved = os.path.realpath(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        exists = os.path.isdir(resolved)
        readable = exists and os.access(resolved, os.R_OK | os.X_OK)
        result.append(AllowedFolder(Path(resolved), source, exists, readable))
    return result


def add_configured_folder(path: Path) -> Path:
    resolved = Path(os.path.realpath(path.expanduser()))
    if not resolved.is_dir():
        raise ValueError(f"Folder does not exist: {resolved}")
    settings = load_settings()
    folders = settings.setdefault("allowed_folders", [])
    if str(resolved) not in folders:
        folders.append(str(resolved))
    save_settings(settings)
    return resolved


def remove_configured_folder(path: Path) -> bool:
    resolved = os.path.realpath(path.expanduser())
    settings = load_settings()
    folders = settings.get("allowed_folders", [])
    if resolved not in folders:
        return False
    folders.remove(resolved)
    save_settings(settings)
    return True


class FolderPermissionError(PermissionError):
    """Raised when a path lies outside every allowed folder."""


def is_inside(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # different drives on Windows
        return False


def require_inside_allowed_folder(path: Path | str, folders: list[AllowedFolder] | None = None) -> Path:
    """Returns the resolved path if it lies inside an allowed folder, otherwise raises.

    Symbolic links are resolved first, so a link inside an allowed folder that points
    somewhere else is rejected as well.
    """
    folders = allowed_folders() if folders is None else folders
    resolved = os.path.realpath(os.fspath(path))
    for folder in folders:
        if folder.exists and is_inside(resolved, str(folder.path)):
            return Path(resolved)
    raise FolderPermissionError(
        f"'{resolved}' is not inside an allowed folder. Allow it with "
        f"'cutcontent folders add <folder>' or {ROM_FOLDER_ENVIRONMENT_VARIABLE}."
    )
