"""Adapter for disc images with a big-endian file system table.

- Unencrypted disc images: the file system table is read, every file is listed,
  and file names are compared with the text inside the main executable and the
  relocatable modules (``.rel``), which are not encrypted.
- Folders extracted by an emulator (a ``sys/`` folder with the main executable and
  a ``files/`` folder): read like a disc.
- Disc images with encrypted partitions: only the unencrypted header is read; the
  partitions are never decrypted. The report explains this.
- Compressed or packed disc image formats are recognised by their signatures and
  refused with the reason.

Images are recognised by their header signatures, not by their file names.
"""

from __future__ import annotations

import struct
from pathlib import Path

from cutcontent.core.byte_sources import FileByteSource
from cutcontent.core.content_items import Preview
from cutcontent.core.content_probe import could_be_game_file, file_head
from cutcontent.core.scan_report import ScanReport
from cutcontent.formats import file_table_disc as disc_format
from cutcontent.platforms.base import Detection, FormatSupport, PlatformAdapter, PreviewError, PreviewResult
from cutcontent.platforms.generic_folder import list_folder
from cutcontent.platforms.shared_analysis import analyse_file_list, read_browser_preview
from cutcontent.platforms.iso9660_disc import refused_report

CONVERT_HINT = "Convert a copy to a plain disc image with the emulator or tool that created it and scan that, or extract the file system with an emulator and scan the folder."
ENCRYPTED_PARTITION_REASON = "The disc partitions are encrypted. Cut Content Anything does not decrypt them. Extract the file system with an emulator and scan the extracted folder instead."
UNKNOWN_DISC = "Disc with file table or encrypted partitions"
PACKED_IMAGE_SIGNATURE = bytes.fromhex("4349534f")  # shared with compressed ISO images; told apart by the block size field
COMPRESSED_ISO_HEADER_SIZE = 0x18


def packed_disc_image_name(head: bytes) -> str | None:
    """Name of a compressed or packed disc image format that is refused, or None."""
    if len(head) < 8:
        return None
    name = disc_format.COMPRESSED_FORMATS.get(head[:4])
    if name:
        return name
    if head[:4] == PACKED_IMAGE_SIGNATURE:
        (block_size,) = struct.unpack_from("<I", head, 4)
        if block_size != COMPRESSED_ISO_HEADER_SIZE and block_size >= 0x8000 and block_size & (block_size - 1) == 0:
            return "packed disc image (signature 43 49 53 4F with a block map)"
    return None


def is_extracted_disc_folder(path: Path) -> bool:
    return (path / disc_format.MAIN_EXECUTABLE_PATH).is_file() and (path / "files").is_dir()


class FileTableDisc:
    def __init__(self, path: Path):
        self.path = path
        self.notes: list[str] = []
        self.refusal: str | None = None
        self.header = None
        if path.is_dir():
            boot = path / "sys" / "boot.bin"
            if boot.is_file():
                self.header = disc_format.read_header(FileByteSource(boot)) if boot.stat().st_size >= 0x440 else None
            vfs, warnings = list_folder(path / "files", str(path / "files"))
            system_vfs, _ = list_folder(path / "sys", str(path / "sys"))
            main_executable_name = disc_format.MAIN_EXECUTABLE_PATH.rsplit("/", 1)[-1]
            self.files = [file for file in system_vfs.files() if file.name == main_executable_name] + vfs.files()
            for file in self.files[:1]:
                file.path = disc_format.MAIN_EXECUTABLE_PATH
            self.notes += warnings
            self.container = "extracted folder"
            self.system = self.header.system if self.header else UNKNOWN_DISC
            return
        source = FileByteSource(path)
        packed = packed_disc_image_name(source.read_at(0, 16))
        if packed:
            self.refusal = f"This {packed} is not read. {CONVERT_HINT}"
            self.system, self.files, self.container = UNKNOWN_DISC, [], path.name
            return
        self.header = disc_format.read_header(source)
        if self.header is None:
            raise ValueError("No disc header with a file table was found.")
        self.system = self.header.system
        self.container = path.name
        if self.header.system == disc_format.ENCRYPTED_PARTITION_DISC:
            self.refusal = ENCRYPTED_PARTITION_REASON
            self.files = []
        else:
            self.files = disc_format.list_file_table_files(source, self.header, path.name, str(path))

    def get(self, internal_path: str):
        for file in self.files:
            if file.path == internal_path:
                return file
        return None

    @property
    def title(self) -> str:
        return self.header.name if self.header else self.path.name

    @property
    def label(self) -> str:
        if not self.header:
            return self.path.name
        return f"{self.path.name} ({self.header.game_code}{self.header.maker_code}, disc {self.header.disc_number + 1}, version {self.header.version})"


