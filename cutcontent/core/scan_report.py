"""Scan reports: what was scanned, with which adapter, and every item found.

Reports are stored as JSON in ``<data directory>/reports/<build id>.json``.
Evidence that agents or people record later (for example "loaded under test
conditions" after an emulator run) is kept in a separate file
``<data directory>/evidence/<build id>.json`` and merged in when a report is
loaded, so a new scan never throws away runtime observations.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from cutcontent import __version__
from cutcontent.core.content_items import EVIDENCE_LEVELS, METHODS, STATUS_TEXT, ContentItem
from cutcontent.core.settings import data_directory, ensure_data_directory, write_json_atomically

SUMMARY_FIELDS = ("build_id", "path", "adapter", "platform", "format_name", "title", "build_label", "scanned_at", "statistics")


@lru_cache(maxsize=512)
def _detect_current_source(path: str, size: int, modified_nanoseconds: int):
    """Cache source identity checks while older reports are opened in the gallery."""
    from cutcontent.core.service import detect_path
    detections = detect_path(Path(path))
    return detections[0] if detections else None


def current_report_metadata(report: dict) -> dict:
    """Resolve removed adapter identifiers from the original game file.

    Older private reports retain their item IDs and recorded evidence. Their
    display labels and preview adapter are refreshed in memory, without editing
    the original report or guessing from its old platform label.
    """
    from cutcontent.platforms import adapter_by_identifier

    try:
        adapter_by_identifier(report.get("adapter", ""))
        return report
    except KeyError:
        pass

    source_path = report.get("path", "")
    source = Path(source_path) if isinstance(source_path, str) and source_path else None
    detection = None
    if source is not None:
        try:
            information = source.stat()
            detection = _detect_current_source(str(source), information.st_size, information.st_mtime_ns)
        except OSError:
            pass
    if detection:
        report["adapter"] = detection.adapter
        report["platform"] = detection.platform
        report["format_name"] = detection.format_name
    else:
        # A missing source can still be inspected as a historical report.
        # Its original preview is unavailable until the file is restored.
        report["adapter"] = "generic_folder" if source is not None and source.is_dir() else "generic_artifact"
        report["platform"] = "Undetermined"
        report["format_name"] = "Previously scanned data (source unavailable)"
    return report


def build_identifier(path: Path | str) -> str:
    """A stable short identifier for a scanned file or folder (based on its full path)."""
    resolved = os.path.realpath(os.fspath(path))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


@dataclass
class ScanReport:
    path: str
    adapter: str
    platform: str
    format_name: str
    title: str
    build_label: str
    items: list[ContentItem] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    game_launch: dict = field(default_factory=dict)
    scanned_at: str = ""
    build_id: str = ""

    def __post_init__(self):
        if not self.build_id:
            self.build_id = build_identifier(self.path)
        if not self.scanned_at:
            self.scanned_at = _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds")

    def statistics(self) -> dict:
        by_kind: dict[str, int] = {}
        findings_by_kind: dict[str, int] = {}
        for item in self.items:
            by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
            if item.is_finding:
                findings_by_kind[item.kind] = findings_by_kind.get(item.kind, 0) + 1
        return {
            "items": len(self.items),
            "findings": sum(findings_by_kind.values()),
            "items_by_kind": by_kind,
            "findings_by_kind": findings_by_kind,
        }

    def to_dict(self) -> dict:
        return {
            "format_version": 1,
            "tool_version": __version__,
            "build_id": self.build_id,
            "path": self.path,
            "adapter": self.adapter,
            "platform": self.platform,
            "format_name": self.format_name,
            "title": self.title,
            "build_label": self.build_label,
            "scanned_at": self.scanned_at,
            "statistics": self.statistics(),
            "limits": self.limits,
            "warnings": self.warnings,
            "details": self.details,
            "game_launch": self.game_launch,
            "items": [item.to_dict() for item in self.items],
        }


def reports_directory() -> Path:
    return data_directory() / "reports"


def evidence_directory() -> Path:
    return data_directory() / "evidence"


def report_summaries_directory() -> Path:
    return data_directory() / "report-summaries"


def report_source_signature(path: Path) -> list[int]:
    metadata = path.stat()
    signature = [metadata.st_size, metadata.st_mtime_ns]
    scene_index = data_directory() / "decoded-scenes" / "builds" / path.name
    if scene_index.is_file():
        scene_metadata = scene_index.stat()
        signature += [scene_metadata.st_size, scene_metadata.st_mtime_ns]
    return signature


def cache_report_summary(path: Path, report: dict) -> dict:
    """The library needs only metadata, not hundreds of megabytes of asset rows."""
    summary = {key: report.get(key) for key in SUMMARY_FIELDS}
    write_json_atomically(report_summaries_directory() / path.name,
                          {"source_signature": report_source_signature(path), "summary": summary})
    return summary


def save_report(report: ScanReport) -> Path:
    ensure_data_directory()
    path = reports_directory() / f"{report.build_id}.json"
    payload = report.to_dict()
    write_json_atomically(path, payload)
    from cutcontent.core.decoded_scenes import attach_decoded_scenes
    attach_decoded_scenes(payload)
    cache_report_summary(path, payload)
    return path


def load_report(build_id: str) -> dict | None:
    if not build_id.isalnum():
        return None
    path = reports_directory() / f"{build_id}.json"
    if not path.is_file():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    current_report_metadata(report)
    from cutcontent.core.decoded_scenes import attach_decoded_scenes
    from cutcontent.core.release_history import apply_release_history
    attach_decoded_scenes(report)
    apply_recorded_evidence(report)
    apply_release_history(report)
    return report


def list_reports() -> list[dict]:
    directory = reports_directory()
    if not directory.is_dir():
        return []
    summaries = []
    for path in sorted(directory.glob("*.json")):
        try:
            metadata = path.stat()
            try:
                cached = json.loads((report_summaries_directory() / path.name).read_text(encoding="utf-8"))
                if cached.get("source_signature") == report_source_signature(path) and isinstance(cached.get("summary"), dict):
                    summary = cached["summary"]
                    old_labels = (summary.get("adapter"), summary.get("platform"), summary.get("format_name"))
                    current_report_metadata(summary)
                    if old_labels != (summary.get("adapter"), summary.get("platform"), summary.get("format_name")):
                        cache_report_summary(path, summary)
                    summaries.append(summary)
                    continue
            except (OSError, ValueError, AttributeError):
                pass
            report = json.loads(path.read_text(encoding="utf-8"))
            current_report_metadata(report)
            from cutcontent.core.decoded_scenes import attach_decoded_scenes
            attach_decoded_scenes(report)
        except (OSError, ValueError):
            continue
        summaries.append(cache_report_summary(path, report))
    return summaries


def load_recorded_evidence(build_id: str) -> dict:
    path = evidence_directory() / f"{build_id}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_evidence(build_id: str, item_id: str, level: str, status: str, basis: str, method: str = "agent", access_route: str | None = None) -> dict:
    """Stores an observation for one item, e.g. after testing it in an emulator."""
    if level not in EVIDENCE_LEVELS:
        raise ValueError(f"Unknown evidence level '{level}'. Use one of: {', '.join(EVIDENCE_LEVELS)}")
    if status not in STATUS_TEXT:
        raise ValueError(f"Unknown status '{status}'. Use one of: {', '.join(STATUS_TEXT)}")
    if method not in METHODS:
        raise ValueError(f"Unknown method '{method}'. Use one of: {', '.join(METHODS)}")
    if not basis.strip():
        raise ValueError("Describe the basis of the observation (what was done and what was seen).")
    if access_route is not None and (level != "loaded_under_test" or access_route not in ("direct_start", "debug_menu", "normal_play")):
        raise ValueError("Record a known runtime access route only for loaded_under_test.")
    ensure_data_directory()
    recorded = load_recorded_evidence(build_id)
    entry = {
        "status": status,
        "basis": basis.strip(),
        "method": method,
        "recorded_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    if access_route is not None:
        entry["access_route"] = access_route
    recorded.setdefault(item_id, {})[level] = entry
    write_json_atomically(evidence_directory() / f"{build_id}.json", recorded)
    return entry


def apply_recorded_evidence(report: dict) -> None:
    recorded = load_recorded_evidence(report.get("build_id", ""))
    if not recorded:
        return
    for item in report.get("items", []):
        for level, entry in recorded.get(item["id"], {}).items():
            item["evidence"][level] = dict(entry, recorded=True)
