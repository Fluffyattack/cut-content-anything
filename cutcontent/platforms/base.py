"""The interface every platform adapter implements.

An adapter answers four questions for its platform family:

1. ``detect(path)``: is this file or folder a game or build I understand?
2. ``scan(path)``: what content does it hold, and what might be unused?
3. ``preview(path, item, options)``: give me a browser-friendly view of one item.
4. ``format_support()``: what exactly is supported, and how was it tested?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cutcontent.core.scan_report import ScanReport

SUPPORT_LEVELS = {
    "tested": "read, analysed and previewed; covered by automated tests",
    "partial": "partly supported; see the notes",
    "detection_only": "recognised and described, content is not read",
    "not_supported": "recognised, then refused with a reason",
}


@dataclass
class Detection:
    adapter: str
    platform: str
    format_name: str
    title: str
    build_label: str
    path: str
    confidence: float = 0.5
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "adapter": self.adapter,
            "platform": self.platform,
            "format_name": self.format_name,
            "title": self.title,
            "build_label": self.build_label,
            "path": self.path,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class FormatSupport:
    platform: str
    format_name: str
    extensions: str
    level: str  # key of SUPPORT_LEVELS
    reads: str
    analysis: str
    previews: str
    not_supported: str
    tested_with: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class PreviewResult:
    content_type: str
    body: bytes


class PreviewError(Exception):
    """A preview that cannot be produced; the message is shown to the user."""


class PlatformAdapter:
    identifier = "base"
    display_name = "Base adapter"
    platform_family = "none"

    def detect(self, path: Path) -> list[Detection]:
        return []

    def scan(self, path: Path) -> ScanReport:
        raise NotImplementedError

    def preview(self, path: Path, item: dict, options: dict) -> PreviewResult:
        raise PreviewError("This adapter has no previews.")

    def format_support(self) -> list[FormatSupport]:
        return []
