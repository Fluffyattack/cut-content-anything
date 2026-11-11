"""Reader for Quake character and object models (``.mdl``, magic ``IDPO``, version 6).

A model has one or more 8-bit skins, a list of texture coordinates, triangles
and a list of animation frames. Every frame stores all vertex positions
compressed to one byte per axis; the real position is ``scale * byte + translate``.
Frames can be grouped (a group is played as a small animation of its own).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

MODEL_MAGIC = b"IDPO"
MODEL_VERSION = 6
HEADER_FORMAT = "<4si3f3ff3f3i3iiif"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class ModelFormatError(ValueError):
    pass


@dataclass
class ModelFrame:
    name: str
    positions: bytes  # vertex_count * 3 bytes (x, y, z), compressed
    group: int  # index of the frame group, or -1 for a single frame


@dataclass
class QuakeModel:
    scale: tuple[float, float, float]
    translate: tuple[float, float, float]
    skin_width: int
    skin_height: int
    skins: list[bytes]  # every skin image (8-bit palette indices), group skins expanded
    skin_names: list[str]
    vertex_count: int
    texture_coordinates: list[tuple[int, int, int]]  # (on seam, s, t)
    triangles: list[tuple[int, int, int, int]]  # (faces front, vertex a, b, c)
    frames: list[ModelFrame]
    flags: int
    animations: list[dict] = field(default_factory=list)


def is_model(data: bytes) -> bool:
    return data[:4] == MODEL_MAGIC


def read_model(data: bytes) -> QuakeModel:
    if len(data) < HEADER_SIZE or data[:4] != MODEL_MAGIC:
        raise ModelFormatError("not a Quake model (missing 'IDPO' header)")
    header = struct.unpack_from(HEADER_FORMAT, data, 0)
    version = header[1]
    if version != MODEL_VERSION:
        raise ModelFormatError(f"unsupported model version {version} (only version 6 is supported)")
    scale = tuple(header[2:5])
    translate = tuple(header[5:8])
    skin_count, skin_width, skin_height = header[12:15]
    vertex_count, triangle_count, frame_count = header[15:18]
    flags = header[19]
    if not (0 < skin_width <= 4096 and 0 < skin_height <= 4096):
        raise ModelFormatError("skin size is out of range")
    if not (0 < vertex_count <= 65536 and 0 < triangle_count <= 131072 and 0 < frame_count <= 65536):
        raise ModelFormatError("vertex, triangle or frame count is out of range")

    position = HEADER_SIZE
    skin_size = skin_width * skin_height

    def take(length: int) -> bytes:
        nonlocal position
        if position + length > len(data):
            raise ModelFormatError("model file is truncated")
        chunk = data[position : position + length]
        position += length
        return chunk

    def take_int() -> int:
        return struct.unpack("<i", take(4))[0]

    skins: list[bytes] = []
    skin_names: list[str] = []
    for skin_index in range(skin_count):
        if take_int() == 0:
            skins.append(take(skin_size))
            skin_names.append(f"skin {skin_index}")
        else:
            group_size = take_int()
            if not 0 < group_size <= 256:
                raise ModelFormatError("skin group size is out of range")
            take(4 * group_size)  # display times of the group images
            for frame_in_group in range(group_size):
                skins.append(take(skin_size))
                skin_names.append(f"skin {skin_index}, image {frame_in_group}")

    texture_coordinates = list(struct.iter_unpack("<iii", take(12 * vertex_count)))
    triangles = list(struct.iter_unpack("<iiii", take(16 * triangle_count)))
    for triangle in triangles:
        if not all(0 <= index < vertex_count for index in triangle[1:]):
            raise ModelFormatError("triangle refers to a missing vertex")

    def take_frame(group: int) -> ModelFrame:
        take(8)  # bounding box minimum and maximum (compressed)
        name = take(16).split(b"\0", 1)[0].decode("latin-1")
        raw = take(4 * vertex_count)
        positions = bytearray(3 * vertex_count)
        positions[0::3] = raw[0::4]
        positions[1::3] = raw[1::4]
        positions[2::3] = raw[2::4]
        return ModelFrame(name, bytes(positions), group)

    frames: list[ModelFrame] = []
    for frame_index in range(frame_count):
        if take_int() == 0:
            frames.append(take_frame(-1))
        else:
            group_size = take_int()
            if not 0 < group_size <= 1024:
                raise ModelFormatError("frame group size is out of range")
            take(8)  # bounding box of the group
            take(4 * group_size)  # display times
            for _ in range(group_size):
                frames.append(take_frame(frame_index))

    model = QuakeModel(
        scale=scale,
        translate=translate,
        skin_width=skin_width,
        skin_height=skin_height,
        skins=skins,
        skin_names=skin_names,
        vertex_count=vertex_count,
        texture_coordinates=texture_coordinates,
        triangles=triangles,
        frames=frames,
        flags=flags,
    )
    model.animations = group_frames_into_animations(frames)
    return model


_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")


def group_frames_into_animations(frames: list[ModelFrame]) -> list[dict]:
    """Quake names frames like ``run1 .. run8``; consecutive frames with the same
    name stem form one animation."""
    animations: list[dict] = []
    for index, frame in enumerate(frames):
        match = _TRAILING_NUMBER.match(frame.name)
        stem = (match.group(1) if match else frame.name) or "frame"
        if frame.group >= 0:
            stem = f"{stem} (group {frame.group})"
        if animations and animations[-1]["name"] == stem and animations[-1]["first_frame"] + animations[-1]["frame_count"] == index:
            animations[-1]["frame_count"] += 1
        else:
            animations.append({"name": stem, "first_frame": index, "frame_count": 1})
    return animations


def build_model(
    skin_width: int,
    skin_height: int,
    skin: bytes,
    texture_coordinates: list[tuple[int, int, int]],
    triangles: list[tuple[int, int, int, int]],
    frames: list[tuple[str, list[tuple[int, int, int]]]],
    scale: tuple[float, float, float],
    translate: tuple[float, float, float],
) -> bytes:
    """Builds a version 6 model file. Used for the self-made demo data and tests."""
    vertex_count = len(texture_coordinates)
    header = struct.pack(
        HEADER_FORMAT,
        MODEL_MAGIC,
        MODEL_VERSION,
        *scale,
        *translate,
        64.0,
        0.0,
        0.0,
        24.0,
        1,
        skin_width,
        skin_height,
        vertex_count,
        len(triangles),
        len(frames),
        0,
        0,
        float(skin_width * skin_height),
    )
    body = bytearray(header)
    body += struct.pack("<i", 0) + skin
    for coordinate in texture_coordinates:
        body += struct.pack("<iii", *coordinate)
    for triangle in triangles:
        body += struct.pack("<iiii", *triangle)
    for name, positions in frames:
        body += struct.pack("<i", 0) + bytes(8) + name.encode("latin-1").ljust(16, b"\0")
        for x, y, z in positions:
            body += bytes((x, y, z, 0))
    return bytes(body)
