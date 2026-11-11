"""Adapter for plain cartridge ROM images with tile graphics (8-bit and 32-bit).

Cartridge games have no file system, so "unused content" cannot be judged by
file references. What this adapter does honestly:

- reads and checks the cartridge header (title, codes, checksum, sizes);
- lists text that mentions debug, test, unused or select menus, with offsets;
- maps long 0x00/0xFF runs (free space);
- offers a tile browser: any part of the ROM drawn as 8 x 8 tiles (2 bits per
  pixel for 8-bit cartridges, 4 bits per pixel for 32-bit cartridges).

Files are recognised by their header checksums, not by their names. Whether code
ever reaches a piece of data needs disassembly or an emulator (REA or emucap);
this adapter says so instead of guessing. A ZIP archive that holds exactly one
cartridge image is read directly from the archive.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from cutcontent.core.content_items import ContentItem, Preview
from cutcontent.core.content_probe import could_be_game_file, file_head
from cutcontent.core.scan_report import ScanReport
from cutcontent.formats import cartridge_rom as rom_format
from cutcontent.platforms.base import Detection, FormatSupport, PlatformAdapter, PreviewError, PreviewResult

ROM_SIZE_LIMIT = 64 * 1024 * 1024
MINIMUM_ROM_SIZE = 0x8000
TILE_WINDOW_TILES = 1024
ARM_BRANCH_OPCODE = 0xEA  # 32-bit cartridges start with a branch instruction over the header


def header_from_rom(rom: bytes, total_size: int | None = None) -> rom_format.CartridgeHeader | None:
    """Recognises a cartridge by its header alone (checksums plus plausibility checks)."""
    total_size = len(rom) if total_size is None else total_size
    if not MINIMUM_ROM_SIZE <= total_size <= ROM_SIZE_LIMIT:
        return None
    header = rom_format.read_thirty_two_bit_cartridge_header(rom)
    if header is not None and len(rom) > 3 and rom[3] == ARM_BRANCH_OPCODE:
        return header
    header = rom_format.read_eight_bit_cartridge_header(rom)
    if header is None or total_size % 0x4000:
        return None
    size_code = rom[0x148]
    if size_code > 8 or (32 * 1024) << size_code != total_size:
        return None  # the declared ROM size must match the file
    return header


def zip_cartridge_member(path: Path):
    """The single cartridge image inside a ZIP archive, or None."""
    try:
        with zipfile.ZipFile(path) as archive:
            candidates = []
            for member in archive.infolist():
                if member.is_dir() or not MINIMUM_ROM_SIZE <= member.file_size <= ROM_SIZE_LIMIT:
                    continue
                with archive.open(member) as handle:
                    if header_from_rom(handle.read(0x150), member.file_size) is not None:
                        candidates.append(member)
            return candidates[0] if len(candidates) == 1 else None
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return None


def read_rom(path: Path) -> tuple[bytes, str, str]:
    """Returns (ROM bytes, container label, name inside the container)."""
    if zipfile.is_zipfile(path):
        member = zip_cartridge_member(path)
        if member is None:
            raise ValueError("The ZIP archive must contain exactly one recognisable cartridge image.")
        with zipfile.ZipFile(path) as archive, archive.open(member) as handle:
            return handle.read(), path.name, member.filename
    if path.stat().st_size > ROM_SIZE_LIMIT:
        raise ValueError("The ROM is larger than 64 MB.")
    with open(path, "rb") as handle:
        return handle.read(), path.name, ""


def read_header(rom: bytes, name: str = "") -> rom_format.CartridgeHeader | None:
    return header_from_rom(rom)


class CartridgeRomAdapter(PlatformAdapter):
    identifier = "cartridge_rom"
    display_name = "Plain cartridge ROM images (8-bit and 32-bit)"
    platform_family = "cartridge_rom"

    def detect(self, path: Path) -> list[Detection]:
        if not could_be_game_file(path):
            return []
        try:
            if zipfile.is_zipfile(path):
                if zip_cartridge_member(path) is None:
                    return []
                rom, _, inner = read_rom(path)
                header = header_from_rom(rom)
            else:
                header = header_from_rom(file_head(path, 0x150), path.stat().st_size)
        except (ValueError, OSError, zipfile.BadZipFile):
            return []
        if header is None:
            return []
        label = f"{path.name}" + (f" (code {header.game_code}, version {header.version})" if header.game_code else f" (version {header.version})")
        return [Detection(self.identifier, header.system, "Cartridge ROM image", header.title, label, str(path), 0.9)]

    def scan(self, path: Path) -> ScanReport:
        rom, container, inner = read_rom(path)
        header = read_header(rom, inner or path.name)
        if header is None:
            raise ValueError("No valid cartridge header was found (checksum mismatch or implausible size).")
        base_location = {"container": container, "container_path": str(path), "internal_path": inner}
        items: list[ContentItem] = []

        header_item = ContentItem("header", f"Cartridge header: {header.title}", dict(base_location, offset=0xA0 if header.system == rom_format.THIRTY_TWO_BIT_CARTRIDGE else 0x100), {"type": "header"}, Preview("text", True))
        header_item.details = dict(header.details, title=header.title, game_code=header.game_code, maker_code=header.maker_code, version=header.version, system=header.system)
        header_item.set_evidence("present_in_data", "yes", "Header read and its checksum verified.")
        items.append(header_item)

        bits = 4 if header.system == rom_format.THIRTY_TWO_BIT_CARTRIDGE else 2
        tiles = ContentItem("rom_region", "Tile browser (whole ROM)", dict(base_location, offset=0, size=len(rom)), {"type": "tiles", "bits_per_pixel": bits}, Preview("tiles", True))
        tiles.details = {"bits per pixel": bits, "hint": "Step through the ROM to look for graphics; whether code uses them is not checked."}
        tiles.set_evidence("present_in_data", "yes", f"{len(rom)} bytes of ROM data.")
        items.append(tiles)

        regions = rom_format.fill_regions(rom)
        free_space = ContentItem("rom_region", f"Free space map ({len(regions)} filled regions)", dict(base_location, size=sum(region["length"] for region in regions)), {"type": "fill_regions"}, Preview("text", True))
        free_space.details = {"regions": len(regions), "bytes": sum(region["length"] for region in regions)}
        free_space.set_evidence("present_in_data", "yes", "Long runs of 0x00 or 0xFF bytes (usually free space).")
        items.append(free_space)

        for offset, text in rom_format.development_strings(rom)[:60]:
            item = ContentItem("text", text[:80], dict(base_location, offset=offset, size=len(text)), {"type": "string", "offset": offset}, Preview("text", True))
            item.set_evidence("present_in_data", "yes", f"ASCII text at offset 0x{offset:X}.")
            item.set_evidence("possibly_unused", "unknown", "Whether code ever displays or uses this text needs disassembly or an emulator.", "none")
            item.finding_reasons.append("Text that mentions debug, test, unused or selection menus.")
            item.limits.append("Plain ASCII only; games with their own character encoding are not searched.")
            items.append(item)

        return ScanReport(
            path=str(path),
            adapter=self.identifier,
            platform=header.system,
            format_name="Cartridge ROM image" + (" in a ZIP archive" if inner else ""),
            title=header.title,
            build_label=f"{path.name}" + (f", code {header.game_code}" if header.game_code else "") + f", version {header.version}",
            items=items,
            limits=[
                "Cartridge ROMs have no file names, so there is no reference analysis; code is not disassembled.",
                "Use REA for disassembly or emucap for emulator tests to judge whether data is reached.",
                "Text search covers plain ASCII only.",
            ],
            details={"header": header.details, "fill_regions": regions[:200]},
            game_launch={"available": False, "reason": "Game start is not part of this tool; use an emulator (for example through emucap) with your own ROM."},
        )

    def preview(self, path: Path, item: dict, options: dict) -> PreviewResult:
        rom, _, inner = read_rom(path)
        reference = item["reference"]
        kind = reference.get("type")
        if kind == "tiles":
            bits = int(options.get("bits") or reference.get("bits_per_pixel", 2))
            if bits not in (2, 4):
                raise PreviewError("Bits per pixel must be 2 or 4.")
            tile_size = 16 if bits == 2 else 32
            offset = max(0, min(int(options.get("offset") or 0), max(0, len(rom) - tile_size)))
            columns = max(8, min(64, int(options.get("columns") or 16)))
            window = rom[offset : offset + TILE_WINDOW_TILES * tile_size]
            return PreviewResult("image/png", rom_format.render_tiles(window, bits, columns))
        if kind == "header":
            header = read_header(rom, inner or path.name)
            lines = [f"{key}: {value}" for key, value in ({"system": header.system, "title": header.title, "game code": header.game_code, "maker code": header.maker_code, "version": header.version} | header.details).items()]
            return PreviewResult("text/plain; charset=utf-8", "\n".join(lines).encode("utf-8"))
        if kind == "fill_regions":
            regions = rom_format.fill_regions(rom)
            lines = [f"0x{region['start']:08X} - 0x{region['end']:08X}  {region['length']:>9} bytes of {region['fill']}" for region in regions]
            return PreviewResult("text/plain; charset=utf-8", ("\n".join(lines) or "No long filled regions.").encode("utf-8"))
        if kind == "string":
            offset = int(reference["offset"])
            start = max(0, offset - 64)
            context = rom[start : offset + 192]
            dump = []
            for line_start in range(0, len(context), 16):
                chunk = context[line_start : line_start + 16]
                text = "".join(chr(value) if 32 <= value < 127 else "." for value in chunk)
                dump.append(f"0x{start + line_start:08X}  {chunk.hex(' '):<47}  {text}")
            return PreviewResult("text/plain; charset=utf-8", "\n".join(dump).encode("utf-8"))
        raise PreviewError("No preview for this item.")

    def format_support(self) -> list[FormatSupport]:
        return [
            FormatSupport(
                "8-bit cartridges",
                "Cartridge ROM image",
                "any file name, or a ZIP archive with one image inside; recognised by header checksum and declared size",
                "partial",
                "Header (title, cartridge type, sizes, header checksum).",
                "Development-sounding ASCII text with offsets; free-space map. No code analysis.",
                "Tile browser (2 bits per pixel, any offset), header and hex context of text finds.",
                "No disassembly, no compressed graphics, no palettes (tiles are greyscale), no game start. Over- or under-sized dumps are not recognised automatically.",
                "Automated tests with a self-made ROM image (valid header, test strings, tiles); no commercial ROMs.",
            ),
            FormatSupport(
                "32-bit cartridges",
                "Cartridge ROM image",
                "any file name, or a ZIP archive with one image inside; recognised by header complement check",
                "partial",
                "Header (title, game code, maker, version, complement check).",
                "Development-sounding ASCII text with offsets; free-space map. No code analysis.",
                "Tile browser (4 bits per pixel, any offset), header and hex context of text finds.",
                "No disassembly, no LZ77/Huffman decompression, no palettes, no game start.",
                "Automated tests with a self-made ROM image; no commercial ROMs.",
            ),
        ]
