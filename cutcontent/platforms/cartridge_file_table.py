"""Inventory, banners, tiles and bounded code-string checks for cartridge images
that carry their own file system (filename table plus file allocation table).

Files are addressed by numeric file ID as well as by name. Missing name
references therefore never make a file "unused" in this adapter. Runtime and
normal-play reachability remain untested until a real observation is recorded.
Cartridges are recognised by their header structure and checksum, not by their names.
"""
from __future__ import annotations

from pathlib import Path
import re

from cutcontent.core.byte_sources import FileByteSource
from cutcontent.core.content_items import ContentItem, Preview
from cutcontent.core.content_probe import could_be_game_file
from cutcontent.core.scan_report import ScanReport
from cutcontent.formats import cartridge_file_table as cartridge_format
from cutcontent.formats.cartridge_rom import render_tiles
from cutcontent.platforms.base import Detection, FormatSupport, PlatformAdapter, PreviewError, PreviewResult
from cutcontent.platforms.shared_analysis import kind_for_extension, name_hint, preview_for_file, read_browser_preview

EXECUTABLE_STRING_BYTE_LIMIT = 2 * 1024 * 1024
ASCII_STRINGS = re.compile(rb"[\x20-\x7e]{5,200}")
PLATFORM_LABEL = "Cartridge with file table"
FORMAT_LABEL = "Cartridge ROM with embedded file system"
MINIMUM_CARTRIDGE_SIZE = 0x4000
DEVELOPMENT_HINT = re.compile(r"debug|unused|level.?select|stage.?select|sound.?test|developer|prototype|not used", re.IGNORECASE)


def cartridge_title(header, banner: dict | None) -> str:
    titles = banner.get("titles", {}) if banner else {}
    title = titles.get("English") or next(iter(titles.values()), "")
    return " ".join(title.split()) if title else header.title


def try_banner(source, offset: int) -> dict | None:
    try:
        return cartridge_format.read_banner(source, offset)
    except cartridge_format.CartridgeFileTableError:
        return None


def executable_segments(header, label: str) -> list[tuple[int, int]]:
    """Skip the cartridge secure area (0x4000..0x7FFF), even in modified dumps."""
    offset, size = header.regions[label]
    end = offset + size
    segments = []
    if offset < 0x4000:
        segments.append((offset, min(end, 0x4000) - offset))
    if end > 0x8000:
        start = max(offset, 0x8000)
        segments.append((start, end - start))
    remaining = EXECUTABLE_STRING_BYTE_LIMIT
    result = []
    for start, length in segments:
        take = min(remaining, length)
        if take:
            result.append((start, take))
            remaining -= take
    return result


