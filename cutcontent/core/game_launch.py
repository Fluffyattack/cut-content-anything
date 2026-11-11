"""Prepare a selected level for a real engine running in browser memory.

The server issues a short-lived, unguessable address for exactly this game.
No engine command, host path, or file name supplied by a browser is executed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import time

from cutcontent.core.folders import require_inside_allowed_folder
from cutcontent.core.scan_report import load_report
from cutcontent.core.service import find_item
from cutcontent.platforms.base import PreviewError
from cutcontent.platforms.browser_engines import ENGINE_FILES, engine_directory, quake_browser_engine_status
from cutcontent.platforms.quake_engine import QuakeGameData, resolve_game_directory

MAXIMUM_GAME_BYTES = 512 * 1024 * 1024
MAXIMUM_GAME_FILES = 4096
SESSION_LIFETIME_SECONDS = 4 * 60 * 60
MAP_PATH = re.compile(r"maps/([A-Za-z0-9_./-]+)\.bsp\Z")


@dataclass
class GameLaunch:
    build_path: Path
    game_directory: Path
    engine_directory: Path
    level_name: str
    files: list[tuple[str, Path, int]]
    created_at: float

    def require_current_access(self) -> None:
        if time.monotonic() - self.created_at > SESSION_LIFETIME_SECONDS:
            raise PreviewError("This game session has expired. Open the level again.")
        require_inside_allowed_folder(self.build_path)

    def game_file_path(self, number: int) -> Path:
        self.require_current_access()
        if number < 0 or number >= len(self.files):
            raise PreviewError("Unknown game file.")
        _, path, expected_size = self.files[number]
        resolved = require_inside_allowed_folder(path)
        if self.game_directory not in resolved.parents or path.is_symlink() or resolved.stat().st_size != expected_size:
            raise PreviewError("The game data has changed. Scan the build and open the level again.")
        return resolved

    def read_game_file(self, number: int) -> bytes:
        with self.game_file_path(number).open("rb") as handle:
            return handle.read()

    def read_engine_file(self, name: str) -> bytes:
        self.require_current_access()
        if name not in ENGINE_FILES:
            raise PreviewError("Unknown engine file.")
        target = (self.engine_directory / name).resolve()
        if target.parent != self.engine_directory:
            raise PreviewError("The engine file points outside its build directory.")
        return target.read_bytes()

    def manifest(self) -> dict:
        self.require_current_access()
        return {"map": self.level_name, "files": [{"name": name, "size": size, "url": f"files/{number}"} for number, (name, _, size) in enumerate(self.files)]}


def prepare_game_launch(build_id: str, item_id: str, allow_unverified_engine: bool = False) -> GameLaunch:
    report = load_report(build_id)
    if report is None:
        raise PreviewError("Scan this build first.")
    path = require_inside_allowed_folder(report["path"])
    item = find_item(report, item_id)
    if report["adapter"] != "quake" or item is None or item["kind"] != "map" or item["evidence"]["present_in_data"]["status"] != "yes":
        raise PreviewError("Only an existing Quake level from the latest scan can be opened in Qwasm.")
    match = MAP_PATH.fullmatch(item["reference"].get("path", ""))
    if match is None or any(part in ("", ".", "..") for part in match[1].split("/")):
        raise PreviewError("The level name cannot be passed to the engine.")
    status = quake_browser_engine_status(require_verification=not allow_unverified_engine)
    if not status["available"]:
        raise PreviewError(status["reason"])
    game_path = resolve_game_directory(path)
    game = QuakeGameData(game_path)
    if not game.vfs.get(item["reference"]["path"]):
        raise PreviewError("The level is no longer present. Scan the build again.")
    missing = [name for name in ("progs.dat", "gfx.wad", "gfx/palette.lmp", "gfx/colormap.lmp") if game.vfs.get(name) is None]
    if missing:
        raise PreviewError("This data supports previews but is missing engine resources: " + ", ".join(missing))
    root = game.game_directory.resolve()
    files: list[tuple[str, Path, int]] = []
    if game_path.is_file():
        files.append(("pak0.pak", game_path, game_path.stat().st_size))
    else:
        files += [(f"pak{number}.pak", pak, pak.stat().st_size) for number, pak in enumerate(game.pak_files)]
        for virtual_file in game.vfs.files():
            if virtual_file.container == "loose file":
                files.append((virtual_file.path, Path(virtual_file.container_path), virtual_file.size))
    total_size = 0
    for name, local_path, size in files:
        safe_name = PurePosixPath(name)
        resolved = require_inside_allowed_folder(local_path)
        if safe_name.is_absolute() or any(part in (".", "..") for part in safe_name.parts) or "\\" in name or root not in resolved.parents or local_path.is_symlink():
            raise PreviewError("A game file points outside this game's folder.")
        total_size += size
    if total_size > MAXIMUM_GAME_BYTES or len(files) > MAXIMUM_GAME_FILES:
        raise PreviewError("This game exceeds the browser limit of 512 MiB or 4096 files. Use a desktop engine.")
    return GameLaunch(path, root, engine_directory().resolve(), match[1], files, time.monotonic())
