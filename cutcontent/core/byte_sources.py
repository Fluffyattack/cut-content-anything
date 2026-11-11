"""Read-only random access to bytes, wherever they come from.

Every reader in ``cutcontent.formats`` works on a *byte source* instead of a file
name. That way the same ISO 9660 reader can read a plain ``.iso`` file, a raw
CD image with 2352-byte sectors, a compressed ISO image or a file inside a
ZIP archive, and nothing can accidentally open a game file for writing.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path


class ByteSource:
    """Base class: a fixed-size block of bytes that can be read at any offset."""

    size: int = 0
    description: str = ""

    def read_at(self, offset: int, length: int) -> bytes:
        raise NotImplementedError

    def read_all(self, limit: int | None = None) -> bytes:
        length = self.size if limit is None else min(self.size, limit)
        return self.read_at(0, length)

    def close(self) -> None:
        pass


class FileByteSource(ByteSource):
    """A file on disk, opened read-only. Never writes, never truncates."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.description = str(self.path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        self._descriptor = os.open(self.path, flags)
        self.size = os.fstat(self._descriptor).st_size
        self._lock = threading.Lock()

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        if hasattr(os, "pread"):
            chunks = []
            while length > 0:
                chunk = os.pread(self._descriptor, length, offset)
                if not chunk:
                    break
                chunks.append(chunk)
                offset += len(chunk)
                length -= len(chunk)
            return b"".join(chunks)
        with self._lock:  # Windows has no pread
            os.lseek(self._descriptor, offset, os.SEEK_SET)
            return os.read(self._descriptor, length)

    def close(self) -> None:
        if self._descriptor >= 0:
            os.close(self._descriptor)
            self._descriptor = -1

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class LazyFileByteSource(ByteSource):
    """A file on disk that is only opened (read-only) while bytes are being read.
    Used for loose files in game folders, so thousands of files do not keep
    thousands of open file handles."""

    def __init__(self, path: Path | str, size: int | None = None):
        self.path = Path(path)
        self.description = str(self.path)
        self.size = os.path.getsize(self.path) if size is None else size

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        with open(self.path, "rb") as handle:
            handle.seek(offset)
            return handle.read(min(length, self.size - offset))


class MemoryByteSource(ByteSource):
    def __init__(self, data: bytes, description: str = "memory"):
        self._data = bytes(data)
        self.size = len(self._data)
        self.description = description

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0:
            return b""
        return self._data[offset : offset + length]


class SliceByteSource(ByteSource):
    """A window into another byte source, e.g. one file inside an archive."""

    def __init__(self, parent: ByteSource, offset: int, size: int, description: str = ""):
        self.parent = parent
        self.offset = offset
        self.size = max(0, min(size, parent.size - offset))
        self.description = description or f"{parent.description}@{offset}"

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        return self.parent.read_at(self.offset + offset, length)


RAW_SECTOR_SIZE = 2352
USER_DATA_SIZE = 2048
CD_SYNC_PATTERN = b"\x00" + b"\xff" * 10 + b"\x00"


class RawCdSectorSource(ByteSource):
    """Presents a raw CD image (2352 bytes per sector, e.g. a ``.bin`` file with a ``.cue`` sheet)
    as plain 2048-byte data sectors, so the ISO 9660 reader can use it.

    Mode 1 sectors keep user data at byte 16, Mode 2 Form 1 sectors at byte 24.
    The mode is read from the sector header of sector 16 (the volume descriptor).
    """

    def __init__(self, parent: ByteSource):
        self.parent = parent
        self.description = f"{parent.description} (raw 2352-byte sectors)"
        self.sector_count = parent.size // RAW_SECTOR_SIZE
        self.size = self.sector_count * USER_DATA_SIZE
        header = parent.read_at(16 * RAW_SECTOR_SIZE, 16)
        mode = header[15] if len(header) == 16 else 2
        self.user_data_offset = 16 if mode == 1 else 24
        self.mode = mode

    @staticmethod
    def looks_like_raw_cd(parent: ByteSource) -> bool:
        if parent.size < 17 * RAW_SECTOR_SIZE or parent.size % RAW_SECTOR_SIZE:
            return False
        return parent.read_at(16 * RAW_SECTOR_SIZE, 12) == CD_SYNC_PATTERN

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        result = bytearray()
        while length > 0:
            sector, inside = divmod(offset, USER_DATA_SIZE)
            take = min(length, USER_DATA_SIZE - inside)
            raw_offset = sector * RAW_SECTOR_SIZE + self.user_data_offset + inside
            result += self.parent.read_at(raw_offset, take)
            offset += take
            length -= take
        return bytes(result)
