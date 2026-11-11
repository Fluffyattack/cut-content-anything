"""The evidence model: what a scan found and how sure we are about it.

Every item in a report (a map, a model, a texture, a sound, an entity, a ROM
region ...) carries four separate evidence levels. They are deliberately kept
apart, because "it is in the files" is a much weaker statement than "players
can reach it":

``present_in_data``
    The content exists in the scanned data (always backed by a location).
``possibly_unused``
    Static analysis found no reference that would use it. Static only.
``loaded_under_test``
    The content was observed loading at runtime under test conditions
    (engine console, emulator, debugger). Only set from real observations,
    for example recorded with ``cutcontent evidence set`` after an emucap test.
``reachable_in_normal_play``
    Whether a player can reach it without cheats or debug tools.

Each level has a ``status`` (see ``STATUS_TEXT``), a ``method`` (how the status was
determined) and a plain-language ``basis``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

EVIDENCE_LEVELS = (
    "present_in_data",
    "possibly_unused",
    "loaded_under_test",
    "reachable_in_normal_play",
)

EVIDENCE_LEVEL_TITLES = {
    "present_in_data": "Present in the data",
    "possibly_unused": "Possibly unused",
    "loaded_under_test": "Loaded under test conditions",
    "reachable_in_normal_play": "Reachable in normal play",
}

STATUS_TEXT = {
    "yes": "yes",
    "no": "no",
    "likely": "likely",
    "unlikely": "unlikely",
    "unknown": "unknown",
    "not_checked": "not checked",
    "not_analysed": "not analysed",
}

METHODS = {
    "static": "static analysis of the files",
    "runtime": "observed at runtime",
    "agent": "recorded by an agent or person",
    "none": "no check",
}

PREVIEW_VIEWERS = ("map3d", "model3d", "image", "audio", "text", "tiles", "info")


@dataclass
class Evidence:
    status: str
    basis: str
    method: str = "static"

    def to_dict(self) -> dict:
        return {"status": self.status, "basis": self.basis, "method": self.method}


@dataclass
class Preview:
    """How the item can be shown in the web interface, or why it cannot."""

    viewer: str  # one of PREVIEW_VIEWERS
    supported: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {"viewer": self.viewer, "supported": self.supported, "reason": self.reason}


@dataclass
class ContentItem:
    kind: str  # map, model, sprite, texture, image, sound, music, text, code, entity, file, rom_region, header
    name: str
    location: dict
    reference: dict  # private: how the adapter finds the bytes again for previews
    preview: Preview
    evidence: dict[str, Evidence] = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    finding_reasons: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    thumbnail: bool = False  # True if the image preview is small enough for the gallery
    item_id: str = ""

    def __post_init__(self):
        if not self.item_id:
            key = repr(sorted(self.reference.items())) + self.kind + self.name
            self.item_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        for level in EVIDENCE_LEVELS:
            self.evidence.setdefault(level, default_evidence(level))

    @property
    def is_finding(self) -> bool:
        return bool(self.finding_reasons)

    def set_evidence(self, level: str, status: str, basis: str, method: str = "static") -> None:
        if level not in EVIDENCE_LEVELS:
            raise ValueError(f"Unknown evidence level: {level}")
        self.evidence[level] = Evidence(status, basis, method)

    def to_dict(self) -> dict:
        return {
            "id": self.item_id,
            "kind": self.kind,
            "name": self.name,
            "location": self.location,
            "reference": self.reference,
            "preview": self.preview.to_dict(),
            "evidence": {level: self.evidence[level].to_dict() for level in EVIDENCE_LEVELS},
            "details": self.details,
            "is_finding": self.is_finding,
            "finding_reasons": self.finding_reasons,
            "limits": self.limits,
            "thumbnail": self.thumbnail,
        }


def default_evidence(level: str) -> Evidence:
    if level == "present_in_data":
        return Evidence("yes", "The item was read from the scanned data at the given location.")
    if level == "loaded_under_test":
        return Evidence("not_checked", "No runtime test has been recorded for this item.", "none")
    if level == "reachable_in_normal_play":
        return Evidence("unknown", "Reachability in normal play was not determined.", "none")
    return Evidence("not_analysed", "This adapter has no reference analysis for this kind of item.", "none")
