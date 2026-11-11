"""A small virtual file system: the list of files inside a game, wherever they live.

A PAK archive, a disc image and a normal folder all end up as the same thing:
a list of :class:`VirtualFile` objects with a path, a size and a way to read
their bytes. Analysis and previews then work the same for every platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cutcontent.core.byte_sources import ByteSource


@dataclass
class VirtualFile:
    path: str  # forward slashes, as stored in the container
    size: int
    source: ByteSource
    offset: int = 0  # offset inside ``source``
    container: str = ""  # human-readable name of the container, e.g. "pak0.pak"
    container_path: str = ""  # file system path of the container on disk

    def read(self, limit: int | None = None) -> bytes:
        length = self.size if limit is None else min(self.size, limit)
        return self.source.read_at(self.offset, length)

    def read_range(self, start: int, length: int) -> bytes:
        if start >= self.size:
            return b""
        return self.source.read_at(self.offset + start, min(length, self.size - start))

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def extension(self) -> str:
        name = self.name
        return name.rsplit(".", 1)[-1].lower() if "." in name else ""

    def location(self) -> dict:
        return {
            "container": self.container,
            "container_path": self.container_path,
            "internal_path": self.path,
            "offset": self.offset,
            "size": self.size,
        }


@dataclass
class ShadowedFile:
    """A file that exists more than once; only ``winner`` is used by the game."""

    winner: VirtualFile
    hidden: VirtualFile


@dataclass
class VirtualFileSystem:
    description: str
    _files: dict[str, VirtualFile] = field(default_factory=dict)
    shadowed: list[ShadowedFile] = field(default_factory=list)

    def add(self, virtual_file: VirtualFile, replaces_existing: bool = True) -> None:
        key = virtual_file.path.lower()
        existing = self._files.get(key)
        if existing is None:
            self._files[key] = virtual_file
        elif replaces_existing:
            self._files[key] = virtual_file
            self.shadowed.append(ShadowedFile(winner=virtual_file, hidden=existing))
        else:
            self.shadowed.append(ShadowedFile(winner=existing, hidden=virtual_file))

    def get(self, path: str) -> VirtualFile | None:
        return self._files.get(path.lower().replace("\\", "/"))

    def files(self) -> list[VirtualFile]:
        return sorted(self._files.values(), key=lambda item: item.path.lower())

    def __len__(self) -> int:
        return len(self._files)

    def __contains__(self, path: str) -> bool:
        return self.get(path) is not None
