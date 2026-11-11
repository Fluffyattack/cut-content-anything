"""Content-based file recognition.

Adapters recognise game data by what is inside a file (signatures, header
checksums, file system descriptors), not by its file-name extension. This module
reads the first bytes of a file once, read-only, and keeps them in a small cache,
so several adapters can inspect the same file during a library search without
reading it again.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# Documents, media, saves and PC programs are never cartridge or disc images;
# skipping them keeps a library search fast on slow disks.
EVERYDAY_FILE_EXTENSIONS = {
    "txt", "md", "json", "xml", "html", "htm", "css", "js", "py", "png", "jpg", "jpeg", "gif", "bmp", "webp",
    "ogg", "mp3", "wav", "flac", "pdf", "cfg", "ini", "log", "csv", "yml", "yaml", "nfo", "sh", "bat", "srt",
    "sav", "srm", "state", "lnk", "url", "db", "sqlite", "torrent", "exe", "dll", "so",
}
MINIMUM_GAME_FILE_SIZE = 512
HEAD_SIZE = 0x8000 + 0x800  # enough for cartridge headers and an ISO 9660 volume descriptor


@lru_cache(maxsize=256)
def _cached_head(path: str, size: int, modified_nanoseconds: int, length: int) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(length)


def file_head(path: Path, length: int = HEAD_SIZE) -> bytes:
    """The first ``length`` bytes of a file (cached by path, size and modification time)."""
    information = os.stat(path)
    return _cached_head(str(path), information.st_size, information.st_mtime_ns, length)


def read_at(path: Path, offset: int, length: int) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(offset)
        return handle.read(length)


def could_be_game_file(path: Path) -> bool:
    """Cheap pre-check before any content is read."""
    if not path.is_file():
        return False
    extension = path.suffix.lower().lstrip(".")
    if extension in EVERYDAY_FILE_EXTENSIONS:
        return False
    try:
        return path.stat().st_size >= MINIMUM_GAME_FILE_SIZE
    except OSError:
        return False