class FileTableDiscAdapter(PlatformAdapter):
    identifier = "file_table_disc"
    display_name = "Disc images with a file table, and their extracted folders"
    platform_family = "file_table_disc"

    def detect(self, path: Path) -> list[Detection]:
        if path.is_dir():
            if not is_extracted_disc_folder(path):
                return []
        elif not could_be_game_file(path):
            return []
        else:
            head = file_head(path, 0x440)
            if packed_disc_image_name(head) is None and disc_format.read_header(_HeadSource(head)) is None:
                return []
        try:
            disc = FileTableDisc(path)
        except (ValueError, OSError):
            return []
        format_name = "Extracted disc folder" if path.is_dir() else ("Disc image (not readable)" if disc.refusal else "Disc image")
        return [Detection(self.identifier, disc.system, format_name, disc.title, disc.label, str(path), 0.85, [disc.refusal] if disc.refusal else [])]

    def scan(self, path: Path) -> ScanReport:
        disc = FileTableDisc(path)
        if disc.refusal:
            report = refused_report(self.identifier, path, disc.system, disc.refusal)
            if disc.header:
                report.title = disc.title
                report.items[0].details = {"game code": disc.header.game_code, "maker code": disc.header.maker_code, "version": disc.header.version}
            return report
        executables = [file for file in disc.files if file.path == disc_format.MAIN_EXECUTABLE_PATH or file.extension in ("rel", disc_format.MAIN_EXECUTABLE_PATH.rsplit(".", 1)[-1])]
        items, limits, index = analyse_file_list(disc.files, executables, disc.container)
        for item in items:
            if item.name.endswith("opening.bnr"):
                item.kind, item.preview, item.thumbnail = "image", Preview("image", True), True
        limits.append("Only file names are compared; archives inside the disc (e.g. .arc, .szs, .rarc) are not opened.")
        return ScanReport(
            path=str(path),
            adapter=self.identifier,
            platform=disc.system,
            format_name="Extracted disc folder" if path.is_dir() else "Disc image with file table",
            title=disc.title,
            build_label=disc.label,
            items=items,
            limits=limits,
            warnings=disc.notes,
            details={"reference_sources": index.sources, "game_code": disc.header.game_code if disc.header else None},
            game_launch={"available": False, "reason": "Game start is not part of this tool; use a suitable emulator (for example through emucap) with your own disc image."},
        )

    def preview(self, path: Path, item: dict, options: dict) -> PreviewResult:
        disc = FileTableDisc(path)
        virtual_file = disc.get(item["reference"].get("path", ""))
        if virtual_file is None:
            raise PreviewError("The file was not found in the disc any more.")
        if virtual_file.name == "opening.bnr":
            png = disc_format.decode_banner(virtual_file.read())
            if png is None:
                raise PreviewError("The banner could not be decoded.")
            return PreviewResult("image/png", png)
        return read_browser_preview(virtual_file)

    def format_support(self) -> list[FormatSupport]:
        return [
            FormatSupport(disc_format.UNENCRYPTED_DISC, "Disc image", "any file name; recognised by the header signature", "partial",
                          "Disc header, file system table, main executable size.", "File names versus text in the main executable, .rel modules and text files.",
                          "opening.bnr banner (RGB5A3), PNG/WAV/text files.", "Texture, video and streamed-audio formats and packed archives inside the disc are not decoded; compressed or packed disc images are refused.",
                          "Automated tests with a self-made disc image (header, file table, executable with file names, banner); no commercial discs."),
            FormatSupport(disc_format.UNENCRYPTED_DISC, "Folder extracted by an emulator", "a sys/ folder with the main executable plus files/", "partial",
                          "File list, boot header.", "File names versus text in the main executable and .rel modules.",
                          "opening.bnr banner, PNG/WAV/text files.", "Same decoders missing as for disc images.",
                          "Automated tests with a self-made extracted folder."),
            FormatSupport(disc_format.ENCRYPTED_PARTITION_DISC, "Disc image", "any file name; recognised by the header signature", "detection_only",
                          "Unencrypted disc header (game code, name).", "None: partitions are encrypted and never decrypted.",
                          "None.", "Decryption is deliberately not implemented; extract the disc with an emulator and scan the folder.",
                          "Automated test with a self-made header-only image."),
        ]


class _HeadSource:
    """Lets the header reader inspect bytes that were already read."""

    def __init__(self, data: bytes):
        self.data = data
        self.size = len(data)

    def read_at(self, offset: int, length: int) -> bytes:
        return self.data[offset : offset + length]
