"""Turns a Quake level into a description the browser can draw with three.js.

What the browser receives (JSON):

- ``textures``: every texture used by visible surfaces, as PNG data URLs
- ``lightmap``: all surface light maps packed into one greyscale or colour image
- ``groups``: one triangle list per texture with positions, texture coordinates
  and light map coordinates (as base64 ``Float32Array`` data)
- ``entities``: point entities (monsters, items, lights, player starts ...)
- ``spawn``: where the free camera starts (the first player start)

Quake uses a Z-up coordinate system; three.js uses Y-up. Positions are converted
here: ``(x, y, z)`` becomes ``(x, z, -y)``.

Light maps follow the engine's rules: one light sample every 16 texture units,
measured from the face's rounded-down minimum texture coordinate.
"""

from __future__ import annotations

import math

from cutcontent.core.png_writer import encode_png, indexed_to_rgba
from cutcontent.formats.quake_bsp import QuakeLevel, parse_vector, spawn_flags
from cutcontent.previews import float_array_base64, int32_array_base64, png_data_url

LIGHTMAP_ATLAS_WIDTH = 1024
FULL_BRIGHT_LIGHT = 128  # shown as normal brightness (the viewer doubles light values like the engine's overbright mode)
NO_LIGHT = 0
TRANSPARENT_INDEX = 255
HIDDEN_TEXTURE_NAMES = {"trigger", "clip", "skip", "hint", "hintskip"}


def to_viewer_space(point) -> tuple[float, float, float]:
    return (point[0], point[2], -point[1])


