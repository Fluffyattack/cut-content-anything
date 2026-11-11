"""Minimal PNG encoder (standard library only) for previews in the browser."""

from __future__ import annotations

import struct
import zlib


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def encode_png(width: int, height: int, pixels: bytes, channels: int = 4) -> bytes:
    """Encodes raw pixels. ``channels``: 1 = grey, 3 = RGB, 4 = RGBA (8 bits each)."""
    colour_types = {1: 0, 2: 4, 3: 2, 4: 6}
    if channels not in colour_types:
        raise ValueError("channels must be 1, 2, 3 or 4")
    if width <= 0 or height <= 0:
        raise ValueError("image must not be empty")
    row_size = width * channels
    if len(pixels) < row_size * height:
        raise ValueError("not enough pixel data")
    rows = bytearray()
    for row in range(height):
        rows.append(0)  # filter type "none"
        rows += pixels[row * row_size : (row + 1) * row_size]
    header = struct.pack(">IIBBBBB", width, height, 8, colour_types[channels], 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + _chunk(b"IEND", b"")


def indexed_to_rgba(indices: bytes, palette: bytes, transparent_index: int | None = None) -> bytes:
    """Converts 8-bit palette indices to RGBA using a 768-byte RGB palette."""
    lookup = []
    for index in range(256):
        red, green, blue = palette[index * 3 : index * 3 + 3] if index * 3 + 3 <= len(palette) else (index, index, index)
        alpha = 0 if index == transparent_index else 255
        lookup.append(bytes((red, green, blue, alpha)))
    return b"".join(lookup[value] for value in indices)


def greyscale_palette() -> bytes:
    """Fallback palette when a game does not provide one (colours will be wrong)."""
    return bytes(value for index in range(256) for value in (index, index, index))


def palette_swatch_png(palette: bytes, cell: int = 8) -> bytes:
    """A 16 x 16 grid of colour cells, to preview a palette file."""
    size = 16 * cell
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            index = (y // cell) * 16 + (x // cell)
            pixels += palette[index * 3 : index * 3 + 3] if index * 3 + 3 <= len(palette) else b"\0\0\0"
    return encode_png(size, size, bytes(pixels), channels=3)
