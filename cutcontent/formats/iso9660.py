"""Reader for ISO 9660 file systems (CD and DVD images).

Used for ISO 9660 game discs (CD and DVD images). The primary volume
descriptor sits in sector 16; its root directory record points to directory
extents made of variable-length records (file name, first sector, size, flags).
Sectors are 2048 bytes; raw 2352-byte CD images are converted by
:class:`cutcontent.core.byte_sources.RawCdSectorSource` first.

The file system itself is unencrypted on all these discs. Encrypted executables
inside it are listed but never decrypted.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from cutcontent.core.byte_sources import ByteSource
from cutcontent.core.virtual_files import VirtualFile

SECTOR_SIZE = 2048
DESCRIPTOR_SECTOR = 16
FILE_LIMIT = 50000
DIRECTORY_FLAG = 0x02


class IsoFormatError(ValueError):
    pass


@dataclass
class VolumeInfo:
    system_identifier: str
    volume_identifier: str
    volume_size_sectors: int


def is_iso9660(source: ByteSource) -> bool:
    return source.read_at(DESCRIPTOR_SECTOR * SECTOR_SIZE + 1, 5) == b"CD001"


def read_volume(source: ByteSource) -> tuple[VolumeInfo, tuple[int, int]]:
    descriptor = source.read_at(DESCRIPTOR_SECTOR * SECTOR_SIZE, SECTOR_SIZE)
    if len(descriptor) < 190 or descriptor[1:6] != b"CD001" or descriptor[0] != 1:
        raise IsoFormatError("no ISO 9660 primary volume descriptor in sector 16")
    info = VolumeInfo(
        system_identifier=descriptor[8:40].decode("ascii", errors="replace").strip(),
        volume_identifier=descriptor[40:72].decode("ascii", errors="replace").strip(),
        volume_size_sectors=struct.unpack_from("<I", descriptor, 80)[0],
    )
    root_record = descriptor[156:190]
    root_sector, root_size = struct.unpack_from("<I", root_record, 2)[0], struct.unpack_from("<I", root_record, 10)[0]
    return info, (root_sector, root_size)


def _clean_name(raw: bytes) -> str:
    name = raw.decode("latin-1")
    if ";" in name:
        name = name.split(";", 1)[0]
    if name.endswith(".") and "." not in name[:-1]:
        name = name[:-1]
    return name


def list_files(source: ByteSource, container: str, container_path: str) -> tuple[VolumeInfo, list[VirtualFile]]:
    info, (root_sector, root_size) = read_volume(source)
    files: list[VirtualFile] = []
    pending = [("", root_sector, root_size)]
    visited: set[int] = set()
    while pending:
        prefix, sector, size = pending.pop()
        if sector in visited or size <= 0 or size > 64 * 1024 * 1024:
            continue
        visited.add(sector)
        data = source.read_at(sector * SECTOR_SIZE, size)
        position = 0
        while position < len(data):
            length = data[position]
            if length == 0:
                position = (position // SECTOR_SIZE + 1) * SECTOR_SIZE  # records never cross sectors
                continue
            record = data[position : position + length]
            position += length
            if len(record) < 34:
                break
            extent, extent_size, flags, name_length = struct.unpack_from("<I", record, 2)[0], struct.unpack_from("<I", record, 10)[0], record[25], record[32]
            raw_name = record[33 : 33 + name_length]
            if raw_name in (b"\x00", b"\x01"):
                continue
            name = _clean_name(raw_name)
            path = f"{prefix}{name}"
            if flags & DIRECTORY_FLAG:
                pending.append((path + "/", extent, extent_size))
            else:
                files.append(VirtualFile(path, extent_size, source, extent * SECTOR_SIZE, container, container_path))
                if len(files) >= FILE_LIMIT:
                    return info, files
    return info, files


def build_iso(files: dict[str, bytes], volume_identifier: str = "CUTCONTENT", system_identifier: str = "") -> bytes:
    """Builds a small ISO 9660 image in memory (sub-folders supported). Used by tests."""
    tree: dict = {}
    for path, data in files.items():
        node = tree
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = data

    sectors: list[bytes] = [b"\0" * SECTOR_SIZE] * 18  # system area, descriptors
    def allocate(data: bytes) -> tuple[int, int]:
        start = len(sectors)
        padded = data + b"\0" * (-len(data) % SECTOR_SIZE or 0)
        for offset in range(0, max(len(padded), SECTOR_SIZE), SECTOR_SIZE):
            sectors.append(padded[offset : offset + SECTOR_SIZE].ljust(SECTOR_SIZE, b"\0"))
        return start, len(data)

    def record(name: bytes, sector: int, size: int, is_directory: bool) -> bytes:
        length = 33 + len(name) + (1 if len(name) % 2 == 0 else 0)
        body = struct.pack("<BB", length, 0) + struct.pack("<I", sector) + struct.pack(">I", sector) + struct.pack("<I", size) + struct.pack(">I", size)
        body += bytes(7) + bytes([DIRECTORY_FLAG if is_directory else 0, 0, 0]) + struct.pack("<H", 1) + struct.pack(">H", 1) + bytes([len(name)]) + name
        return body.ljust(length, b"\0")

    def write_directory(node: dict) -> tuple[int, int]:
        entries = []
        for name, value in sorted(node.items()):
            if isinstance(value, dict):
                sector, size = write_directory(value)
                entries.append(record(name.upper().encode("ascii"), sector, size, True))
            else:
                sector, size = allocate(value)
                entries.append(record((name.upper() + ";1").encode("ascii"), sector, size, False))
        body = b""
        for entry in [b"\x00", b"\x01"]:
            body += record(entry, 0, 0, True)
        for entry in entries:
            if len(body) % SECTOR_SIZE + len(entry) > SECTOR_SIZE:
                body += b"\0" * (SECTOR_SIZE - len(body) % SECTOR_SIZE)
            body += entry
        return allocate(body)

    root_sector, root_size = write_directory(tree)
    descriptor = bytearray(SECTOR_SIZE)
    descriptor[0:6] = b"\x01CD001"
    descriptor[6] = 1
    descriptor[8:40] = system_identifier.encode("ascii").ljust(32)[:32]
    descriptor[40:72] = volume_identifier.encode("ascii").ljust(32)[:32]
    struct.pack_into("<I", descriptor, 80, len(sectors))
    descriptor[156:190] = record(b"\x00", root_sector, root_size, True)
    sectors[16] = bytes(descriptor)
    terminator = bytearray(SECTOR_SIZE)
    terminator[0:6] = b"\xffCD001"
    sectors[17] = bytes(terminator)
    return b"".join(sectors)
