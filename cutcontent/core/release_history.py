"""Source-backed release history, separate from unused and runtime evidence."""
from __future__ import annotations

import datetime
import json
from urllib.parse import urlparse

from cutcontent.core.settings import data_directory, write_json_atomically

RELEASE_LABELS = {
    "unknown": "Release history not checked",
    "unreleased_candidate": "Possible unreleased content",
    "unreleased_confirmed": "Unreleased content · supported by sources",
    "released": "Release supported by sources",
}
RELEASE_SCOPES = {
    "playable_release": "Regular playable release",
    "asset_distribution": "Distribution of the data",
    "project_release": "Release of the game",
}


def _history(build_id: str) -> dict:
    path = data_directory() / "release-history" / (build_id + ".json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_release_history(build_id: str, item_id: str, status: str, basis: str,
                           sources: list[str], scope: str = "playable_release") -> dict:
    from cutcontent.core.scan_report import load_report
    report = load_report(build_id)
    if report is None or not any(item["id"] == item_id for item in report["items"]):
        raise ValueError("Select an existing item from a scanned game.")
    if status not in RELEASE_LABELS or scope not in RELEASE_SCOPES:
        raise ValueError("Unknown release status or scope.")
    if not basis.strip():
        raise ValueError("Describe what the checked sources actually establish.")
    for source in sources:
        parsed = urlparse(source)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use public source-page URLs without credentials.")
    if status != "unknown" and not sources:
        raise ValueError("A publication-history finding needs checked public sources.")
    label = "Release history remains unresolved" if status == "unknown" else RELEASE_LABELS[status]
    entry = {"status": status, "label": label, "scope": scope,
             "scope_label": RELEASE_SCOPES[scope], "basis": basis.strip(), "sources": sources,
             "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
             "method": "source_research", "recorded": True}
    recorded = _history(build_id)
    recorded[item_id] = entry
    write_json_atomically(data_directory() / "release-history" / (build_id + ".json"), recorded)
    return entry


def apply_release_history(report: dict) -> None:
    recorded = _history(report["build_id"])
    for item in report.get("items", []):
        item["release_history"] = recorded.get(item["id"], {
            "status": "unknown", "label": RELEASE_LABELS["unknown"],
            "basis": "Filenames, debug menus and missing game references do not establish release history.",
            "sources": [], "recorded": False,
        })
        history = item["release_history"]
        history["label"] = "Release history remains unresolved" if history.get("recorded") and history["status"] == "unknown" else RELEASE_LABELS[history["status"]]
        if history.get("scope") in RELEASE_SCOPES:
            history["scope_label"] = RELEASE_SCOPES[history["scope"]]
