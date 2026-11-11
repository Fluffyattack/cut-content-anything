"""Fallback adapter for PC games and extracted game folders without a dedicated reader.

It lists every file, previews formats a browser can show (PNG, JPEG, WAV, OGG,
text), and checks which file names appear as text inside the game's
executables (``.exe``, ``.dll``, ``.so``, ELF files) and small index or text
files. Names that appear nowhere are *possibly unused*; the shared safety check
turns this off when most names are missing (games that load files by index).
"""

from __future__ import annotations

import os
from pathlib import Path

from cutcontent.core.byte_sources import LazyFileByteSource
from cutcontent.core.content_items import ContentItem
from cutcontent.core.scan_report import ScanReport
from cutcontent.core.virtual_files import VirtualFile, VirtualFileSystem
from cutcontent.platforms.base import Detection, FormatSupport, PlatformAdapter, PreviewError, PreviewResult
from cutcontent.platforms.shared_analysis import (
    ReferenceIndex,
    browser_content_type,
    judge_files_by_reference,
    kind_for_extension,
    name_hint,
    preview_for_file,
)

FILE_LIMIT = 20000
EXECUTABLE_BYTE_LIMIT = 256 * 1024 * 1024
INDEX_FILE_SIZE_LIMIT = 4 * 1024 * 1024
INDEX_EXTENSIONS = {"txt", "ini", "cfg", "json", "xml", "lua", "lst", "csv", "dat", "def", "inf", "scr", "script", "yaml", "yml"}
NATIVE_EXECUTABLE_EXTENSIONS = {"exe", "dll", "so", "elf", "dylib"}
ELF_MAGIC = b"\x7fELF"
WINDOWS_EXECUTABLE_MAGIC = b"MZ"


def list_folder(root: Path, description: str) -> tuple[VirtualFileSystem, list[str]]:
    vfs = VirtualFileSystem(description)
    warnings = []
    count = 0
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories if not name.startswith("."))
        for file_name in sorted(files):
            full_path = os.path.join(directory, file_name)
            if os.path.islink(full_path) or not os.path.isfile(full_path):
                continue
            size = os.path.getsize(full_path)
            relative = os.path.relpath(full_path, root).replace(os.sep, "/")
            vfs.add(VirtualFile(relative, size, LazyFileByteSource(full_path, size), 0, "folder", full_path))
            count += 1
            if count >= FILE_LIMIT:
                warnings.append(f"Stopped listing after {FILE_LIMIT} files; the rest of the folder was not analysed.")
                return vfs, warnings
    return vfs, warnings


def is_native_executable(virtual_file: VirtualFile) -> bool:
    if virtual_file.extension in NATIVE_EXECUTABLE_EXTENSIONS:
        return True
    head = virtual_file.read(4)
    return head == ELF_MAGIC


def build_file_items(vfs: VirtualFileSystem, container_label: str) -> list[tuple[ContentItem, VirtualFile]]:
    pairs = []
    for virtual_file in vfs.files():
        preview = preview_for_file(virtual_file)
        kind = kind_for_extension(virtual_file.extension)
        reference = {"type": "file", "path": virtual_file.path}
        item = ContentItem(kind, virtual_file.path, virtual_file.location(), reference, preview, thumbnail=preview.viewer == "image" and preview.supported and virtual_file.size < 4_000_000)
        item.set_evidence("present_in_data", "yes", f"Stored as {virtual_file.path} in {container_label} ({virtual_file.size} bytes).")
        hint = name_hint(virtual_file.path)
        if hint:
            item.finding_reasons.append(hint)
        pairs.append((item, virtual_file))
    return pairs


def read_previewable_file(virtual_file: VirtualFile) -> PreviewResult:
    content_type = browser_content_type(virtual_file.extension)
    if content_type is None:
        raise PreviewError(preview_for_file(virtual_file).reason or "No preview for this file type.")
    if content_type.startswith("text/"):
        raw = virtual_file.read(2_000_000)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        return PreviewResult(content_type, text.encode("utf-8"))
    if virtual_file.size > 64 * 1024 * 1024:
        raise PreviewError("The file is larger than 64 MB and is not sent to the browser.")
    return PreviewResult(content_type, virtual_file.read())


class GenericFolderAdapter(PlatformAdapter):
    identifier = "generic_folder"
    display_name = "Other PC games and extracted game folders"
    platform_family = "pc"

    def detect(self, path: Path) -> list[Detection]:
        """Only folders with a Windows or Linux executable at the top level count as a PC game."""
        if not path.is_dir():
            return []
        try:
            entries = list(os.scandir(path))
        except OSError:
            return []
        executables = []
        for entry in entries:
            if not entry.is_file():
                continue
            lower = entry.name.lower()
            if lower.endswith(".exe"):
                executables.append(entry.name)
        if not executables:
            return []
        return [Detection(self.identifier, "PC", "Game folder", path.name, f"{len(entries)} entries, {executables[0]}", str(path), 0.3)]

    def scan(self, path: Path) -> ScanReport:
        if not path.is_dir():
            raise ValueError(f"{path} is not a folder. Single files are only supported by the platform adapters.")
        vfs, warnings = list_folder(path, str(path))
        pairs = build_file_items(vfs, "the game folder")
        index = ReferenceIndex()
        for virtual_file in vfs.files():
            if is_native_executable(virtual_file):
                index.add_binary(virtual_file.path, virtual_file, EXECUTABLE_BYTE_LIMIT)
            elif virtual_file.extension in INDEX_EXTENSIONS and virtual_file.size <= INDEX_FILE_SIZE_LIMIT:
                index.add_binary(virtual_file.path, virtual_file, INDEX_FILE_SIZE_LIMIT)
        limits = judge_files_by_reference(pairs, index, None)
        limits.append("Generic folder analysis only compares file names with text found in executables and index files; game-specific archive formats are not opened.")
        return ScanReport(
            path=str(path),
            adapter=self.identifier,
            platform="PC",
            format_name="Game folder (generic)",
            title=path.name,
            build_label=f"{len(vfs)} files",
            items=[item for item, _ in pairs],
            limits=limits,
            warnings=warnings,
            details={"reference_sources": index.sources[:50], "reference_bytes_scanned": index.bytes_scanned},
            game_launch={"available": False, "reason": "No game start integration exists for generic PC folders."},
        )

    def preview(self, path: Path, item: dict, options: dict) -> PreviewResult:
        relative = item["reference"].get("path", "")
        full_path = Path(os.path.realpath(path / relative))
        if os.path.commonpath([str(full_path), os.path.realpath(path)]) != os.path.realpath(path) or not full_path.is_file():
            raise PreviewError("The file is not inside the scanned folder any more.")
        size = full_path.stat().st_size
        return read_previewable_file(VirtualFile(relative, size, LazyFileByteSource(full_path, size), 0, "folder", str(full_path)))

    def format_support(self) -> list[FormatSupport]:
        return [
            FormatSupport(
                "PC",
                "Any game folder (fallback)",
                "folders",
                "partial",
                "File list (up to 20,000 files), text inside executables and small index files.",
                "File names that appear in no executable or index file; development-sounding names. Turned off when most names are missing.",
                "PNG, JPEG, GIF, BMP, WebP, WAV, OGG, MP3, FLAC and text files.",
                "Game archives (e.g. Unity, Unreal PAK, ZIP-based) are not opened; models and levels of unknown engines are not shown.",
                "Automated tests with a self-made folder (fake executable with file names, images, sounds).",
            )
        ]
