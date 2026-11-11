"""Reader for Quake PAK archives.

Layout (all numbers little-endian):

- 12-byte header: magic ``PACK``, offset of the directory, length of the directory
- directory: 64-byte entries, each a 56-byte zero-padded file name, the file's
  offset and its size.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from cutcontent.core.byte_sources import ByteSource, FileByteSource
from cutcontent.core.virtual_files import VirtualFile

PAK_MAGIC = b"PACK"
DIRECTORY_ENTRY_SIZE = 64
FILE_NAME_LENGTH = 56


class PakFormatError(ValueError):
    pass


@dataclass(frozen=True)
class PakEntry:
    name: str
    offset: int
    size: int


def is_pak(source: ByteSource) -> bool:
    return source.size >= 12 and source.read_at(0, 4) == PAK_MAGIC


def read_pak_directory(source: ByteSource) -> list[PakEntry]:
    header = source.read_at(0, 12)
    if len(header) < 12 or header[:4] != PAK_MAGIC:
        raise PakFormatError(f"{source.description} is not a PAK archive (missing 'PACK' header)")
    directory_offset, directory_length = struct.unpack("<ii", header[4:12])
    if directory_offset < 12 or directory_length < 0 or directory_offset + directory_length > source.size:
        raise PakFormatError(f"{source.description}: directory lies outside the file")
    if directory_length % DIRECTORY_ENTRY_SIZE:
        raise PakFormatError(f"{source.description}: directory length is not a multiple of 64")
    directory = source.read_at(directory_offset, directory_length)
    entries = []
    for start in range(0, directory_length, DIRECTORY_ENTRY_SIZE):
        raw_name = directory[start : start + FILE_NAME_LENGTH].split(b"\0", 1)[0]
        offset, size = struct.unpack("<ii", directory[start + FILE_NAME_LENGTH : start + DIRECTORY_ENTRY_SIZE])
        if offset < 0 or size < 0 or offset + size > source.size:
            raise PakFormatError(f"{source.description}: entry {raw_name!r} points outside the file")
        entries.append(PakEntry(raw_name.decode("latin-1"), offset, size))
    return entries


def open_pak_files(path) -> list[VirtualFile]:
    """Returns the files inside a PAK archive on disk (read-only)."""
    source = FileByteSource(path)
    container_name = source.path.name
    return [
        VirtualFile(entry.name, entry.size, source, entry.offset, container_name, str(source.path))
        for entry in read_pak_directory(source)
    ]


def build_pak(files: list[tuple[str, bytes]]) -> bytes:
    """Builds a PAK archive in memory. Used for the self-made demo data and tests."""
    body = bytearray()
    directory = bytearray()
    for name, data in files:
        encoded = name.encode("latin-1")
        if len(encoded) >= FILE_NAME_LENGTH:
            raise ValueError(f"file name too long for PAK: {name}")
        offset = 12 + len(body)
        body += data
        directory += encoded.ljust(FILE_NAME_LENGTH, b"\0") + struct.pack("<ii", offset, len(data))
    header = PAK_MAGIC + struct.pack("<ii", 12 + len(body), len(directory))
    return header + bytes(body) + bytes(directory)
