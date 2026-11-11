"""Reader for Quake level files (``.bsp``).

Supports the original version 29 layout and the two enlarged community layouts
``BSP2`` and ``2PSB`` (same data, wider integer fields). A level file is a list
of 15 *lumps* (blocks): entity text, planes, embedded textures, vertices,
visibility, BSP nodes, texture projections, faces, light maps, clip nodes,
leaves, leaf face lists, edges, face edge lists and brush models.

Only what the previews and the analysis need is decoded. Nothing is modified.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

LUMP_NAMES = (
    "entities",
    "planes",
    "textures",
    "vertices",
    "visibility",
    "nodes",
    "texture_projections",
    "faces",
    "lighting",
    "clip_nodes",
    "leaves",
    "leaf_faces",
    "edges",
    "face_edges",
    "models",
)

VERSION_29 = 29
MAGIC_BSP2 = b"BSP2"
MAGIC_2PSB = b"2PSB"

CONTENTS_EMPTY = -1
CONTENTS_SOLID = -2
CONTENTS_WATER = -3
CONTENTS_SLIME = -4
CONTENTS_LAVA = -5
CONTENTS_SKY = -6

CONTENTS_NAMES = {
    CONTENTS_EMPTY: "empty space",
    CONTENTS_SOLID: "solid",
    CONTENTS_WATER: "water",
    CONTENTS_SLIME: "slime",
    CONTENTS_LAVA: "lava",
    CONTENTS_SKY: "sky",
}

# Entity spawn flags that hide an entity on a difficulty level or in deathmatch.
SPAWNFLAG_NOT_EASY = 256
SPAWNFLAG_NOT_NORMAL = 512
SPAWNFLAG_NOT_HARD = 1024
SPAWNFLAG_NOT_DEATHMATCH = 2048


class BspFormatError(ValueError):
    pass


@dataclass
class EmbeddedTexture:
    index: int
    name: str
    width: int
    height: int
    pixels: bytes | None  # full-size mip level as 8-bit palette indices; None if stored outside the map


@dataclass
class TextureProjection:
    s_vector: tuple[float, float, float, float]
    t_vector: tuple[float, float, float, float]
    texture_index: int
    flags: int


@dataclass
class Face:
    plane_index: int
    side: int
    first_edge: int
    edge_count: int
    projection_index: int
    light_styles: tuple[int, int, int, int]
    light_offset: int


@dataclass
class BrushModel:
    mins: tuple[float, float, float]
    maxs: tuple[float, float, float]
    origin: tuple[float, float, float]
    head_nodes: tuple[int, int, int, int]
    first_face: int
    face_count: int


@dataclass
class QuakeLevel:
    layout: str
    entities_text: str
    entities: list[dict]
    planes: list[tuple[float, float, float, float]]
    vertices: list[tuple[float, float, float]]
    edges: list[tuple[int, int]]
    face_edges: list[int]
    projections: list[TextureProjection]
    faces: list[Face]
    textures: list[EmbeddedTexture | None]
    lighting: bytes
    models: list[BrushModel]
    nodes: list[tuple[int, int, int]] = field(default_factory=list)  # (plane index, front child, back child)
    leaf_contents: list[int] = field(default_factory=list)
    # Clip nodes describe collision for the larger "hulls" (hull 1 = player size 32 x 32 x 56).
    # Their negative children are contents values directly (-1 empty, -2 solid, ...).
    clip_nodes: list[tuple[int, int, int]] = field(default_factory=list)

    def hull_contents(self, hull: int, point: tuple[float, float, float]) -> int:
        """Contents for a box of the hull's size centred on ``point`` (hull 1 = standing player)."""
        if not self.models or not 0 < hull < 4:
            return self.point_contents(point)
        node_index = self.models[0].head_nodes[hull]
        steps = 0
        while node_index >= 0:
            steps += 1
            if steps > 100000 or node_index >= len(self.clip_nodes):
                return CONTENTS_EMPTY
            plane_index, front, back = self.clip_nodes[node_index]
            normal_x, normal_y, normal_z, distance = self.planes[plane_index]
            side = point[0] * normal_x + point[1] * normal_y + point[2] * normal_z - distance
            node_index = front if side >= 0 else back
        return node_index

    def face_vertex_indices(self, face: Face) -> list[int]:
        indices = []
        for position in range(face.first_edge, face.first_edge + face.edge_count):
            edge_number = self.face_edges[position]
            if edge_number >= 0:
                indices.append(self.edges[edge_number][0])
            else:
                indices.append(self.edges[-edge_number][1])
        return indices

    def point_contents(self, point: tuple[float, float, float]) -> int:
        """What is at a point of the world: empty space, solid, water, ... (drawing hull)."""
        if not self.models or not self.nodes:
            return CONTENTS_EMPTY
        node_index = self.models[0].head_nodes[0]
        steps = 0
        while node_index >= 0:
            steps += 1
            if steps > 100000 or node_index >= len(self.nodes):
                return CONTENTS_EMPTY
            plane_index, front, back = self.nodes[node_index]
            normal_x, normal_y, normal_z, distance = self.planes[plane_index]
            side = point[0] * normal_x + point[1] * normal_y + point[2] * normal_z - distance
            node_index = front if side >= 0 else back
        leaf_index = -node_index - 1
        if 0 <= leaf_index < len(self.leaf_contents):
            return self.leaf_contents[leaf_index]
        return CONTENTS_EMPTY


def detect_layout(data: bytes) -> str | None:
    if len(data) < 4:
        return None
    if data[:4] == MAGIC_BSP2:
        return "BSP2"
    if data[:4] == MAGIC_2PSB:
        return "2PSB"
    if struct.unpack_from("<i", data, 0)[0] == VERSION_29:
        return "BSP29"
    return None


