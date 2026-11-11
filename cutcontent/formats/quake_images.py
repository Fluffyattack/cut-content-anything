"""Readers for Quake's 2D image formats.

- ``.lmp`` pictures: width, height and 8-bit palette indices (menu graphics).
  ``palette.lmp`` (768 bytes of RGB) and ``colormap.lmp`` are special cases.
- ``.wad`` archives (``WAD2``): a list of named pictures and textures (``gfx.wad``).
- ``.spr`` sprites (``IDSP``): flat images that always face the player, e.g. explosions.

Palette index 255 is transparent in sprites and in textures whose name starts with ``{``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

PALETTE_SIZE = 768
COLOURMAP_SIZE = 16385
TRANSPARENT_INDEX = 255


class QuakeImageError(ValueError):
    pass


@dataclass
class IndexedImage:
    name: str
    width: int
    height: int
    pixels: bytes  # 8-bit palette indices
    transparent_index: int | None = None


def read_lmp_picture(name: str, data: bytes) -> IndexedImage:
    if len(data) < 8:
        raise QuakeImageError("picture is truncated")
    width, height = struct.unpack_from("<ii", data, 0)
    if not (0 < width <= 4096 and 0 < height <= 4096) or 8 + width * height > len(data):
        raise QuakeImageError("picture size does not match the file")
    return IndexedImage(name, width, height, data[8 : 8 + width * height], TRANSPARENT_INDEX)


@dataclass
class WadLump:
    name: str
    lump_type: int
    offset: int
    size: int


WAD_TYPE_PALETTE = 0x40
WAD_TYPE_STATUS_PICTURE = 0x42
WAD_TYPE_MIP_TEXTURE = 0x44
WAD_TYPE_CONSOLE_PICTURE = 0x45


def read_wad_directory(data: bytes) -> list[WadLump]:
    if data[:4] not in (b"WAD2", b"WAD3"):
        raise QuakeImageError("not a WAD2 archive")
    count, directory_offset = struct.unpack_from("<ii", data, 4)
    if count < 0 or directory_offset < 12 or directory_offset + count * 32 > len(data):
        raise QuakeImageError("WAD directory lies outside the file")
    lumps = []
    for index in range(count):
        offset, disk_size, size, lump_type, compression = struct.unpack_from("<iiiBB", data, directory_offset + index * 32)
        name = data[directory_offset + index * 32 + 16 : directory_offset + index * 32 + 32].split(b"\0", 1)[0].decode("latin-1")
        if compression == 0 and 0 <= offset and offset + disk_size <= len(data):
            lumps.append(WadLump(name, lump_type, offset, disk_size))
    return lumps


def read_wad_image(data: bytes, lump: WadLump) -> IndexedImage | None:
    """Decodes a picture or texture from a WAD archive, or returns None for other lump types."""
    body = data[lump.offset : lump.offset + lump.size]
    if lump.name.lower() == "conchars" and len(body) >= 128 * 128:
        return IndexedImage(lump.name, 128, 128, body[: 128 * 128], 0)
    if lump.lump_type == WAD_TYPE_STATUS_PICTURE:
        try:
            return read_lmp_picture(lump.name, body)
        except QuakeImageError:
            return None
    if lump.lump_type == WAD_TYPE_MIP_TEXTURE and len(body) >= 40:
        width, height, first_offset = struct.unpack_from("<III", body, 16)
        if 0 < width <= 4096 and 0 < height <= 4096 and first_offset + width * height <= len(body):
            transparent = TRANSPARENT_INDEX if lump.name.startswith("{") else None
            return IndexedImage(lump.name, width, height, body[first_offset : first_offset + width * height], transparent)
    return None


SPRITE_MAGIC = b"IDSP"


def read_sprite_frames(data: bytes) -> list[IndexedImage]:
    """Returns every image of a version 1 sprite (single frames and frame groups)."""
    if data[:4] != SPRITE_MAGIC:
        raise QuakeImageError("not a Quake sprite (missing 'IDSP' header)")
    version, _sprite_type, _radius, _width, _height, frame_count = struct.unpack_from("<iifiii", data, 4)
    if version != 1:
        raise QuakeImageError(f"unsupported sprite version {version}")
    position = 36
    images: list[IndexedImage] = []

    def read_single(label: str) -> None:
        nonlocal position
        _origin_x, _origin_y, width, height = struct.unpack_from("<iiii", data, position)
        position += 16
        if not (0 < width <= 2048 and 0 < height <= 2048) or position + width * height > len(data):
            raise QuakeImageError("sprite frame size does not match the file")
        images.append(IndexedImage(label, width, height, data[position : position + width * height], TRANSPARENT_INDEX))
        position += width * height

    for frame_index in range(frame_count):
        (frame_type,) = struct.unpack_from("<i", data, position)
        position += 4
        if frame_type == 0:
            read_single(f"frame {frame_index}")
        else:
            (group_size,) = struct.unpack_from("<i", data, position)
            position += 4 + 4 * group_size
            for image_index in range(group_size):
                read_single(f"frame {frame_index}.{image_index}")
    return images


def combine_side_by_side(images: list[IndexedImage], gap: int = 2) -> IndexedImage:
    """Puts several frames next to each other in one image (for sprite previews)."""
    width = sum(image.width for image in images) + gap * (len(images) - 1)
    height = max(image.height for image in images)
    canvas = bytearray([TRANSPARENT_INDEX]) * (width * height)
    x_position = 0
    for image in images:
        for row in range(image.height):
            start = row * width + x_position
            canvas[start : start + image.width] = image.pixels[row * image.width : (row + 1) * image.width]
        x_position += image.width + gap
    return IndexedImage("frames", width, height, bytes(canvas), TRANSPARENT_INDEX)
