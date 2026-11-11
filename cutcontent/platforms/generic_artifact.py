"""Explicitly selected unknown files remain investigable without guessed decoding."""
from pathlib import Path

from cutcontent.core.content_items import ContentItem, Preview
from cutcontent.core.scan_report import ScanReport
from cutcontent.platforms.base import FormatSupport, PlatformAdapter, PreviewError


class GenericArtifactAdapter(PlatformAdapter):
    identifier = "generic_artifact"
    display_name = "Explicit unknown game artifact"
    platform_family = "generic"

    def detect(self, path: Path) -> list:
        # Do not turn every unknown file in a library into a separate game.
        return []

    def scan(self, path: Path) -> ScanReport:
        if not path.is_file():
            raise ValueError("Select an actual game artifact file.")
        with path.open("rb") as handle:
            signature = handle.read(32)
        item = ContentItem("file", path.name,
                           {"container": str(path), "internal_path": path.name, "offset": 0, "size": path.stat().st_size},
                           {"type": "opaque_artifact"},
                           Preview("info", False, "The format needs a real reader/decoder before its content can be shown."),
                           details={"signature_hex": signature.hex(), "decoded": False})
        return ScanReport(str(path), self.identifier, "Undetermined", "Opaque game artifact", path.stem,
                          f"{path.stat().st_size} bytes", [item],
                          limits=["Only file identity, size and the first 32 signature bytes were read. Internal contents, encryption and asset meaning are unknown; an appropriate reader is the next investigation step."])

    def preview(self, path: Path, item: dict, options: dict):
        raise PreviewError("Decode the actual format and register its source-bound scene or asset preview first.")

    def format_support(self) -> list:
        return [FormatSupport("Undetermined", "Explicit unknown artifact", "any directly selected file", "detection_only",
                              "Size, source location and first 32 signature bytes.", "None until the real format is decoded.",
                              "Metadata; shared scene view after a tested decoder export.",
                              "No assumed container, encryption, geometry, unused status or runtime behavior.",
                              "Read-only signature checks; decoded results require their own real-input verification.")]
