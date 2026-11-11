"""Readers for plain cartridge ROM images with tile graphics.

8-bit cartridges: the header lives at 0x100-0x14F (title at 0x134, cartridge
type at 0x147, ROM size code at 0x148, header checksum at 0x14D).
32-bit cartridges: the header is the first 192 bytes (title at 0xA0, game code at
0xAC, maker code at 0xB0, fixed value 0x96 at 0xB2, complement check at 0xBD).

The logo bitmap stored in every header is *not* compared or copied here; the
checksums are enough to recognise a header.

Graphics are stored as 8 x 8 tiles: 2 bits per pixel on 8-bit cartridges (two
bit planes per row) and 4 bits per pixel on 32-bit cartridges (two pixels per
byte, low nibble first). :func:`render_tiles` turns any part of a ROM into a
greyscale tile sheet, the classic way to spot unused graphics.
"""


from __future__ import annotations

import re
from dataclasses import dataclass

from cutcontent.core.png_writer import encode_png

EIGHT_BIT_CARTRIDGE = "8-bit cartridge"
EIGHT_BIT_COLOUR_CARTRIDGE = "8-bit cartridge (colour)"
THIRTY_TWO_BIT_CARTRIDGE = "32-bit cartridge"

CARTRIDGE_MAPPER_TYPES = {
    0x00: "ROM only", 0x01: "MBC1", 0x02: "MBC1 + RAM", 0x03: "MBC1 + RAM + battery", 0x05: "MBC2", 0x06: "MBC2 + battery",
    0x0F: "MBC3 + timer + battery", 0x10: "MBC3 + timer + RAM + battery", 0x11: "MBC3", 0x12: "MBC3 + RAM", 0x13: "MBC3 + RAM + battery",
    0x19: "MBC5", 0x1A: "MBC5 + RAM", 0x1B: "MBC5 + RAM + battery", 0x1C: "MBC5 + rumble", 0x1E: "MBC5 + rumble + RAM + battery",
    0x22: "MBC7", 0xFC: "camera mapper", 0xFE: "HuC3", 0xFF: "HuC1 + RAM + battery",
}


@dataclass
class CartridgeHeader:
    system: str  # one of the cartridge labels above
    title: str
    game_code: str
    maker_code: str
    version: int
    header_checksum_ok: bool
    details: dict


def _ascii(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("ascii", errors="replace").strip()


def read_eight_bit_cartridge_header(rom: bytes) -> CartridgeHeader | None:
    if len(rom) < 0x150:
        return None
    checksum = 0
    for value in rom[0x134:0x14D]:
        checksum = (checksum - value - 1) & 0xFF
    if checksum != rom[0x14D]:
        return None
    colour_flag = rom[0x143]
    system = EIGHT_BIT_COLOUR_CARTRIDGE if colour_flag in (0x80, 0xC0) else EIGHT_BIT_CARTRIDGE
    title_bytes = rom[0x134:0x13F] if colour_flag in (0x80, 0xC0) else rom[0x134:0x144]
    size_code = rom[0x148]
    declared_size = (32 * 1024) << size_code if size_code <= 8 else None
    return CartridgeHeader(
        system=system,
        title=_ascii(title_bytes) or "(no title)",
        game_code=_ascii(rom[0x13F:0x143]) if colour_flag in (0x80, 0xC0) else "",
        maker_code=_ascii(rom[0x144:0x146]) if rom[0x14B] == 0x33 else f"{rom[0x14B]:02X}",
        version=rom[0x14C],
        header_checksum_ok=True,
        details={
            "cartridge type": CARTRIDGE_MAPPER_TYPES.get(rom[0x147], f"unknown (0x{rom[0x147]:02X})"),
            "declared ROM size": f"{declared_size // 1024} KiB" if declared_size else f"unknown code 0x{size_code:02X}",
            "actual file size": f"{len(rom) // 1024} KiB",
            "colour only": colour_flag == 0xC0,
            "extended border features": rom[0x146] == 0x03,
        },
    )


def read_thirty_two_bit_cartridge_header(rom: bytes) -> CartridgeHeader | None:
    if len(rom) < 0xC0 or rom[0xB2] != 0x96:
        return None
    complement = (-sum(rom[0xA0:0xBD]) - 0x19) & 0xFF
    if complement != rom[0xBD]:
        return None
    return CartridgeHeader(
        system=THIRTY_TWO_BIT_CARTRIDGE,
        title=_ascii(rom[0xA0:0xAC]) or "(no title)",
        game_code=_ascii(rom[0xAC:0xB0]),
        maker_code=_ascii(rom[0xB0:0xB2]),
        version=rom[0xBC],
        header_checksum_ok=True,
        details={"actual file size": f"{len(rom) // 1024} KiB", "entry branch": rom[0:4].hex()},
    )


def fill_regions(rom: bytes, minimum_length: int = 4096) -> list[dict]:
    """Long runs of 0x00 or 0xFF: usually free space, sometimes erased content."""
    regions = []
    for fill in (b"\x00", b"\xff"):
        for match in re.finditer(re.escape(fill) + b"{%d,}" % minimum_length, rom):
            regions.append({"start": match.start(), "end": match.end(), "length": match.end() - match.start(), "fill": f"0x{fill[0]:02X}"})
    return sorted(regions, key=lambda region: region["start"])


DEVELOPMENT_TEXT = re.compile(
    rb"[\x20-\x7e]*(?:debug|test|unused|beta|proto|sound test|level select|stage select|cheat|dummy|sample|staff only|not used|developer|kiosk)[\x20-\x7e]*",
    re.IGNORECASE,
)


def development_strings(rom: bytes, limit: int = 200) -> list[tuple[int, str]]:
    found = []
    for match in DEVELOPMENT_TEXT.finditer(rom):
        text = match.group().decode("ascii", errors="replace").strip()
        if len(text) >= 5:
            found.append((match.start(), text))
            if len(found) >= limit:
                break
    return found


def render_tiles(data: bytes, bits_per_pixel: int, tiles_per_row: int = 16, scale_grey: bool = True) -> bytes:
    """Renders 8 x 8 tiles as a greyscale PNG (2 bits per pixel: 8-bit cartridges, 4: 32-bit cartridges)."""
    tile_size = 16 if bits_per_pixel == 2 else 32
    tile_count = max(1, len(data) // tile_size)
    rows = (tile_count + tiles_per_row - 1) // tiles_per_row
    width, height = tiles_per_row * 8, rows * 8
    pixels = bytearray(width * height)
    levels = (1 << bits_per_pixel) - 1
    for tile in range(tile_count):
        block = data[tile * tile_size : (tile + 1) * tile_size]
        origin_x, origin_y = (tile % tiles_per_row) * 8, (tile // tiles_per_row) * 8
        for row in range(8):
            for column in range(8):
                if bits_per_pixel == 2:
                    low = block[row * 2] if row * 2 < len(block) else 0
                    high = block[row * 2 + 1] if row * 2 + 1 < len(block) else 0
                    value = ((low >> (7 - column)) & 1) | (((high >> (7 - column)) & 1) << 1)
                    shade = 255 - value * 255 // levels  # 8-bit cartridges: 0 is the lightest shade
                else:
                    byte = block[row * 4 + column // 2] if row * 4 + column // 2 < len(block) else 0
                    value = (byte >> 4) if column % 2 else (byte & 0x0F)
                    shade = value * 255 // levels
                pixels[(origin_y + row) * width + origin_x + column] = shade
    return encode_png(width, height, bytes(pixels), channels=1)
