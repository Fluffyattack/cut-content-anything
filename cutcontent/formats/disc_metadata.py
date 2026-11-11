"""Small metadata formats found on ISO 9660 game discs.

- Parameter files (signature ``00 50 53 46``): a key/value table with the title,
  the disc ID and more.
- Compressed ISO images (signature ``43 49 53 4F``, version 1): the image is split
  into blocks; each block is stored raw or deflate-compressed. Reading needs no keys.
- Boot configuration text (``BOOT = ...`` / ``BOOT2 = ...``) naming the boot executable.
- Executables: plain CD executables and ELF files are unencrypted and can be
  searched for file names. Encrypted or signed executables are recognised by their
  signature and never decrypted.
"""

from __future__ import annotations

import re
import struct
import zlib

from cutcontent.core.byte_sources import ByteSource

PARAMETER_FILE_MAGIC = bytes.fromhex("00505346")
COMPRESSED_ISO_MAGIC = bytes.fromhex("4349534f")
PLAIN_CD_EXECUTABLE_SIGNATURE = bytes.fromhex("50532d5820455845")
ELF_SIGNATURE = bytes.fromhex("7f454c46")
ENCRYPTED_HANDHELD_EXECUTABLE_SIGNATURE = bytes.fromhex("7e505350")
SIGNED_EXECUTABLE_SIGNATURE = bytes.fromhex("53434500")
PACKAGE_SIGNATURE = bytes.fromhex("00504250")


class DiscMetadataError(ValueError):
    pass


def read_parameter_file(data: bytes) -> dict[str, object]:
    if data[:4] != PARAMETER_FILE_MAGIC or len(data) < 20:
        raise DiscMetadataError("not a parameter file")
    _version, key_table, data_table, count = struct.unpack_from("<IIII", data, 4)
    values: dict[str, object] = {}
    for index in range(min(count, 512)):
        key_offset, data_format, used_length, _maximum, value_offset = struct.unpack_from("<HHIII", data, 20 + index * 16)
        key_start = key_table + key_offset
        key = data[key_start : data.find(b"\0", key_start)].decode("ascii", errors="replace")
        raw = data[data_table + value_offset : data_table + value_offset + used_length]
        if data_format == 0x0404:
            values[key] = struct.unpack("<I", raw[:4])[0] if len(raw) >= 4 else 0
        else:
            values[key] = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
    return values


def build_parameter_file(values: dict[str, object]) -> bytes:
    """Builds a parameter file. Used by tests."""
    keys = sorted(values)
    key_table = bytearray()
    data_table = bytearray()
    entries = bytearray()
    for key in keys:
        value = values[key]
        if isinstance(value, int):
            raw, data_format = struct.pack("<I", value), 0x0404
        else:
            raw, data_format = str(value).encode("utf-8") + b"\0", 0x0204
        maximum = (len(raw) + 3) // 4 * 4
        entries += struct.pack("<HHIII", len(key_table), data_format, len(raw), maximum, len(data_table))
        key_table += key.encode("ascii") + b"\0"
        data_table += raw.ljust(maximum, b"\0")
    while len(key_table) % 4:
        key_table.append(0)
    key_offset = 20 + len(entries)
    data_offset = key_offset + len(key_table)
    return PARAMETER_FILE_MAGIC + struct.pack("<IIII", 0x0101, key_offset, data_offset, len(keys)) + bytes(entries) + bytes(key_table) + bytes(data_table)


class CompressedIsoSource(ByteSource):
    """Read access to a compressed ISO image as if it were the uncompressed ISO."""

    def __init__(self, parent: ByteSource):
        header = parent.read_at(0, 24)
        if header[:4] != COMPRESSED_ISO_MAGIC:
            raise DiscMetadataError("not a compressed ISO image")
        _header_size, total_size, block_size, version, alignment = struct.unpack_from("<IQIBB", header, 4)
        if block_size <= 0 or block_size > 1 << 20 or version > 1:
            raise DiscMetadataError("unsupported compressed ISO header")
        self.parent = parent
        self.size = total_size
        self.block_size = block_size
        self.alignment = alignment
        self.description = f"{parent.description} (compressed ISO)"
        block_count = (total_size + block_size - 1) // block_size
        raw_index = parent.read_at(24, 4 * (block_count + 1))
        self.index = struct.unpack(f"<{block_count + 1}I", raw_index)
        self._cache: dict[int, bytes] = {}

    def _block(self, number: int) -> bytes:
        if number in self._cache:
            return self._cache[number]
        entry, following = self.index[number], self.index[number + 1]
        stored_uncompressed = bool(entry & 0x80000000)
        start = (entry & 0x7FFFFFFF) << self.alignment
        end = (following & 0x7FFFFFFF) << self.alignment
        raw = self.parent.read_at(start, max(0, end - start))
        block = raw[: self.block_size] if stored_uncompressed else zlib.decompress(raw, -15)
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[number] = block
        return block

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        result = bytearray()
        while length > 0:
            number, inside = divmod(offset, self.block_size)
            block = self._block(number)
            take = min(length, len(block) - inside)
            if take <= 0:
                break
            result += block[inside : inside + take]
            offset += take
            length -= take
        return bytes(result)


def build_compressed_iso(iso: bytes, block_size: int = 2048) -> bytes:
    """Compresses an ISO image to compressed ISO version 1. Used by tests."""
    block_count = (len(iso) + block_size - 1) // block_size
    header = COMPRESSED_ISO_MAGIC + struct.pack("<IQIBB2x", 24, len(iso), block_size, 1, 0)
    position = 24 + 4 * (block_count + 1)
    index, body = [], bytearray()
    for number in range(block_count):
        block = iso[number * block_size : (number + 1) * block_size]
        compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
        compressed = compressor.compress(block) + compressor.flush()
        if len(compressed) >= len(block):
            index.append((position + len(body)) | 0x80000000)
            body += block
        else:
            index.append(position + len(body))
            body += compressed
    index.append(position + len(body))
    return header + struct.pack(f"<{len(index)}I", *index) + bytes(body)


BOOT_LINE = re.compile(r"^\s*(BOOT2?)\s*=\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def read_boot_configuration(text: str) -> tuple[str, str] | None:
    """Returns ("BOOT" | "BOOT2", executable path inside the disc) or None."""
    match = BOOT_LINE.search(text)
    if not match:
        return None
    target = match.group(2)
    target = target.split(":", 1)[-1].lstrip("\\/").replace("\\", "/").split(";", 1)[0]
    return match.group(1).upper(), target


def executable_kind(head: bytes) -> str:
    if head.startswith(PLAIN_CD_EXECUTABLE_SIGNATURE):
        return "plain CD executable (unencrypted)"
    if head.startswith(ELF_SIGNATURE):
        return "ELF executable (unencrypted)"
    if head.startswith(ENCRYPTED_HANDHELD_EXECUTABLE_SIGNATURE):
        return "encrypted executable"
    if head.startswith(SIGNED_EXECUTABLE_SIGNATURE):
        return "signed and encrypted executable"
    if head.startswith(PACKAGE_SIGNATURE):
        return "packed executable package"
    return "unknown"