def _lump(data: bytes, index: int) -> bytes:
    offset, length = struct.unpack_from("<ii", data, 4 + index * 8)
    if offset < 0 or length < 0 or offset + length > len(data):
        raise BspFormatError(f"lump '{LUMP_NAMES[index]}' lies outside the file")
    return data[offset : offset + length]


def _records(lump: bytes, record_format: str) -> list[tuple]:
    size = struct.calcsize(record_format)
    usable = len(lump) - len(lump) % size
    return list(struct.iter_unpack(record_format, lump[:usable]))


def parse_entities(text: str) -> list[dict]:
    """Parses the entity lump: blocks of ``{ "key" "value" ... }``."""
    entities: list[dict] = []
    current: dict | None = None
    pending_key: str | None = None
    position = 0
    length = len(text)
    while position < length:
        character = text[position]
        if character == "{":
            current, pending_key = {}, None
            position += 1
        elif character == "}":
            if current is not None:
                entities.append(current)
            current, pending_key = None, None
            position += 1
        elif character == '"':
            end = text.find('"', position + 1)
            if end < 0:
                break
            token = text[position + 1 : end]
            position = end + 1
            if current is None:
                continue
            if pending_key is None:
                pending_key = token
            else:
                current.setdefault(pending_key, token)
                pending_key = None
        elif character == "/" and text.startswith("//", position):
            end = text.find("\n", position)
            position = length if end < 0 else end + 1
        else:
            position += 1
    return entities


def _parse_textures(lump: bytes) -> list[EmbeddedTexture | None]:
    if len(lump) < 4:
        return []
    (count,) = struct.unpack_from("<i", lump, 0)
    if count < 0 or 4 + count * 4 > len(lump):
        raise BspFormatError("texture lump is damaged")
    textures: list[EmbeddedTexture | None] = []
    for index in range(count):
        (offset,) = struct.unpack_from("<i", lump, 4 + index * 4)
        if offset < 0 or offset + 40 > len(lump):
            textures.append(None)
            continue
        raw_name = lump[offset : offset + 16].split(b"\0", 1)[0].decode("latin-1")
        width, height, mip_offset_0 = struct.unpack_from("<III", lump, offset + 16)
        pixels = None
        if mip_offset_0 and 0 < width <= 4096 and 0 < height <= 4096:
            start = offset + mip_offset_0
            if start + width * height <= len(lump):
                pixels = lump[start : start + width * height]
        textures.append(EmbeddedTexture(index, raw_name, width, height, pixels))
    return textures


def read_level(data: bytes) -> QuakeLevel:
    layout = detect_layout(data)
    if layout is None:
        raise BspFormatError("not a Quake level file (unknown version)")
    if len(data) < 4 + 15 * 8:
        raise BspFormatError("level file is truncated")

    entities_text = _lump(data, 0).split(b"\0", 1)[0].decode("latin-1")
    planes = [record[:4] for record in _records(_lump(data, 1), "<ffffi")]
    vertices = _records(_lump(data, 3), "<fff")
    projections = [
        TextureProjection(tuple(record[0:4]), tuple(record[4:8]), record[8], record[9])
        for record in _records(_lump(data, 6), "<8fii")
    ]
    face_edges = [record[0] for record in _records(_lump(data, 13), "<i")]
    models = [
        BrushModel(tuple(record[0:3]), tuple(record[3:6]), tuple(record[6:9]), tuple(record[9:13]), record[14], record[15])
        for record in _records(_lump(data, 14), "<9f4iiii")
    ]

    clip_format = "<ihh" if layout == "BSP29" else "<iii"
    if layout == "BSP29":
        node_format, face_format, edge_format, leaf_format = "<ihh6hHH", "<hhihh4Bi", "<HH", "<ii6hHH4B"
    elif layout == "2PSB":
        node_format, face_format, edge_format, leaf_format = "<iii6hII", "<iiiii4Bi", "<II", "<ii6hII4B"
    else:
        node_format, face_format, edge_format, leaf_format = "<iii6fII", "<iiiii4Bi", "<II", "<ii6fII4B"

    faces = [
        Face(record[0], record[1], record[2], record[3], record[4], tuple(record[5:9]), record[9])
        for record in _records(_lump(data, 7), face_format)
    ]
    edges = _records(_lump(data, 12), edge_format)
    nodes = [(record[0], record[1], record[2]) for record in _records(_lump(data, 5), node_format)]
    leaf_contents = [record[0] for record in _records(_lump(data, 10), leaf_format)]

    return QuakeLevel(
        layout=layout,
        entities_text=entities_text,
        entities=parse_entities(entities_text),
        planes=planes,
        vertices=vertices,
        edges=edges,
        face_edges=face_edges,
        projections=projections,
        faces=faces,
        textures=_parse_textures(_lump(data, 2)),
        lighting=_lump(data, 8),
        models=models,
        nodes=nodes,
        leaf_contents=leaf_contents,
        clip_nodes=_records(_lump(data, 9), clip_format),
    )


def read_entities_only(data: bytes) -> list[dict]:
    """Fast path for the analysis: only the entity text is decoded."""
    if detect_layout(data) is None:
        raise BspFormatError("not a Quake level file (unknown version)")
    return parse_entities(_lump(data, 0).split(b"\0", 1)[0].decode("latin-1"))


def parse_vector(value: str | None) -> tuple[float, float, float] | None:
    if not value:
        return None
    parts = value.split()
    if len(parts) != 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None


def spawn_flags(entity: dict) -> int:
    try:
        return int(float(entity.get("spawnflags", "0")))
    except ValueError:
        return 0
