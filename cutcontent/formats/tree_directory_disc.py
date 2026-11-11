"""Readers for DVD images whose directories are stored as binary trees.

The game partition's volume descriptor sits 32 sectors (0x10000 bytes) into the
partition and starts with a fixed 20-byte signature (``VOLUME_MAGIC``). Plain
images start the partition at offset 0; full disc copies put a video partition
first, so a few known partition offsets are tried.

Directories are binary trees: every entry has a left and a right offset (in
4-byte units, 0 = none), a start sector, a size, attributes and a name.

The unencrypted main executable carries a certificate with the game title in
UTF-16 and the title ID. A later executable format is encrypted or signed and is
never decrypted.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from cutcontent.core.byte_sources import ByteSource
from cutcontent.core.virtual_files import VirtualFile

SECTOR_SIZE = 2048
VOLUME_MAGIC = bytes.fromhex("4d4943524f534f46542a58424f582a4d45444941")  # volume descriptor signature
PARTITION_OFFSETS = (0, 0x18300000, 0xFD90000, 0x2080000)
EXECUTABLE_SIGNATURE = bytes.fromhex("58424548")
DIRECTORY_ATTRIBUTE = 0x10
FILE_LIMIT = 50000


class TreeDirectoryFormatError(ValueError):
    pass


def find_partition(source: ByteSource) -> int | None:
    for offset in PARTITION_OFFSETS:
        if offset + 0x10000 + 20 <= source.size and source.read_at(offset + 0x10000, 20) == VOLUME_MAGIC:
            return offset
    return None


def list_files(source: ByteSource, container: str, container_path: str) -> tuple[int, list[VirtualFile]]:
    partition = find_partition(source)
    if partition is None:
        raise TreeDirectoryFormatError("no XDVDFS volume descriptor found")
    descriptor = source.read_at(partition + 0x10000, 32)
    root_sector, root_size = struct.unpack_from("<II", descriptor, 20)
    files: list[VirtualFile] = []
    pending = [("", root_sector, root_size)]
    seen: set[int] = set()
    while pending and len(files) < FILE_LIMIT:
        prefix, sector, size = pending.pop()
        if sector in seen or size == 0 or size > 32 * 1024 * 1024:
            continue
        seen.add(sector)
        table = source.read_at(partition + sector * SECTOR_SIZE, size)
        stack, visited = [0], set()
        while stack:
            offset = stack.pop()
            if offset in visited or offset + 14 > len(table):
                continue
            visited.add(offset)
            left, right, start, length, attributes, name_length = struct.unpack_from("<HHIIBB", table, offset)
            if left == 0xFFFF:
                continue  # padding
            name = table[offset + 14 : offset + 14 + name_length].decode("latin-1")
            if left:
                stack.append(left * 4)
            if right:
                stack.append(right * 4)
            path = f"{prefix}{name}"
            if attributes & DIRECTORY_ATTRIBUTE:
                pending.append((path + "/", start, length))
            else:
                files.append(VirtualFile(path, length, source, partition + start * SECTOR_SIZE, container, container_path))
    return partition, sorted(files, key=lambda file: file.path.lower())


@dataclass
class ExecutableCertificate:
    title: str
    title_id: str


def read_executable_certificate(data: bytes) -> ExecutableCertificate | None:
    if data[:4] != EXECUTABLE_SIGNATURE or len(data) < 0x178:
        return None
    base_address, = struct.unpack_from("<I", data, 0x104)
    certificate_address, = struct.unpack_from("<I", data, 0x118)
    offset = certificate_address - base_address
    if not 0 < offset < len(data) - 0x5C:
        return None
    title_id, = struct.unpack_from("<I", data, offset + 0x08)
    title = data[offset + 0x0C : offset + 0x0C + 80].decode("utf-16-le", errors="replace").split("\0", 1)[0]
    return ExecutableCertificate(title.strip(), f"{title_id:08X}")


def build_executable_with_certificate(title: str, title_id: int, text: bytes) -> bytes:
    """A minimal main executable with a certificate (used by tests)."""
    base = 0x10000
    image = bytearray(0x200)
    image[0:4] = EXECUTABLE_SIGNATURE
    struct.pack_into("<I", image, 0x104, base)
    struct.pack_into("<I", image, 0x118, base + 0x180)
    struct.pack_into("<I", image, 0x180 + 0x08, title_id)
    encoded = title.encode("utf-16-le")[:80]
    image[0x180 + 0x0C : 0x180 + 0x0C + len(encoded)] = encoded
    return bytes(image) + text


def build_tree_directory_image(files: dict[str, bytes]) -> bytes:
    """Builds a small XDVDFS image (one directory level per folder, used by tests)."""
    tree: dict = {}
    for path, data in files.items():
        node = tree
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = data
    sectors: dict[int, bytes] = {}
    next_sector = [34]

    def allocate(data: bytes) -> int:
        start = next_sector[0]
        count = max(1, (len(data) + SECTOR_SIZE - 1) // SECTOR_SIZE)
        sectors[start] = data.ljust(count * SECTOR_SIZE, b"\0")
        next_sector[0] += count
        return start

    def write_directory(node: dict) -> tuple[int, int]:
        names = sorted(node, key=str.upper)
        records = []
        for name in names:
            value = node[name]
            if isinstance(value, dict):
                sector, size = write_directory(value)
                records.append((name, sector, size, DIRECTORY_ATTRIBUTE))
            else:
                records.append((name, allocate(value), len(value), 0x20))
        # a right-leaning chain is a valid (if unbalanced) binary tree
        table = bytearray()
        offsets = []
        for name, *_ in records:
            offsets.append(len(table))
            table += bytes(((14 + len(name) + 3) // 4) * 4)
        for index, (name, sector, size, attributes) in enumerate(records):
            right = offsets[index + 1] // 4 if index + 1 < len(records) else 0
            entry = struct.pack("<HHIIBB", 0, right, sector, size, attributes, len(name)) + name.encode("latin-1")
            table[offsets[index] : offsets[index] + len(entry)] = entry
        data = bytes(table) or b"\xff" * 16
        return allocate(data), len(data)

    root_sector, root_size = write_directory(tree)
    descriptor = VOLUME_MAGIC + struct.pack("<II", root_sector, root_size) + bytes(8)
    descriptor = descriptor.ljust(0x7EC, b"\0") + VOLUME_MAGIC
    total = next_sector[0]
    image = bytearray(total * SECTOR_SIZE)
    image[32 * SECTOR_SIZE : 32 * SECTOR_SIZE + len(descriptor)] = descriptor
    for start, data in sectors.items():
        image[start * SECTOR_SIZE : start * SECTOR_SIZE + len(data)] = data
    return bytes(image)
