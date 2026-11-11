"""Adapter for DVD games whose directories are stored as binary trees.

- Disc images (plain images or full copies with a video partition): the tree
  directories are listed; the title comes from the certificate of the main
  executable; file names are compared with the text inside unencrypted
  executables.
- Extracted folders with such a main executable: read the same way.
- Games whose main executable uses the later, encrypted or signed format: listed,
  but executables are never decrypted, so no reference check is possible.

Images and executables are recognised by their signatures, not by file names.
"""

from __future__ import annotations

from pathlib import Path

from cutcontent.core.byte_sources import FileByteSource
from cutcontent.core.content_probe import could_be_game_file
from cutcontent.core.scan_report import ScanReport
from cutcontent.formats import tree_directory_disc
from cutcontent.platforms.base import Detection, FormatSupport, PlatformAdapter, PreviewError, PreviewResult
from cutcontent.platforms.generic_folder import list_folder
from cutcontent.platforms.shared_analysis import analyse_file_list, read_browser_preview

TREE_DIRECTORY_GAME = "DVD image with tree directories"
ENCRYPTED_TREE_DIRECTORY_GAME = "DVD image with tree directories and encrypted executables"
MAIN_EXECUTABLE_STEM = "default"
ENCRYPTED_EXECUTABLE_SIGNATURE = bytes.fromhex("58455832")
ENCRYPTED_EXECUTABLE_REASON = "The main executable uses an encrypted or signed format; Cut Content Anything does not decrypt it, so names inside the game code were not checked."


def main_executable_kind(virtual_file) -> str | None:
    """'plain' or 'encrypted' for a top-level main executable, otherwise None."""
    if "/" in virtual_file.path or virtual_file.name.rsplit(".", 1)[0].lower() != MAIN_EXECUTABLE_STEM:
        return None
    head = virtual_file.read(4)
    if head == tree_directory_disc.EXECUTABLE_SIGNATURE:
        return "plain"
    if head == ENCRYPTED_EXECUTABLE_SIGNATURE:
        return "encrypted"
    return None


class TreeDirectoryGame:
    def __init__(self, path: Path):
        self.path = path
        self.notes: list[str] = []
        if path.is_dir():
            vfs, self.notes = list_folder(path, str(path))
            self.files = vfs.files()
            self.container = "extracted folder"
            self.partition = None
        else:
            source = FileByteSource(path)
            self.partition, self.files = tree_directory_disc.list_files(source, path.name, str(path))
            self.container = path.name
        self.by_path = {file.path.lower(): file for file in self.files}
        self.main_executable = None
        self.has_encrypted_executable = False
        for file in self.files:
            kind = main_executable_kind(file)
            if kind == "plain":
                self.main_executable = file
            elif kind == "encrypted":
                self.has_encrypted_executable = True
        self.certificate = tree_directory_disc.read_executable_certificate(self.main_executable.read(64 * 1024)) if self.main_executable else None
        self.is_encrypted = self.has_encrypted_executable and self.main_executable is None
        self.platform = ENCRYPTED_TREE_DIRECTORY_GAME if self.is_encrypted else TREE_DIRECTORY_GAME

    @property
    def recognised(self) -> bool:
        return self.main_executable is not None or self.is_encrypted

    @property
    def title(self) -> str:
        return self.certificate.title if self.certificate and self.certificate.title else self.path.stem


def folder_has_main_executable(path: Path) -> bool:
    for candidate in path.glob(f"{MAIN_EXECUTABLE_STEM}.*"):
        if candidate.is_file():
            with open(candidate, "rb") as handle:
                if handle.read(4) in (tree_directory_disc.EXECUTABLE_SIGNATURE, ENCRYPTED_EXECUTABLE_SIGNATURE):
                    return True
    return False


class TreeDirectoryDiscAdapter(PlatformAdapter):
    identifier = "tree_directory_disc"
    display_name = "DVD games with tree directories"
    platform_family = "tree_directory_disc"

    def detect(self, path: Path) -> list[Detection]:
        if path.is_dir():
            if not folder_has_main_executable(path):
                return []
        elif not could_be_game_file(path):
            return []
        else:
            source = FileByteSource(path)
            try:
                if tree_directory_disc.find_partition(source) is None:
                    return []
            finally:
                source.close()
        try:
            game = TreeDirectoryGame(path)
        except (ValueError, OSError):
            return []
        if not game.recognised:
            return []
        label = path.name + (f" (title ID {game.certificate.title_id})" if game.certificate else "")
        return [Detection(self.identifier, game.platform, "Disc image" if path.is_file() else "Extracted game folder", game.title, label, str(path), 0.85)]

    def scan(self, path: Path) -> ScanReport:
        game = TreeDirectoryGame(path)
        executables = [file for file in game.files if file.read(4) == tree_directory_disc.EXECUTABLE_SIGNATURE] if not game.is_encrypted else []
        encrypted_reason = ENCRYPTED_EXECUTABLE_REASON if game.is_encrypted else None
        items, limits, index = analyse_file_list(game.files, executables, game.container, encrypted_reason)
        limits.append("Only file names are compared; archives, texture bundles and wave banks inside the game are not opened.")
        return ScanReport(
            path=str(path),
            adapter=self.identifier,
            platform=game.platform,
            format_name="Extracted game folder" if path.is_dir() else "Disc image with tree directories",
            title=game.title,
            build_label=path.name + (f", title ID {game.certificate.title_id}" if game.certificate else ""),
            items=items,
            limits=limits,
            warnings=game.notes,
            details={"reference_sources": index.sources, "partition_offset": game.partition},
            game_launch={"available": False, "reason": "Game start is not part of this tool; use a suitable emulator (for example through emucap) with your own disc image."},
        )

    def preview(self, path: Path, item: dict, options: dict) -> PreviewResult:
        game = TreeDirectoryGame(path)
        virtual_file = game.by_path.get(item["reference"].get("path", "").lower())
        if virtual_file is None:
            raise PreviewError("The file was not found any more.")
        return read_browser_preview(virtual_file)

    def format_support(self) -> list[FormatSupport]:
        return [
            FormatSupport(TREE_DIRECTORY_GAME, "Disc image or extracted folder", "any file name; recognised by the volume descriptor or the main executable signature", "partial",
                          "Tree directories, partition offsets of full disc copies, main executable certificate (title, title ID).",
                          "File names versus text in unencrypted executables and text files.",
                          "PNG/JPEG/WAV/text files.", "Console texture bundles, wave banks and game archives are not decoded.",
                          "Automated tests with a self-made image (tree directories, executable with certificate); no commercial discs."),
            FormatSupport(ENCRYPTED_TREE_DIRECTORY_GAME, "Disc image or extracted folder", "any file name; recognised by the main executable signature", "detection_only",
                          "File list.", "None: the executables are encrypted or signed and are never decrypted.",
                          "PNG/JPEG/WAV/text files.", "Encrypted executables, signed content packages and encrypted content are not read (by design).",
                          "Automated test with a self-made folder containing a dummy encrypted main executable."),
        ]
