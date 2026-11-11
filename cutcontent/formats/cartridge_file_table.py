"""Read-only headers, file tables and static banner icons of cartridge images
that carry their own file system (a filename table plus a file allocation table).

The layout follows public homebrew toolchain documentation. This reader uses
offsets and file IDs; it never decrypts the secure area, copies the header logo,
or extracts files onto the host file system.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

from cutcontent.core.byte_sources import ByteSource
from cutcontent.core.png_writer import encode_png
from cutcontent.core.virtual_files import VirtualFile

HEADER_SIZE = 0x200
DIRECTORY_ID_BASE = 0xF000
MAXIMUM_DIRECTORIES = 4096
MAXIMUM_FILES = 65536
MAXIMUM_FILENAME_TABLE_BYTES = 8 * 1024 * 1024
BANNER_LANGUAGES = ("Japanese", "English", "French", "German", "Italian", "Spanish", "Chinese", "Korean")


class CartridgeFileTableError(ValueError):
    pass


def crc16(data: bytes) -> int:
    """CRC-16/IBM with initial value 0xFFFF, used by the cartridge header."""
    checksum = 0xFFFF
    for value in data:
        checksum ^= value
        for _ in range(8):
            checksum = (checksum >> 1) ^ (0xA001 if checksum & 1 else 0)
    return checksum


def checked_region(source: ByteSource, offset: int, size: int, label: str, limit: int | None = None) -> bytes:
    if offset < 0 or size < 0 or offset + size > source.size:
        raise CartridgeFileTableError(f"{label} points outside the ROM image.")
    if limit is not None and size > limit:
        raise CartridgeFileTableError(f"{label} is larger than the reader's {limit}-byte limit.")
    data = source.read_at(offset, size)
    if len(data) != size:
        raise CartridgeFileTableError(f"{label} is truncated.")
    return data


@dataclass
class CartridgeFileTableHeader:
    title: str
    game_code: str
    maker_code: str
    unit_code: int
    version: int
    declared_capacity: int
    header_checksum_ok: bool
    regions: dict[str, tuple[int, int]]
    banner_offset: int
    used_rom_size: int
    details: dict = field(default_factory=dict)


def read_header(source: ByteSource) -> CartridgeFileTableHeader:
    data = checked_region(source, 0, HEADER_SIZE, "Cartridge header")
    text = lambda start, size: data[start:start + size].split(b"\0", 1)[0].decode("ascii", errors="replace").strip()
    if data[0x12] not in (0, 2, 3):
        raise CartridgeFileTableError("Unknown cartridge unit code.")
    regions = {}
    for name, offset in (("ARM9 executable", 0x20), ("ARM7 executable", 0x30)):
        file_offset, entry_address, ram_address, size = struct.unpack_from("<IIII", data, offset)
        if not size or file_offset < HEADER_SIZE or file_offset + size > source.size:
            raise CartridgeFileTableError(f"{name} is missing or outside the ROM image.")
        regions[name] = file_offset, size
    for name, offset in (("Filename table", 0x40), ("File allocation table", 0x48), ("ARM9 overlay table", 0x50), ("ARM7 overlay table", 0x58)):
        start, size = struct.unpack_from("<II", data, offset)
        if size and (start < HEADER_SIZE or start + size > source.size):
            raise CartridgeFileTableError(f"{name} points outside the ROM image.")
        regions[name] = start, size
    if data[0x14] > 20:
        raise CartridgeFileTableError("The cartridge capacity code is outside the supported range.")
    return CartridgeFileTableHeader(
        title=text(0, 12) or "Untitled cartridge", game_code=text(12, 4), maker_code=text(16, 2),
        unit_code=data[0x12], version=data[0x1E], declared_capacity=(128 * 1024) << data[0x14],
        header_checksum_ok=crc16(data[:0x15E]) == struct.unpack_from("<H", data, 0x15E)[0],
        regions=regions, banner_offset=struct.unpack_from("<I", data, 0x68)[0],
        used_rom_size=struct.unpack_from("<I", data, 0x80)[0],
        details={"ARM9 entry address": f"0x{struct.unpack_from('<I', data, 0x24)[0]:08X}",
                 "ARM7 entry address": f"0x{struct.unpack_from('<I', data, 0x34)[0]:08X}"},
    )


def read_filename_table(data: bytes, file_count: int) -> dict[int, str]:
    if not data:
        return {}
    if len(data) < 8:
        raise CartridgeFileTableError("The filename table has no root directory.")
    directory_count = struct.unpack_from("<H", data, 6)[0]
    if not 1 <= directory_count <= MAXIMUM_DIRECTORIES or directory_count * 8 > len(data):
        raise CartridgeFileTableError("The filename table has an invalid directory count.")
    pending = [(DIRECTORY_ID_BASE, "")]
    visited = set()
    names = {}
    while pending:
        directory_id, prefix = pending.pop()
        directory_index = directory_id - DIRECTORY_ID_BASE
        if directory_id in visited or not 0 <= directory_index < directory_count:
            raise CartridgeFileTableError("The filename table contains a directory cycle or invalid directory ID.")
        visited.add(directory_id)
        position, file_id = struct.unpack_from("<IH", data, directory_index * 8)
        if position < directory_count * 8:
            raise CartridgeFileTableError("A filename list overlaps the directory table.")
        while True:
            if position >= len(data):
                raise CartridgeFileTableError("A filename list is truncated.")
            descriptor = data[position]
            position += 1
            if not descriptor:
                break
            is_directory, length = bool(descriptor & 0x80), descriptor & 0x7F
            if not length or position + length + (2 if is_directory else 0) > len(data):
                raise CartridgeFileTableError("A filename record is truncated.")
            name = data[position:position + length].decode("utf-8", errors="replace")
            position += length
            if name in (".", "..") or any(character in name for character in ("/", "\\", "\0")):
                raise CartridgeFileTableError("A filename contains path separators or parent traversal.")
            path = prefix + name
            if is_directory:
                child_id = struct.unpack_from("<H", data, position)[0]
                position += 2
                pending.append((child_id, path + "/"))
            else:
                if file_id >= file_count or file_id in names:
                    raise CartridgeFileTableError("A filename references an invalid or duplicate file ID.")
                names[file_id] = path
                file_id += 1
    return names


@dataclass
class CartridgeFileSystem:
    header: CartridgeFileTableHeader
    files: list[VirtualFile]
    named_file_ids: dict[int, str]
    overlay_file_ids: set[int]
    warnings: list[str]
    invalid_file_ids: dict[int, str] = field(default_factory=dict)


def read_file_system(source: ByteSource, container: str, container_path: str, allow_incomplete_files: bool = False) -> CartridgeFileSystem:
    header = read_header(source)
    allocation_offset, allocation_size = header.regions["File allocation table"]
    if allocation_size % 8 or allocation_size // 8 > MAXIMUM_FILES:
        raise CartridgeFileTableError("The file allocation table has an invalid length.")
    allocation = checked_region(source, allocation_offset, allocation_size, "File allocation table", MAXIMUM_FILES * 8)
    file_count = allocation_size // 8
    filename_offset, filename_size = header.regions["Filename table"]
    names = read_filename_table(checked_region(source, filename_offset, filename_size, "Filename table", MAXIMUM_FILENAME_TABLE_BYTES), file_count)
    overlays = set()
    warnings = []
    for label in ("ARM9 overlay table", "ARM7 overlay table"):
        offset, size = header.regions[label]
        if size % 32 or size > MAXIMUM_FILES * 32:
            warnings.append(f"{label} has an invalid size; overlay IDs were not read.")
            continue
        table = checked_region(source, offset, size, label)
        for record in range(0, len(table), 32):
            file_id = struct.unpack_from("<I", table, record + 24)[0]
            if file_id < file_count:
                overlays.add(file_id)
            else:
                warnings.append(f"{label} references missing file ID {file_id}.")
    files = []
    invalid = {}
    for file_id in range(file_count):
        start, end = struct.unpack_from("<II", allocation, file_id * 8)
        if end < start or end > source.size:
            reason = f"File ID {file_id} declares ROM offsets 0x{start:X}..0x{end:X}, outside the available {source.size} bytes. This entry is incomplete or invalid; it cannot be previewed."
            if not allow_incomplete_files:
                raise CartridgeFileTableError(reason)
            invalid[file_id] = reason
            warnings.append(reason)
        name = names.get(file_id, f"Unnamed file ID {file_id}")
        files.append(VirtualFile(name, max(0, end - start), source, start, container, container_path))
    if not header.header_checksum_ok:
        warnings.append("The cartridge header checksum differs. The image may have been modified; its file tables were still checked for bounds.")
    if header.unit_code:
        warnings.append("Only the base header and file system are read; executables of the extended mode and encrypted areas are not analysed.")
    return CartridgeFileSystem(header, files, names, overlays, warnings, invalid)


def read_banner(source: ByteSource, offset: int) -> dict:
    if not offset:
        raise CartridgeFileTableError("This cartridge has no banner.")
    data = checked_region(source, offset, min(0xA40, source.size - offset), "Cartridge banner", 0xA40)
    if len(data) < 0x840:
        raise CartridgeFileTableError("The cartridge banner is truncated.")
    version = struct.unpack_from("<H", data)[0]
    if version not in (1, 2, 3, 0x103):
        raise CartridgeFileTableError(f"Banner version {version} is not supported.")
    titles = {}
    language_count = {1: 6, 2: 7, 3: 8, 0x103: 8}[version]
    for number, language in enumerate(BANNER_LANGUAGES[:language_count]):
        start = 0x240 + number * 0x100
        if start + 0x100 <= len(data):
            title = data[start:start + 0x100].decode("utf-16-le", errors="replace").split("\0", 1)[0].strip()
            if title:
                titles[language] = title
    return {"version": version, "titles": titles, "icon": data[0x20:0x220], "palette": data[0x220:0x240],
            "checksum_ok": crc16(data[0x20:0x840]) == struct.unpack_from("<H", data, 2)[0]}


def banner_icon_png(banner: dict) -> bytes:
    pixels = bytearray(32 * 32 * 4)
    palette = struct.unpack("<16H", banner["palette"])
    for y in range(32):
        for x in range(32):
            tile = (y // 8) * 4 + x // 8
            packed = banner["icon"][tile * 32 + (y % 8) * 4 + (x % 8) // 2]
            colour_index = (packed >> 4) if x % 2 else packed & 15
            colour = palette[colour_index]
            red, green, blue = ((colour >> shift) & 31 for shift in (0, 5, 10))
            start = (y * 32 + x) * 4
            pixels[start:start + 4] = bytes((red * 255 // 31, green * 255 // 31, blue * 255 // 31, 255 if colour_index else 0))
    return encode_png(32, 32, bytes(pixels), channels=4)