def texture_kind(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith("sky"):
        return "sky"
    if lowered.startswith("*"):
        return "liquid"
    if lowered.startswith("{"):
        return "transparent"
    return "solid"


def texture_png(texture, palette: bytes) -> tuple[bytes, int, int]:
    """Converts an embedded texture to PNG. Sky textures keep only their back layer."""
    if texture is None or texture.pixels is None:
        checker = bytearray()
        for y in range(16):
            for x in range(16):
                checker += b"\xff\x00\xff\xff" if (x // 4 + y // 4) % 2 else b"\x20\x20\x20\xff"
        return encode_png(16, 16, bytes(checker)), 16, 16
    width, height, pixels = texture.width, texture.height, texture.pixels
    kind = texture_kind(texture.name)
    if kind == "sky" and width >= 2:
        half = width // 2
        pixels = b"".join(pixels[row * width + half : (row + 1) * width] for row in range(height))
        width = half
    transparent = TRANSPARENT_INDEX if kind == "transparent" else None
    return encode_png(width, height, indexed_to_rgba(pixels, palette, transparent)), width, height


class LightmapAtlas:
    """Packs many small light maps into one image, row by row (shelf packing)."""

    def __init__(self, coloured: bool):
        self.channels = 3 if coloured else 1
        self.width = LIGHTMAP_ATLAS_WIDTH
        self.rows: list[bytearray] = []
        self.cursor_x = 0
        self.cursor_y = 0
        self.shelf_height = 0
        self.full_bright_spot = self.add(2, 2, bytes([FULL_BRIGHT_LIGHT]) * (4 * self.channels))
        self.no_light_spot = self.add(2, 2, bytes([NO_LIGHT]) * (4 * self.channels))

    def _ensure_rows(self, count: int) -> None:
        while len(self.rows) < count:
            self.rows.append(bytearray(self.width * self.channels))

    def add(self, block_width: int, block_height: int, samples: bytes) -> tuple[int, int]:
        """Adds a block with a one-texel border; returns the top-left corner of the inner block."""
        padded_width, padded_height = block_width + 2, block_height + 2
        if self.cursor_x + padded_width > self.width:
            self.cursor_x = 0
            self.cursor_y += self.shelf_height
            self.shelf_height = 0
        origin_x, origin_y = self.cursor_x, self.cursor_y
        self.cursor_x += padded_width
        self.shelf_height = max(self.shelf_height, padded_height)
        self._ensure_rows(origin_y + padded_height)
        channels = self.channels
        row_length = block_width * channels
        for padded_row in range(padded_height):
            source_row = min(max(padded_row - 1, 0), block_height - 1)
            middle = samples[source_row * row_length : (source_row + 1) * row_length]
            # repeat the outermost texels into the border so filtering does not bleed
            padded = middle[:channels] + middle + middle[-channels:]
            target = origin_x * channels
            self.rows[origin_y + padded_row][target : target + len(padded)] = padded
        return origin_x + 1, origin_y + 1

    def png(self) -> tuple[bytes, int, int]:
        height = max(1, len(self.rows))
        self._ensure_rows(height)
        return encode_png(self.width, height, b"".join(self.rows), channels=self.channels), self.width, height


def read_coloured_light(lit_data: bytes | None, expected_size: int) -> bytes | None:
    """``.lit`` files (``QLIT`` version 1) hold the same light map in RGB."""
    if not lit_data or lit_data[:4] != b"QLIT" or len(lit_data) < 8 + expected_size * 3:
        return None
    return lit_data[8:]


def visible_brush_models(level: QuakeLevel) -> list[int]:
    hidden = set()
    for entity in level.entities:
        model = entity.get("model", "")
        if model.startswith("*") and entity.get("classname", "").startswith("trigger_"):
            try:
                hidden.add(int(model[1:]))
            except ValueError:
                pass
    return [index for index in range(len(level.models)) if index not in hidden]


def build_level_preview(level: QuakeLevel, palette: bytes, lit_data: bytes | None = None, used_texture_names: set | None = None) -> dict:
    coloured_light = read_coloured_light(lit_data, len(level.lighting))
    atlas = LightmapAtlas(coloured=coloured_light is not None)
    light_source = coloured_light if coloured_light is not None else level.lighting
    channels = atlas.channels

    groups: dict[int, dict] = {}
    statistics = {"faces": 0, "triangles": 0, "hidden_faces": 0}
    for model_index in visible_brush_models(level):
        model = level.models[model_index]
        for face_index in range(model.first_face, model.first_face + model.face_count):
            if face_index >= len(level.faces):
                break
            face = level.faces[face_index]
            if not 0 <= face.projection_index < len(level.projections):
                continue
            projection = level.projections[face.projection_index]
            texture = level.textures[projection.texture_index] if 0 <= projection.texture_index < len(level.textures) else None
            texture_name = texture.name if texture else "missing"
            if texture_name.lower() in HIDDEN_TEXTURE_NAMES:
                statistics["hidden_faces"] += 1
                continue
            vertex_indices = level.face_vertex_indices(face)
            if len(vertex_indices) < 3:
                continue
            points = [level.vertices[index] for index in vertex_indices]
            s_vector, t_vector = projection.s_vector, projection.t_vector
            s_values = [p[0] * s_vector[0] + p[1] * s_vector[1] + p[2] * s_vector[2] + s_vector[3] for p in points]
            t_values = [p[0] * t_vector[0] + p[1] * t_vector[1] + p[2] * t_vector[2] + t_vector[3] for p in points]

            kind = texture_kind(texture_name)
            light_spot = None
            if kind in ("sky", "liquid") or not level.lighting:
                light_spot = atlas.full_bright_spot
            elif face.light_offset < 0 or face.light_styles[0] == 255:
                light_spot = atlas.no_light_spot
            if light_spot is None:
                minimum_s, minimum_t = math.floor(min(s_values) / 16), math.floor(min(t_values) / 16)
                maximum_s, maximum_t = math.ceil(max(s_values) / 16), math.ceil(max(t_values) / 16)
                block_width, block_height = maximum_s - minimum_s + 1, maximum_t - minimum_t + 1
                sample_count = block_width * block_height
                start = face.light_offset * channels
                samples = light_source[start : start + sample_count * channels]
                if 0 < block_width <= 256 and 0 < block_height <= 256 and len(samples) == sample_count * channels:
                    corner_x, corner_y = atlas.add(block_width, block_height, samples)
                    light_u = [(corner_x + s / 16 - minimum_s + 0.5) for s in s_values]
                    light_v = [(corner_y + t / 16 - minimum_t + 0.5) for t in t_values]
                else:
                    light_spot = atlas.no_light_spot
            if light_spot is not None:
                light_u = [light_spot[0] + 1.0] * len(points)
                light_v = [light_spot[1] + 1.0] * len(points)

            texture_width = texture.width if texture and texture.width else 64
            texture_height = texture.height if texture and texture.height else 64
            if kind == "sky":
                texture_width = max(1, texture_width // 2)
            group = groups.setdefault(projection.texture_index, {"positions": [], "uv": [], "light_uv": []})
            converted = [to_viewer_space(p) for p in points]
            for corner in range(1, len(points) - 1):
                for vertex in (0, corner, corner + 1):
                    group["positions"].extend(converted[vertex])
                    group["uv"].extend((s_values[vertex] / texture_width, t_values[vertex] / texture_height))
                    group["light_uv"].extend((light_u[vertex], light_v[vertex]))
                statistics["triangles"] += 1
            statistics["faces"] += 1

    lightmap_png, atlas_width, atlas_height = atlas.png()
    textures_out = []
    group_list = []
    for texture_index, group in sorted(groups.items()):
        texture = level.textures[texture_index] if 0 <= texture_index < len(level.textures) else None
        png, width, height = texture_png(texture, palette)
        name = texture.name if texture else "missing"
        textures_out.append({"name": name, "kind": texture_kind(name), "width": width, "height": height, "image": png_data_url(png)})
        light_uv = group["light_uv"]
        normalised_light_uv = [value / (atlas_width if position % 2 == 0 else atlas_height) for position, value in enumerate(light_uv)]
        group_list.append(
            {
                "texture": len(textures_out) - 1,
                "vertex_count": len(group["positions"]) // 3,
                "positions": float_array_base64(group["positions"]),
                "uv": float_array_base64(group["uv"]),
                "light_uv": float_array_base64(normalised_light_uv),
            }
        )

    entities_out, spawn = describe_entities(level)
    collision = player_collision(level)
    world = level.models[0] if level.models else None
    return {
        "layout": level.layout,
        "textures": textures_out,
        "lightmap": {"image": png_data_url(lightmap_png), "width": atlas_width, "height": atlas_height, "coloured": coloured_light is not None},
        "groups": group_list,
        "entities": entities_out,
        "spawn": spawn,
        "bounds": {"min": to_viewer_space(world.mins), "max": to_viewer_space(world.maxs)} if world else None,
        "statistics": statistics,
        "collision": collision,
    }


def player_collision(level: QuakeLevel) -> dict | None:
    """Clip hull 1 (the standing player) for the viewer's walk mode, in Quake coordinates."""
    if not level.models or not level.clip_nodes:
        return None
    head = level.models[0].head_nodes[1]
    if not 0 <= head < len(level.clip_nodes):
        return None
    return {
        "hull": 1,
        "head_node": head,
        "planes": float_array_base64([value for plane in level.planes for value in plane]),
        "clip_nodes": int32_array_base64([value for node in level.clip_nodes for value in node]),
        "eye_height": 22,
    }


def describe_entities(level: QuakeLevel) -> tuple[list[dict], dict | None]:
    entities_out = []
    spawn = None
    for index, entity in enumerate(level.entities):
        origin = parse_vector(entity.get("origin"))
        classname = entity.get("classname", "")
        if origin is None:
            continue
        try:
            angle = float(entity.get("angle", "0"))
        except ValueError:
            angle = 0.0
        entry = {
            "index": index,
            "classname": classname,
            "origin": to_viewer_space(origin),
            "angle": angle,
            "spawnflags": spawn_flags(entity),
        }
        for key in ("targetname", "target", "model", "message"):
            if key in entity:
                entry[key] = entity[key]
        entities_out.append(entry)
        if spawn is None and classname == "info_player_start":
            spawn = {"origin": to_viewer_space((origin[0], origin[1], origin[2] + 22)), "angle": angle}
    if spawn is None:
        for entry in entities_out:
            if entry["classname"].startswith("info_player"):
                x, y, z = entry["origin"]
                spawn = {"origin": (x, y + 22, z), "angle": entry["angle"]}
                break
    return entities_out, spawn
