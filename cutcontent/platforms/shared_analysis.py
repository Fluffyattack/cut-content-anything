"""Analysis steps shared by all file-system based adapters (discs, folders, archives).

- :func:`name_hint`: file names that suggest development or leftover content.
- :class:`ReferenceIndex`: which file names appear as text inside the game's
  executables and index files. A file whose name appears nowhere *may* be unused.
- :func:`judge_files_by_reference`: turns that into evidence, including a safety
  check that switches the judgement off when the game clearly does not refer to
  its files by name.
- preview descriptions for formats a web browser can show directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cutcontent.core.content_items import ContentItem, Preview
from cutcontent.core.virtual_files import VirtualFile

DEVELOPMENT_NAME_PATTERN = re.compile(
    r"(?:^|[/_\-. ])(dev|devel|test|testing|debug|dbg|unused|old|beta|alpha|temp|tmp|backup|bak|copy|cut|wip|"
    r"proto|prototype|placeholder|dummy|sample|e3|kiosk|obsolete|deprecated|draft|notused|nouse)(?:[/_\-. 0-9]|$)",
    re.IGNORECASE,
)


def name_hint(path: str) -> str | None:
    match = DEVELOPMENT_NAME_PATTERN.search(path)
    if not match:
        return None
    return f"The name contains '{match.group(1)}', which often marks development, test or leftover content."


BROWSER_IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp", "webp": "image/webp"}
BROWSER_AUDIO_TYPES = {"wav": "audio/wav", "ogg": "audio/ogg", "mp3": "audio/mpeg", "flac": "audio/flac", "opus": "audio/ogg"}
TEXT_EXTENSIONS = {"txt", "ini", "cfg", "json", "xml", "lua", "csv", "md", "log", "yaml", "yml", "rc", "lst", "cnf", "inf", "htm", "html", "nfo"}
EXECUTABLE_EXTENSIONS = {"exe", "dll", "elf", "xbe", "dol", "rel", "so", "prx", "irx", "self", "sprx", "xex"}

UNSUPPORTED_FORMAT_REASONS = {
    "tpl": "TPL textures are not decoded yet.",
    "thp": "THP video is not decoded.",
    "dsp": "DSP ADPCM audio is not decoded yet.",
    "adp": "ADP streaming audio is not decoded yet.",
    "brstm": "BRSTM audio is not decoded yet.",
    "at3": "ATRAC3 audio cannot be played by web browsers and is not decoded.",
    "at9": "ATRAC9 audio cannot be played by web browsers and is not decoded.",
    "vag": "VAG ADPCM audio is not decoded yet.",
    "xa": "XA audio is not decoded yet.",
    "str": "STR video is not decoded.",
    "pmf": "PMF video is not decoded.",
    "mps": "MPEG program streams are not decoded.",
    "tm2": "TIM2 images are not decoded yet.",
    "tim": "TIM images are not decoded yet.",
    "gim": "GIM images are not decoded yet.",
    "xwb": "Wave banks are not decoded.",
    "xpr": "XPR texture bundles are not decoded yet.",
    "dds": "DDS textures are not decoded yet.",
    "tga": "TGA images are not decoded yet.",
    "pcx": "PCX images are not decoded yet.",
    "self": "Signed executables are encrypted; Cut Content Anything does not decrypt them.",
    "sprx": "Signed libraries are encrypted; Cut Content Anything does not decrypt them.",
    "xex": "These executables are encrypted or signed; Cut Content Anything does not decrypt them.",
}


def kind_for_extension(extension: str) -> str:
    if extension in BROWSER_IMAGE_TYPES or extension in {"tpl", "tm2", "tim", "gim", "dds", "tga", "pcx", "xpr", "bnr"}:
        return "image"
    if extension in BROWSER_AUDIO_TYPES or extension in {"dsp", "adp", "brstm", "at3", "at9", "vag", "xa", "xwb", "adx", "hca"}:
        return "sound"
    if extension in {"thp", "str", "pmf", "mps", "bik", "wmv", "mpg", "mp4", "avi", "sfd", "usm"}:
        return "video"
    if extension in TEXT_EXTENSIONS:
        return "text"
    if extension in EXECUTABLE_EXTENSIONS:
        return "code"
    return "file"


def preview_for_file(virtual_file: VirtualFile) -> Preview:
    extension = virtual_file.extension
    if extension in BROWSER_IMAGE_TYPES:
        return Preview("image", True)
    if extension in BROWSER_AUDIO_TYPES:
        return Preview("audio", True)
    if extension in TEXT_EXTENSIONS:
        return Preview("text", True)
    if extension in UNSUPPORTED_FORMAT_REASONS:
        return Preview("info", False, UNSUPPORTED_FORMAT_REASONS[extension])
    return Preview("info", False, f"No reader for '.{extension or 'no extension'}' files yet; only the file's location and size are shown.")


def browser_content_type(extension: str) -> str | None:
    if extension in BROWSER_IMAGE_TYPES:
        return BROWSER_IMAGE_TYPES[extension]
    if extension in BROWSER_AUDIO_TYPES:
        return BROWSER_AUDIO_TYPES[extension]
    if extension in TEXT_EXTENSIONS:
        return "text/plain; charset=utf-8"
    return None


_PRINTABLE_ASCII = re.compile(rb"[\x20-\x7e]{4,}")
_PRINTABLE_UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
_TOKEN_SPLIT = re.compile(r"[\s\"'<>|,;=()\[\]{}*?]+")
READ_CHUNK = 8 * 1024 * 1024


@dataclass
class ReferenceIndex:
    """Every path-like text found in the reference sources, normalised for lookups."""

    full_names: dict[str, set[str]] = field(default_factory=dict)  # token -> source labels
    stems: dict[str, set[str]] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    skipped_sources: list[str] = field(default_factory=list)
    bytes_scanned: int = 0

    def add_text(self, label: str, text: str) -> None:
        for token in _TOKEN_SPLIT.split(text.lower()):
            token = token.strip("./\\:")
            if len(token) < 3:
                continue
            token = token.replace("\\", "/")
            self.full_names.setdefault(token, set()).add(label)
            base = token.rsplit("/", 1)[-1]
            if base.startswith("cdrom") and ":" in base:
                base = base.split(":", 1)[1]
            base = base.split(";", 1)[0]
            self.full_names.setdefault(base, set()).add(label)
            if "." in base:
                self.stems.setdefault(base.rsplit(".", 1)[0], set()).add(label)

    def add_binary(self, label: str, virtual_file: VirtualFile, byte_limit: int) -> None:
        self.sources.append(label)
        position = 0
        limit = min(virtual_file.size, byte_limit)
        while position < limit:
            chunk = virtual_file.read_range(position, min(READ_CHUNK + 256, limit - position))
            if not chunk:
                break
            for match in _PRINTABLE_ASCII.finditer(chunk):
                self.add_text(label, match.group().decode("ascii"))
            for match in _PRINTABLE_UTF16.finditer(chunk):
                self.add_text(label, match.group().decode("utf-16-le", errors="ignore"))
            self.bytes_scanned += len(chunk)
            position += READ_CHUNK

    def lookup(self, path: str) -> tuple[str, set[str]]:
        """Returns ("full" | "stem" | "none", source labels) for a file path."""
        lowered = path.lower().replace("\\", "/")
        base = lowered.rsplit("/", 1)[-1]
        for candidate in (lowered, base):
            if candidate in self.full_names:
                return "full", self.full_names[candidate]
        stem = base.rsplit(".", 1)[0] if "." in base else base
        if len(stem) >= 4 and stem in self.stems:
            return "stem", self.stems[stem]
        if len(stem) >= 4 and stem in self.full_names:
            return "stem", self.full_names[stem]
        return "none", set()


def judge_files_by_reference(items_and_files: list[tuple[ContentItem, VirtualFile]], index: ReferenceIndex, encrypted_reason: str | None) -> list[str]:
    """Fills ``possibly_unused`` for every file item. Returns report-level limits."""
    limits = []
    if encrypted_reason:
        limits.append(encrypted_reason)
    if not index.sources:
        reason = encrypted_reason or "No readable executable or index file was found, so file name references could not be checked."
        for item, _ in items_and_files:
            item.set_evidence("possibly_unused", "unknown", reason, "none")
        if not encrypted_reason:
            limits.append(reason)
        return limits

    results = []
    for item, virtual_file in items_and_files:
        if item.kind == "code":
            item.set_evidence("possibly_unused", "not_analysed", "Executables and libraries are reference sources themselves; their own use was not analysed.", "none")
            continue
        results.append((item, virtual_file, *index.lookup(virtual_file.path)))

    unreferenced = [entry for entry in results if entry[2] == "none"]
    sources_text = ", ".join(index.sources[:6]) + (" and more" if len(index.sources) > 6 else "")
    meaningful = bool(results) and len(unreferenced) <= 0.5 * len(results)
    if not meaningful and results:
        limits.append(
            f"{len(unreferenced)} of {len(results)} file names do not appear in {sources_text}. The game probably loads "
            "files by index, hash or generated names, so a missing name reference says little here; files are marked 'unknown'."
        )
    for item, virtual_file, match, labels in results:
        if match == "full":
            item.set_evidence("possibly_unused", "no", f"The file name appears as text in {', '.join(sorted(labels)[:4])}.")
        elif match == "stem":
            item.set_evidence("possibly_unused", "unlikely", f"The name without extension appears as text in {', '.join(sorted(labels)[:4])}.")
        elif meaningful:
            item.set_evidence("possibly_unused", "yes", f"The file name does not appear as text in {sources_text}.")
            item.finding_reasons.append("No reference to the file name was found in the game's executables or index files.")
            item.limits.append("Games can build file names at runtime, load files by index or hash, or reference them from compressed archives. A missing name is a hint, not proof.")
        else:
            item.set_evidence("possibly_unused", "unknown", "The file name does not appear as text, but most files of this game do not, so this check is not meaningful here.")
    return limits


def build_items_for_files(files: list[VirtualFile], container_label: str) -> list[tuple[ContentItem, VirtualFile]]:
    """One gallery item per file, with a browser preview where the format allows it."""
    pairs = []
    for virtual_file in files:
        preview = preview_for_file(virtual_file)
        kind = kind_for_extension(virtual_file.extension)
        reference = {"type": "file", "path": virtual_file.path}
        thumbnail = preview.viewer == "image" and preview.supported and virtual_file.size < 4_000_000
        item = ContentItem(kind, virtual_file.path, virtual_file.location(), reference, preview, thumbnail=thumbnail)
        item.set_evidence("present_in_data", "yes", f"Stored as {virtual_file.path} in {container_label} ({virtual_file.size} bytes, offset {virtual_file.offset}).")
        hint = name_hint(virtual_file.path)
        if hint:
            item.finding_reasons.append(hint)
        pairs.append((item, virtual_file))
    return pairs


def analyse_file_list(
    files: list[VirtualFile],
    reference_sources: list[VirtualFile],
    container_label: str,
    encrypted_reason: str | None = None,
    executable_byte_limit: int = 128 * 1024 * 1024,
    index_size_limit: int = 4 * 1024 * 1024,
) -> tuple[list[ContentItem], list[str], ReferenceIndex]:
    """Items plus reference judgement for a disc or folder file system."""
    pairs = build_items_for_files(files, container_label)
    index = ReferenceIndex()
    for source in reference_sources:
        index.add_binary(source.path, source, executable_byte_limit)
    for virtual_file in files:
        if virtual_file in reference_sources:
            continue
        if virtual_file.extension in TEXT_EXTENSIONS and virtual_file.size <= index_size_limit:
            index.add_binary(virtual_file.path, virtual_file, index_size_limit)
    limits = judge_files_by_reference(pairs, index, encrypted_reason)
    return [item for item, _ in pairs], limits, index


def read_browser_preview(virtual_file: VirtualFile):
    """Bytes for formats a browser can show directly (images, audio, text)."""
    from cutcontent.platforms.base import PreviewError, PreviewResult

    content_type = browser_content_type(virtual_file.extension)
    if content_type is None:
        raise PreviewError(preview_for_file(virtual_file).reason or "No preview for this file type.")
    if virtual_file.size > 64 * 1024 * 1024:
        raise PreviewError("The file is larger than 64 MB and is not sent to the browser.")
    data = virtual_file.read()
    if content_type.startswith("text/"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        data = text.encode("utf-8")
    return PreviewResult(content_type, data)
