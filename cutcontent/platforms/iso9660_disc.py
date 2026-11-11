"""Adapter for game discs with an ISO 9660 file system.

Reads the disc file system from plain ISO images, raw 2352-byte CD images (with
or without a cue sheet) and compressed ISO images, or from extracted folders.
Images are recognised by their content: the ISO 9660 volume descriptor, the
raw CD sync pattern or the compressed-image header, never by the file name.

A game is identified by one of three layouts:

- a boot configuration file (``BOOT = ...`` for CD games, ``BOOT2 = ...`` for DVD games);
- a parameter file (``PARAM.SFO``) inside a top-level folder, with the boot
  executable in that folder's ``SYSDIR`` or ``USRDIR`` subfolder;
- a plain CD executable at the top level (recognised by its signature).

Unused-content analysis compares every file name with the text inside the boot
executable and small text files. That only works when the executable is not
encrypted. Encrypted or signed executables are recognised by their signature and
never decrypted; the report then says that the check could not be made.

Compressed hunk images, packed executable packages and encrypted store packages
are recognised by their signatures and refused with the reason.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

from cutcontent.core.byte_sources import ByteSource, FileByteSource, RawCdSectorSource
from cutcontent.core.content_items import ContentItem, Preview
from cutcontent.core.content_probe import MINIMUM_GAME_FILE_SIZE, could_be_game_file, file_head, read_at
from cutcontent.core.scan_report import ScanReport
from cutcontent.core.virtual_files import VirtualFile
from cutcontent.formats import disc_metadata, iso9660
from cutcontent.platforms.base import Detection, FormatSupport, PlatformAdapter, PreviewError, PreviewResult
from cutcontent.platforms.generic_folder import list_folder
from cutcontent.platforms.shared_analysis import BROWSER_AUDIO_TYPES, BROWSER_IMAGE_TYPES, TEXT_EXTENSIONS, analyse_file_list, read_browser_preview

CD_GAME = "CD image (ISO 9660)"
DVD_GAME = "DVD image (ISO 9660)"
PARAMETER_FILE_GAME = "Disc image with parameter file (ISO 9660)"
SIGNED_EXECUTABLE_GAME = "Game folder with signed executables"
REFUSED_IMAGE = "Packed or compressed image"

BOOT_CONFIGURATION_NAME = "SYSTEM.CNF"
PARAMETER_FILE_NAME = "PARAM.SFO"
BOOT_EXECUTABLE_NAME = "EBOOT.BIN"
PLAIN_BOOT_COPY_NAME = "BOOT.BIN"
BOOT_EXECUTABLE_FOLDERS = ("SYSDIR", "USRDIR")
COMPRESSED_ISO_HEADER_SIZE = 0x18
ISO9660_DESCRIPTOR_OFFSET = 16 * 2048
EXECUTABLE_PROBE_LIMIT = 4000  # how many disc files are checked for an unencrypted executable signature

# Signatures of containers that are recognised but not read.
REFUSED_SIGNATURES = {
    b"MComprHD": "Compressed hunk images are not read yet. Convert a copy to BIN/CUE or ISO with chdman ('extractcd' or 'extractdvd') and scan that.",
    bytes.fromhex("00504250"): "Packed executable packages are not unpacked yet.",
    bytes.fromhex("7f504b47"): "Store packages are encrypted; Cut Content Anything does not decrypt them.",
}
GZIP_SIGNATURE = bytes.fromhex("1f8b")
GZIP_REASON = "Gzip-compressed data is not read directly. Decompress a separate copy and scan that; the original archive is left unchanged."


def refusal_reason(head: bytes, explicit_scan: bool = False) -> str | None:
    for signature, reason in REFUSED_SIGNATURES.items():
        if head.startswith(signature):
            return reason
    if explicit_scan and head.startswith(GZIP_SIGNATURE):
        return GZIP_REASON  # gzip files are only refused when the user scans one directly
    return None


def is_compressed_iso(head: bytes) -> bool:
    if len(head) < COMPRESSED_ISO_HEADER_SIZE or head[:4] != disc_metadata.COMPRESSED_ISO_MAGIC:
        return False
    header_size, total_size, block_size, version, alignment = struct.unpack_from("<IQIBB", head, 4)
    # Some readable local images leave the nominal header-size field at zero.
    # Validate the remaining fields before handing the image to the block reader.
    return (header_size in (0, COMPRESSED_ISO_HEADER_SIZE) and total_size > 0
            and 0 < block_size <= 1 << 20 and version <= 1 and alignment <= 31)


def disc_source_for(path: Path) -> tuple[ByteSource, str]:
    """Opens a disc image read-only as 2048-byte data sectors."""
    if path.suffix.lower() == ".cue":
        image = cue_data_file(path)
        if image is None:
            raise ValueError("The cue sheet names no data file next to it.")
        path = image
    source: ByteSource = FileByteSource(path)
    if is_compressed_iso(source.read_at(0, COMPRESSED_ISO_HEADER_SIZE)):
        return disc_metadata.CompressedIsoSource(source), path.name
    if RawCdSectorSource.looks_like_raw_cd(source):
        return RawCdSectorSource(source), path.name
    return source, path.name


def looks_like_disc_image(path: Path) -> bool:
    """ISO 9660 descriptor, raw CD sectors or a compressed ISO header."""
    head = file_head(path, COMPRESSED_ISO_HEADER_SIZE)
    if is_compressed_iso(head):
        return True
    if read_at(path, ISO9660_DESCRIPTOR_OFFSET + 1, 5) == b"CD001":
        return True
    source = FileByteSource(path)
    try:
        return RawCdSectorSource.looks_like_raw_cd(source)
    finally:
        source.close()


def cue_data_file(cue_path: Path) -> Path | None:
    try:
        text = cue_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("FILE"):
            name = stripped[4:].strip()
            if name.startswith('"'):
                name = name[1 : name.find('"', 1)]
            else:
                name = name.rsplit(" ", 1)[0]
            candidate = Path(os.path.realpath(cue_path.parent / name))
            if candidate.parent == Path(os.path.realpath(cue_path.parent)) and candidate.is_file():
                return candidate
    return None


class Iso9660Game:
    """The files of one ISO 9660 game disc (or its extracted folder) and what is known about it."""

    def __init__(self, path: Path):
        self.path = path
        self.notes: list[str] = []
        if path.is_dir():
            vfs, warnings = list_folder(path, str(path))
            self.files = vfs.files()
            self.notes += warnings
            self.container = "extracted folder"
            self.volume = None
        else:
            source, label = disc_source_for(path)
            self.volume, self.files = iso9660.list_files(source, label, str(path))
            self.container = label
        self.by_path = {file.path.upper(): file for file in self.files}
        self.platform, self.title, self.disc_id, self.boot_path, self.parameters, self.parameter_folder = self._identify()

    def get(self, path: str) -> VirtualFile | None:
        return self.by_path.get(path.upper())

    def _parameter_folders(self) -> list[str]:
        folders = []
        for file in self.files:
            parts = file.path.split("/")
            if len(parts) == 2 and parts[1].upper() == PARAMETER_FILE_NAME:
                folders.append(parts[0])
        return sorted(folders)

    def _identify(self):
        for folder in self._parameter_folders():
            parameter_file = self.get(f"{folder}/{PARAMETER_FILE_NAME}")
            try:
                parameters = disc_metadata.read_parameter_file(parameter_file.read(64 * 1024))
            except disc_metadata.DiscMetadataError:
                parameters = {}
            boot_path = None
            for subfolder in BOOT_EXECUTABLE_FOLDERS:
                if self.get(f"{folder}/{subfolder}/{BOOT_EXECUTABLE_NAME}"):
                    boot_path = f"{folder}/{subfolder}/{BOOT_EXECUTABLE_NAME}"
                    break
            platform = PARAMETER_FILE_GAME
            if boot_path and self.get(boot_path).read(4) == disc_metadata.SIGNED_EXECUTABLE_SIGNATURE:
                platform = SIGNED_EXECUTABLE_GAME
            title = str(parameters.get("TITLE", "")) or self.path.stem
            disc_id = str(parameters.get("TITLE_ID") or parameters.get("DISC_ID") or "")
            return platform, title, disc_id, boot_path, parameters, folder
        configuration = self.get(BOOT_CONFIGURATION_NAME)
        if configuration:
            boot = disc_metadata.read_boot_configuration(configuration.read(4096).decode("latin-1"))
            if boot:
                platform = DVD_GAME if boot[0] == "BOOT2" else CD_GAME
                disc_id = Path(boot[1]).name.replace("_", "-").replace(".", "")
                return platform, self.path.stem, disc_id, boot[1], {}, None
        for file in self.files:
            if "/" not in file.path and file.read(8) == disc_metadata.PLAIN_CD_EXECUTABLE_SIGNATURE:
                return CD_GAME, self.path.stem, "", file.path, {}, None
        return None, self.path.stem, "", None, {}, None


def looks_like_iso9660_game_folder(path: Path) -> bool:
    if (path / BOOT_CONFIGURATION_NAME).is_file():
        return True
    try:
        entries = list(os.scandir(path))
    except OSError:
        return False
    for entry in entries:
        if entry.is_dir() and (Path(entry.path) / PARAMETER_FILE_NAME).is_file():
            return True
    for entry in entries[:64]:
        if entry.is_file() and entry.stat().st_size >= 2048 and read_at(Path(entry.path), 0, 8) == disc_metadata.PLAIN_CD_EXECUTABLE_SIGNATURE:
            return True
    return False


class Iso9660DiscAdapter(PlatformAdapter):
    identifier = "iso9660_disc"
    display_name = "Game discs with an ISO 9660 file system"
    platform_family = "iso9660_disc"

    def detect(self, path: Path) -> list[Detection]:
        if path.is_dir():
            if not looks_like_iso9660_game_folder(path):
                return []
        elif path.suffix.lower() == ".cue":
            if cue_data_file(path) is None:
                return []
        elif not could_be_game_file(path) and path.stat().st_size >= MINIMUM_GAME_FILE_SIZE:
            return []  # ordinary documents and media are not candidate disc images
        else:
            try:
                # A short header is enough to identify a refused container.
                # Check it before the general game-image size threshold.
                reason = refusal_reason(file_head(path, 16), explicit_scan=True)
                if reason:
                    return [Detection(self.identifier, REFUSED_IMAGE, "Packed or compressed image (not supported)", path.stem, path.name, str(path), 0.4, [reason])]
                if not could_be_game_file(path):
                    return []
                if path.suffix.lower() == ".bin" and path.with_suffix(".cue").exists():
                    return []  # the cue sheet represents this disc
                if not looks_like_disc_image(path):
                    return []
            except OSError:
                return []
        try:
            game = Iso9660Game(path)
        except (ValueError, OSError, disc_metadata.DiscMetadataError, iso9660.IsoFormatError):
            return []
        if game.platform is None:
            return []
        label = f"{path.name}" + (f" ({game.disc_id})" if game.disc_id else "")
        return [Detection(self.identifier, game.platform, "Disc image" if path.is_file() else "Extracted game folder", game.title, label, str(path), 0.85)]

    def scan(self, path: Path) -> ScanReport:
        if path.is_file() and path.suffix.lower() != ".cue":
            reason = refusal_reason(file_head(path, 16), explicit_scan=True)
            if reason:
                return refused_report(self.identifier, path, REFUSED_IMAGE, reason)
        game = Iso9660Game(path)
        if game.platform is None:
            raise ValueError("No game layout was recognised on this disc (no boot configuration, parameter file or plain CD executable).")

        reference_sources, encrypted_reason = [], None
        boot = game.get(game.boot_path) if game.boot_path else None
        if boot:
            kind = disc_metadata.executable_kind(boot.read(8))
            if "unencrypted" in kind:
                reference_sources.append(boot)
            else:
                encrypted_reason = f"The boot executable {boot.path} is classified as {kind}; Cut Content Anything does not decrypt it, so names inside the game code were not checked."
        if game.parameter_folder:
            plain_boot = game.get(f"{game.parameter_folder}/{BOOT_EXECUTABLE_FOLDERS[0]}/{PLAIN_BOOT_COPY_NAME}")
            if plain_boot and plain_boot.read(4) == disc_metadata.ELF_SIGNATURE:
                reference_sources.append(plain_boot)
                encrypted_reason = None
        media_extensions = set(BROWSER_IMAGE_TYPES) | set(BROWSER_AUDIO_TYPES) | TEXT_EXTENSIONS
        for virtual_file in game.files[:EXECUTABLE_PROBE_LIMIT]:
            if virtual_file in reference_sources or virtual_file.extension in media_extensions or virtual_file.size > 64 * 1024 * 1024:
                continue
            if virtual_file.read(4) == disc_metadata.ELF_SIGNATURE:
                reference_sources.append(virtual_file)

        items, limits, index = analyse_file_list(game.files, reference_sources, game.container, encrypted_reason)
        for item in items:
            if item.name.upper().endswith(PARAMETER_FILE_NAME):
                item.kind = "text"
                parameter_file = game.get(item.name)
                try:
                    disc_metadata.read_parameter_file(parameter_file.read(64 * 1024))
                except (disc_metadata.DiscMetadataError, ValueError):
                    item.preview = Preview("info", False, "This parameter file is an empty placeholder or has no readable parameter table.")
                else:
                    item.preview = Preview("text", True)
        if game.parameters:
            limits.append("Title and disc ID come from the parameter file.")
        limits.append("Only file names are compared; data packed inside game archives is not opened.")
        return ScanReport(
            path=str(path),
            adapter=self.identifier,
            platform=game.platform,
            format_name=("Extracted game folder" if path.is_dir() else f"Disc image ({game.container})"),
            title=game.title,
            build_label=f"{path.name}" + (f", {game.disc_id}" if game.disc_id else ""),
            items=items,
            limits=limits,
            warnings=game.notes,
            details={
                "boot_executable": game.boot_path,
                "reference_sources": index.sources,
                "volume": game.volume.volume_identifier if game.volume else None,
                "parameter_file": {key: value for key, value in game.parameters.items() if isinstance(value, (str, int))},
            },
            game_launch={"available": False, "reason": "Game start is not part of this tool; use an emulator (for example through emucap) with your own disc image."},
        )

    def preview(self, path: Path, item: dict, options: dict) -> PreviewResult:
        game = Iso9660Game(path)
        virtual_file = game.get(item["reference"].get("path", ""))
        if virtual_file is None:
            raise PreviewError("The file was not found in the disc any more.")
        if virtual_file.name.upper() == PARAMETER_FILE_NAME:
            values = disc_metadata.read_parameter_file(virtual_file.read(64 * 1024))
            return PreviewResult("text/plain; charset=utf-8", "\n".join(f"{key} = {value}" for key, value in values.items()).encode("utf-8"))
        return read_browser_preview(virtual_file)

    def format_support(self) -> list[FormatSupport]:
        tested = "Automated tests with self-made disc images built by the test suite (ISO 9660, raw 2352-byte CD image with cue sheet, compressed ISO); no commercial discs."
        tested_dvd = "Self-made fixtures plus local read-only scans of two locally owned disc images (raw CD image with cue sheet, compressed ISO) on 2026-11-10; file inventory, boot metadata and boot configuration previews checked. No emulator gameplay test."
        tested_parameter = "Self-made fixtures plus local read-only scans of 28 locally owned ISO and compressed ISO images on 2026-11-10; parameter file and available icon previews checked. Empty update parameter placeholders are reported explicitly. No emulator gameplay test."
        recognised = "any file name; recognised by ISO 9660 descriptor, raw CD sync pattern or compressed ISO header"
        return [
            FormatSupport(CD_GAME, "Disc image", recognised + "; cue sheets", "partial",
                          "ISO 9660 file system, boot configuration (BOOT entry) or a plain CD executable.", "File names versus text in the unencrypted boot executable and text files.",
                          "PNG/JPEG/WAV/text files; everything else shows the reason.", "Streamed audio, video and console image formats are not decoded; only the first data track; compressed hunk images, packed packages and gzip-compressed images are refused.", tested),
            FormatSupport(DVD_GAME, "Disc image", recognised, "partial",
                          "ISO 9660 file system, boot configuration (BOOT2 entry).", "File names versus text in the unencrypted ELF boot executable, other ELF modules and text files.",
                          "PNG/JPEG/WAV/text files.", "UDF-only discs, compressed hunk images, gzip-compressed images and game archives are not read; console image and audio formats are not decoded.", tested_dvd),
            FormatSupport(PARAMETER_FILE_GAME, "Disc image", recognised, "partial",
                          "ISO 9660, parameter file (title, disc ID).", "Only if the plain boot copy in SYSDIR holds an ELF; the main boot executable is encrypted and never decrypted.",
                          "Icon PNG images, parameter values, text files.", "Console audio, video and image formats are not decoded; packed executable packages are refused.", tested_parameter),
            FormatSupport(SIGNED_EXECUTABLE_GAME, "Extracted disc folder", "a folder with a parameter file in a top-level subfolder", "detection_only",
                          "Parameter file (title, title ID), file list.", "None: the boot executable is signed and encrypted; it is never decrypted, so references cannot be checked.",
                          "Icon PNG images, parameter values.", "Encrypted disc images, signed executables, signed libraries and store packages are not decrypted (by design).",
                          "Automated tests with a self-made folder (parameter file, PNG, dummy signed executable header)."),
        ]


def refused_report(adapter: str, path: Path, platform: str, reason: str) -> ScanReport:
    """A report with one item that explains why the file cannot be read."""
    item = ContentItem("header", path.name, {"container": path.name, "container_path": str(path), "size": path.stat().st_size}, {"type": "refused"}, Preview("info", False, reason))
    item.set_evidence("present_in_data", "yes", "The file exists; its content was not read.")
    return ScanReport(
        path=str(path), adapter=adapter, platform=platform, format_name="Packed or compressed image (not supported)",
        title=path.stem, build_label=path.name, items=[item], limits=[reason],
        game_launch={"available": False, "reason": reason},
    )
