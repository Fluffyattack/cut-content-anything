"""Turns a Quake model into a description the browser can animate with three.js.

The browser receives the compressed frame data as it is stored in the file
(one byte per axis and vertex) plus ``scale`` and ``translate``; it decompresses
and interpolates frames itself. Vertices on the skin seam get a second copy for
back-facing triangles, exactly like the engine shifts their texture coordinate
by half the skin width.
"""

from __future__ import annotations

from cutcontent.core.png_writer import encode_png, indexed_to_rgba
from cutcontent.formats.quake_model import QuakeModel
from cutcontent.previews import bytes_base64, float_array_base64, png_data_url, uint32_array_base64

QUAKE_ANIMATION_RATE = 10  # the engine advances model frames ten times per second


def skin_png(model: QuakeModel, palette: bytes, skin_index: int = 0) -> bytes:
    pixels = model.skins[skin_index] if model.skins else bytes(model.skin_width * model.skin_height)
    return encode_png(model.skin_width, model.skin_height, indexed_to_rgba(pixels, palette))


def build_model_preview(model: QuakeModel, palette: bytes) -> dict:
    expanded_index: dict[tuple[int, bool], int] = {}
    source_vertices: list[int] = []
    uv: list[float] = []
    indices: list[int] = []
    half_width = model.skin_width / 2
    for faces_front, *corners in model.triangles:
        for vertex in corners:
            on_seam, s, t = model.texture_coordinates[vertex]
            back_copy = bool(on_seam) and not faces_front
            key = (vertex, back_copy)
            if key not in expanded_index:
                expanded_index[key] = len(source_vertices)
                source_vertices.append(vertex)
                s_value = s + (half_width if back_copy else 0)
                uv.extend(((s_value + 0.5) / model.skin_width, (t + 0.5) / model.skin_height))
            indices.append(expanded_index[key])

    return {
        "skin_width": model.skin_width,
        "skin_height": model.skin_height,
        "skins": [{"name": name, "image": png_data_url(skin_png(model, palette, index))} for index, name in enumerate(model.skin_names)],
        "vertex_count": model.vertex_count,
        "triangle_count": len(model.triangles),
        "source_vertices": uint32_array_base64(source_vertices),
        "uv": float_array_base64(uv),
        "indices": uint32_array_base64(indices),
        "scale": model.scale,
        "translate": model.translate,
        "frames": [{"name": frame.name, "positions": bytes_base64(frame.positions)} for frame in model.frames],
        "animations": model.animations,
        "frames_per_second": QUAKE_ANIMATION_RATE,
        "flags": model.flags,
    }
