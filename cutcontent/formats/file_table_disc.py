"""Readers for disc images with a big-endian file system table.

Unencrypted discs of this kind start with a header that holds the six-character
game code, the game name and the signature ``0xC2339F3D``; at 0x420 follow the
offset of the main executable and of the file system table. The table is a flat
list of 12-byte entries (directory flag, name offset, file offset or parent,
size or next entry) followed by the name strings.

A related disc type carries the signature ``0x5D1C9EA3`` and encrypted partitions;
this module only reads its unencrypted header and never decrypts anything.
Folders extracted by an emulator (a ``sys/`` folder with the main executable and a
``files/`` folder) can be read like a PC folder.

``opening.bnr`` banners hold a 96 x 32 picture in the RGB5A3 pixel format,
stored in 4 x 4 tiles; :func:`decode_banner` turns it into a PNG.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from cutcontent.core.byte_sources import ByteSource
from cutcontent.core.png_writer import encode_png
from cutcontent.core.virtual_files import VirtualFile

FILE_TABLE_DISC_MAGIC = 0xC2339F3D
ENCRYPTED_PARTITION_DISC_MAGIC = 0x5D1C9EA3
UNENCRYPTED_DISC = "Disc with file table"
MAIN_EXECUTABLE_PATH = "sys/main.dol"  # where emulators place the main executable when they extract a disc
ENCRYPTED_PARTITION_DISC = "Disc with encrypted partitions"
# Signatures (first four bytes) of compressed or packed disc image formats that are not read.
COMPRESSED_FORMATS = {
    bytes.fromhex("52565a01"): "compressed disc image (signature 52 56 5A 01)",
    bytes.fromhex("57494101"): "compressed disc image (signature 57 49 41 01)",
    bytes.fromhex("57424653"): "packed disc image (signature 57 42 46 53)",
    bytes.fromhex("01c00bb1"): "compressed disc image (signature 01 C0 0B B1)",
}


class DiscFormatError(ValueError):
    pass


@dataclass
class DiscHeader:
    system: str  # UNENCRYPTED_DISC or ENCRYPTED_PARTITION_DISC
    game_code: str
    maker_code: str
    disc_number: int
    version: int
    name: str
    executable_offset: int
    fst_offset: int
    fst_size: int


def compressed_format_name(source: ByteSource) -> str | None:
    return COMPRESSED_FORMATS.get(source.read_at(0, 4))


def read_header(source: ByteSource) -> DiscHeader | None:
    header = source.read_at(0, 0x440)
    if len(header) < 0x440:
        return None
    encrypted_signature, unencrypted_signature = struct.unpack_from(">II", header, 0x18)
    if unencrypted_signature == FILE_TABLE_DISC_MAGIC:
        system = UNENCRYPTED_DISC
    elif encrypted_signature == ENCRYPTED_PARTITION_DISC_MAGIC:
        system = ENCRYPTED_PARTITION_DISC
    else:
        return None
    name = header[0x20:0x400].split(b"\0", 1)[0].decode("shift_jis", errors="replace").strip()
    executable_offset, fst_offset, fst_size = struct.unpack_from(">III", header, 0x420)
    return DiscHeader(
        system=system,
        game_code=header[0:4].decode("ascii", errors="replace"),
        maker_code=header[4:6].decode("ascii", errors="replace"),
        disc_number=header[6],
        version=header[7],
        name=name or "(no name)",
        executable_offset=executable_offset,
        fst_offset=fst_offset,
        fst_size=fst_size,
    )


def disc_executable_size(source: ByteSource, offset: int) -> int:
    """A disc executable is as long as its furthest section (7 code + 11 data sections)."""
    header = source.read_at(offset, 0x100)
    if len(header) < 0x100:
        return 0
    offsets = struct.unpack_from(">18I", header, 0)
    sizes = struct.unpack_from(">18I", header, 0x90)
    return max([0x100] + [section_offset + size for section_offset, size in zip(offsets, sizes) if section_offset and size])


def list_file_table_files(source: ByteSource, header: DiscHeader, container: str, container_path: str) -> list[VirtualFile]:
    if header.system != UNENCRYPTED_DISC:
        raise DiscFormatError("The disc partitions are encrypted; Cut Content Anything does not decrypt them.")
    table = source.read_at(header.fst_offset, header.fst_size)
    if len(table) < 12 or table[0] != 1:
        raise DiscFormatError("the file system table is damaged")
    entry_count = struct.unpack_from(">I", table, 8)[0]
    if entry_count * 12 > len(table):
        raise DiscFormatError("the file system table is truncated")
    names = table[entry_count * 12 :]

    def name_at(offset: int) -> str:
        end = names.find(b"\0", offset)
        return names[offset : end if end >= 0 else len(names)].decode("shift_jis", errors="replace")

    files = [VirtualFile(MAIN_EXECUTABLE_PATH, disc_executable_size(source, header.executable_offset), source, header.executable_offset, container, container_path)]
    directory_stack: list[tuple[str, int]] = [("", entry_count)]
    for index in range(1, entry_count):
        while directory_stack and index >= directory_stack[-1][1]:
            directory_stack.pop()
        prefix = directory_stack[-1][0] if directory_stack else ""
        flags_and_name, first, second = struct.unpack_from(">III", table, index * 12)
        is_directory = flags_and_name >> 24
        name = name_at(flags_and_name & 0xFFFFFF)
        if is_directory:
            directory_stack.append((f"{prefix}{name}/", second))
        else:
            files.append(VirtualFile(f"{prefix}{name}", second, source, first, container, container_path))
    return files


def decode_banner(data: bytes) -> bytes | None:
    """96 x 32 RGB5A3 picture of an opening.bnr file as PNG, or None."""
    if data[:4] not in (b"BNR1", b"BNR2") or len(data) < 0x20 + 96 * 32 * 2:
        return None
    width, height = 96, 32
    rgba = bytearray(width * height * 4)
    position = 0x20
    for tile_y in range(0, height, 4):
        for tile_x in range(0, width, 4):
            for y in range(4):
                for x in range(4):
                    (value,) = struct.unpack_from(">H", data, position)
                    position += 2
                    if value & 0x8000:
                        red, green, blue, alpha = ((value >> 10) & 31) * 255 // 31, ((value >> 5) & 31) * 255 // 31, (value & 31) * 255 // 31, 255
                    else:
                        alpha = ((value >> 12) & 7) * 255 // 7
                        red, green, blue = ((value >> 8) & 15) * 17, ((value >> 4) & 15) * 17, (value & 15) * 17
                    target = ((tile_y + y) * width + tile_x + x) * 4
                    rgba[target : target + 4] = bytes((red, green, blue, alpha))
    return encode_png(width, height, bytes(rgba))


def build_file_table_disc_image(game_code: str, name: str, files: dict[str, bytes], executable: bytes) -> bytes:
    """Builds a small disc image with a file system table. Used by tests."""
    paths = sorted(files)
    tree: dict = {}
    for path in paths:
        node = tree
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = files[path]

    entries: list[list] = [[1, 0, 0, 0]]  # root: directory, name offset, parent, next
    names = bytearray()
    payloads: list[tuple[int, bytes]] = []

    def add(node: dict, parent: int) -> None:
        for key in sorted(node):
            name_offset = len(names)
            names.extend(key.encode("ascii") + b"\0")
            if isinstance(node[key], dict):
                index = len(entries)
                entries.append([1, name_offset, parent, 0])
                add(node[key], index)
                entries[index][3] = len(entries)
            else:
                entries.append([0, name_offset, 0, len(node[key])])
                payloads.append((len(entries) - 1, node[key]))

    add(tree, 0)
    entries[0][3] = len(entries)
    executable_offset = 0x2440
    data_offset = (executable_offset + len(executable) + 0x7FFF) & ~0x7FFF
    image = bytearray(data_offset)
    image[0:6] = game_code.encode("ascii")
    struct.pack_into(">I", image, 0x1C, FILE_TABLE_DISC_MAGIC)
    image[0x20 : 0x20 + len(name)] = name.encode("ascii")
    image[executable_offset : executable_offset + len(executable)] = executable
    for index, payload in payloads:
        entries[index][2] = len(image)
        image += payload + b"\0" * (-len(payload) % 32)
    fst_offset = len(image)
    table = b"".join(struct.pack(">III", (flag << 24) | name_offset, first, second) for flag, name_offset, first, second in entries) + bytes(names)
    image += table
    struct.pack_into(">III", image, 0x420, executable_offset, fst_offset, len(table))
    struct.pack_into(">I", image, 0x42C, len(table))
    return bytes(image)


def build_disc_executable(text: bytes) -> bytes:
    """A disc executable with one code section (used by tests)."""
    header = bytearray(0x100)
    struct.pack_into(">I", header, 0, 0x100)
    struct.pack_into(">I", header, 0x48, 0x80003100)
    struct.pack_into(">I", header, 0x90, len(text))
    return bytes(header) + text
