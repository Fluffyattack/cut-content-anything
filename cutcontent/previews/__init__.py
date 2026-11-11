"""Converters from game data to browser-friendly previews (PNG, JSON meshes)."""

import base64
import sys
from array import array


def float_array_base64(values) -> str:
    """Little-endian 32-bit floats, base64-encoded, for ``Float32Array`` in the browser."""
    packed = array("f", values)
    if sys.byteorder != "little":
        packed.byteswap()
    return base64.b64encode(packed.tobytes()).decode("ascii")


def uint32_array_base64(values) -> str:
    packed = array("I", values)
    if sys.byteorder != "little":
        packed.byteswap()
    return base64.b64encode(packed.tobytes()).decode("ascii")


def int32_array_base64(values) -> str:
    packed = array("i", values)
    if sys.byteorder != "little":
        packed.byteswap()
    return base64.b64encode(packed.tobytes()).decode("ascii")


def bytes_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + bytes_base64(png)