class CartridgeFileTableAdapter(PlatformAdapter):
    identifier = "cartridge_file_table"
    display_name = "Cartridge images with an embedded file system"
    platform_family = "cartridge_rom"

    def detect(self, path: Path) -> list[Detection]:
        if not could_be_game_file(path) or path.stat().st_size < MINIMUM_CARTRIDGE_SIZE:
            return []
        source = FileByteSource(path)
        try:
            header = cartridge_format.read_header(source)
            banner = try_banner(source, header.banner_offset)
            if not header.header_checksum_ok and banner is None:
                return []  # neither the checksum nor a readable banner confirms the structure
            return [Detection(self.identifier, PLATFORM_LABEL, FORMAT_LABEL, cartridge_title(header, banner),
                              f"{path.name}, {header.game_code}, revision {header.version}", str(path), 0.95,
                              [] if header.header_checksum_ok else ["The header checksum differs; file tables will be checked during scanning."])]
        except (ValueError, OSError):
            return []
        finally:
            source.close()

    def scan(self, path: Path) -> ScanReport:
        source = FileByteSource(path)
        try:
            filesystem = cartridge_format.read_file_system(source, path.name, str(path), allow_incomplete_files=True)
            header = filesystem.header
            banner = try_banner(source, header.banner_offset)
            base = {"container": path.name, "container_path": str(path), "internal_path": ""}
            header_item = ContentItem("header", "Cartridge header", dict(base, offset=0, size=cartridge_format.HEADER_SIZE), {"type": "header"}, Preview("text", True))
            header_item.details = {"title": header.title, "game code": header.game_code, "maker code": header.maker_code,
                                   "revision": header.version, "unit code": header.unit_code, "header checksum matches": header.header_checksum_ok,
                                   "declared capacity in bytes": header.declared_capacity, "actual size in bytes": source.size,
                                   "files in allocation table": len(filesystem.files), "named files": len(filesystem.named_file_ids),
                                   "overlay files": len(filesystem.overlay_file_ids), **header.details}
            header_item.set_evidence("present_in_data", "yes", "Read the cartridge header and checked all declared file-table boundaries.")
            items = [header_item]
            if banner:
                icon = ContentItem("image", "Cartridge banner icon", dict(base, offset=header.banner_offset + 0x20, size=0x220), {"type": "banner_icon"}, Preview("image", True), thumbnail=True)
                icon.details = {"width": 32, "height": 32, "banner version": banner["version"], "banner checksum matches": banner["checksum_ok"]}
                icon.set_evidence("present_in_data", "yes", "The banner contains a tiled 32 by 32 icon and its 16-colour palette.")
                items.append(icon)
                titles = ContentItem("text", "Cartridge titles", dict(base, offset=header.banner_offset + 0x240), {"type": "banner_titles"}, Preview("text", True))
                titles.set_evidence("present_in_data", "yes", "Read the banner's UTF-16 language titles.")
                items.append(titles)

            # Retain the actual FAT ID; unnamed overlay files are normal, not cut content.
            for file_id, file in enumerate(filesystem.files):
                item = ContentItem(kind_for_extension(file.extension), file.path, file.location(), {"type": "file_id", "file_id": file_id}, preview_for_file(file))
                item.thumbnail = item.preview.viewer == "image" and item.preview.supported and file.size < 4_000_000
                item.set_evidence("present_in_data", "yes", f"File allocation entry {file_id}: {file.size} bytes at ROM offset 0x{file.offset:X}.")
                hint = name_hint(file.path)
                if hint:
                    item.finding_reasons.append(hint)
                item.details = {"file ID": file_id, "has filename": file_id in filesystem.named_file_ids,
                                "listed in an overlay table": file_id in filesystem.overlay_file_ids}
                if file_id in filesystem.overlay_file_ids:
                    item.kind = "code"
                if file.size == 0:
                    item.preview = Preview("info", False, "This is an empty file-table placeholder (0 bytes).")
                item.set_evidence("possibly_unused", "unknown", "Games on this cartridge type can load a file by numeric ID; absence of its name in code would not prove it unused.", "none")
                if file_id in filesystem.invalid_file_ids:
                    reason = filesystem.invalid_file_ids[file_id]
                    item.preview = Preview("info", False, reason)
                    item.finding_reasons.append(reason)
                    item.set_evidence("present_in_data", "unknown" if file.offset < source.size and file.size else "no", reason)
                items.append(item)

            code_bytes_checked = 0
            for label in ("ARM9 executable", "ARM7 executable"):
                segments = executable_segments(header, label)
                code = ContentItem("code", f"{label}: readable text strings", dict(base, offset=header.regions[label][0], size=header.regions[label][1]), {"type": "code_strings", "region": label}, Preview("text", True))
                code.details = {"bytes checked": sum(length for _, length in segments), "secure area": "not read", "disassembly": "not performed"}
                code.set_evidence("present_in_data", "yes", "Executable location is declared by the cartridge header; only bounded text checks outside the secure area were performed.")
                items.append(code)
                found = 0
                for offset, length in segments:
                    raw = source.read_at(offset, length)
                    code_bytes_checked += len(raw)
                    for match in ASCII_STRINGS.finditer(raw):
                        text = match.group().decode("ascii")
                        if not DEVELOPMENT_HINT.search(text):
                            continue
                        absolute_offset = offset + match.start()
                        item = ContentItem("text", text[:100], dict(base, offset=absolute_offset, size=len(match.group())),
                                           {"type": "code_string", "offset": absolute_offset, "size": len(match.group())}, Preview("text", True))
                        item.set_evidence("present_in_data", "yes", f"ASCII text in {label} at ROM offset 0x{absolute_offset:X}.")
                        item.set_evidence("possibly_unused", "unknown", "A development-sounding string is not proof that code can or cannot reach it.", "none")
                        item.finding_reasons.append("Executable text mentions a debug, development or selection function.")
                        items.append(item)
                        found += 1
                        if found >= 40:
                            break
                    if found >= 40:
                        break
            tiles = ContentItem("rom_region", "Raw tile browser", dict(base, offset=0, size=source.size), {"type": "tiles", "bits_per_pixel": 4}, Preview("tiles", True))
            tiles.set_evidence("present_in_data", "yes", "Any selected 32 KiB window can be viewed as raw 4-bit tiles, without palette or compression decoding.")
            items.append(tiles)
            warnings = list(filesystem.warnings)
            if header.banner_offset and banner is None:
                warnings.append("The cartridge banner could not be decoded; header and file inventory are still available.")
            return ScanReport(path=str(path), adapter=self.identifier, platform=PLATFORM_LABEL, format_name=FORMAT_LABEL,
                              title=cartridge_title(header, banner), build_label=f"{path.name}, {header.game_code}, revision {header.version}",
                              items=items, warnings=warnings,
                              limits=["File IDs, filenames and bounds are read statically. No file is labelled unused merely because its name is absent from code.",
                                      "Code is not disassembled. Text checks are limited to 2 MiB per processor and skip the entire cartridge secure area; nothing is decrypted.",
                                      "Game-specific archives, 3D model formats, compressed graphics and sound banks are not decoded. Executables of the extended mode are not analysed.",
                                      "This static scan does not start an emulator. Separately recorded runtime observations are shown per item."],
                              details={"named_files": len(filesystem.named_file_ids), "allocation_entries": len(filesystem.files), "overlay_files": len(filesystem.overlay_file_ids), "incomplete_file_ids": list(filesystem.invalid_file_ids), "code_bytes_checked": code_bytes_checked},
                              game_launch={"available": False, "reason": "This adapter provides static scans and previews. An interpreter is required for a gameplay test."})
        finally:
            source.close()

    def preview(self, path: Path, item: dict, options: dict) -> PreviewResult:
        source = FileByteSource(path)
        try:
            reference = item["reference"]
            kind = reference.get("type")
            header = cartridge_format.read_header(source)
            if kind == "header":
                return PreviewResult("text/plain; charset=utf-8", "\n".join(f"{key}: {value}" for key, value in item["details"].items()).encode("utf-8"))
            if kind in ("banner_icon", "banner_titles"):
                banner = cartridge_format.read_banner(source, header.banner_offset)
                if kind == "banner_icon":
                    return PreviewResult("image/png", cartridge_format.banner_icon_png(banner))
                return PreviewResult("text/plain; charset=utf-8", "\n\n".join(f"{language}:\n{title}" for language, title in banner["titles"].items()).encode("utf-8"))
            if kind == "file_id":
                filesystem = cartridge_format.read_file_system(source, path.name, str(path), allow_incomplete_files=True)
                file_id = int(reference["file_id"])
                if not 0 <= file_id < len(filesystem.files):
                    raise PreviewError("This file ID no longer exists. Scan the cartridge again.")
                if file_id in filesystem.invalid_file_ids:
                    raise PreviewError(filesystem.invalid_file_ids[file_id])
                return read_browser_preview(filesystem.files[file_id])
            if kind == "tiles":
                offset = max(0, min(int(options.get("offset") or 0), source.size - 1))
                bits = int(options.get("bits") or 4)
                if bits not in (2, 4):
                    raise PreviewError("The tile browser supports 2 or 4 bits per pixel.")
                columns = max(8, min(64, int(options.get("columns") or 16)))
                return PreviewResult("image/png", render_tiles(source.read_at(offset, 1024 * (16 if bits == 2 else 32)), bits, columns))
            if kind == "code_strings":
                lines = []
                for offset, length in executable_segments(header, reference["region"]):
                    for match in ASCII_STRINGS.finditer(source.read_at(offset, length)):
                        lines.append(f"0x{offset + match.start():08X}  {match.group().decode('ascii')}")
                        if len(lines) >= 4000:
                            break
                return PreviewResult("text/plain; charset=utf-8", ("\n".join(lines) or "No plain ASCII strings found in the checked regions.").encode("utf-8"))
            if kind == "code_string":
                offset, length = int(reference["offset"]), min(int(reference["size"]), 200)
                text = source.read_at(offset, length).decode("ascii", errors="replace")
                return PreviewResult("text/plain; charset=utf-8", f"ROM offset 0x{offset:X}\n\n{text}".encode("utf-8"))
            raise PreviewError("No preview is available for this cartridge item.")
        finally:
            source.close()

    def format_support(self) -> list[FormatSupport]:
        return [FormatSupport(PLATFORM_LABEL, FORMAT_LABEL, "any file name; recognised by header structure plus checksum or banner", "partial",
                              "Cartridge header and checksum, filename table, file allocation table IDs, overlay IDs, static banner icon and multilingual titles.",
                              "Development-sounding filenames and bounded executable text. Name absence is never treated as proof of unused files because games can load by file ID.",
                              "Banner, text, raw tiles, supported file-table assets; optional separately built local interpreter with actual screens, inputs, audio and private saves.",
                              "No built-in game-specific archive, 3D model, sound-bank or compression decoding; no secure-area decryption or extended-mode code analysis. New decoders can use the shared scene view. ZIP-packed images are not read.",
                              "231 locally owned cartridge images (inventories and supported previews; nine with incomplete file ranges). One exact build was additionally run in the optional local interpreter (developer menu, level selection, touch input, sound, gallery replay); this is not a compatibility claim for other cartridges.")]
