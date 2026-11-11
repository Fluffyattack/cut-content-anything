"""Question-led retrieval across every adapter's real inventory and text.

The agent supplies concepts and content kinds after interpreting the request.
This module records literal supporting bytes/metadata; it does not pretend that
a matching name proves the identity, history or playability of a map.
"""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from pathlib import Path

from cutcontent.core.settings import data_directory, write_json_atomically

MAXIMUM_SEARCH_TERMS = 64
MAXIMUM_TEXT_BYTES = 16 * 1024 * 1024
MAXIMUM_TEXT_PREVIEWS = 256


def normalise_search_text(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(character))


def search_report(report: dict, terms: list[str], kinds: list[str] | None = None,
                  include_text: bool = True, limit: int = 100) -> dict:
    if len(terms) > MAXIMUM_SEARCH_TERMS or not 1 <= limit <= 1000:
        raise ValueError("Use at most 64 search concepts and a result limit from 1 to 1000.")
    terms = list(dict.fromkeys(term.strip() for term in terms if term.strip()))
    if any(len(term) > 200 for term in terms):
        raise ValueError("Each search concept must contain at most 200 characters.")
    selected_kinds = set(kinds or [])
    candidates = []
    preview_count = text_bytes = 0
    unreadable = []
    text_budget_exhausted = False
    for item in report.get("items", []):
        matches = []
        score = 0
        kind_match = bool(selected_kinds and item["kind"] in selected_kinds)
        if kind_match:
            matches.append({"field": "content_kind", "value": item["kind"]})
            score += 2
        fields = {"name": item["name"], "internal_path": item.get("location", {}).get("internal_path", ""),
                  "details": json.dumps(item.get("details", {}), ensure_ascii=False),
                  "scanner_findings": "\n".join(item.get("finding_reasons", []))}
        for field, value in fields.items():
            folded = normalise_search_text(str(value))
            for term in terms:
                position = folded.find(normalise_search_text(term))
                if position >= 0:
                    matches.append({"field": field, "term": term, "excerpt": str(value)[max(0, position - 80):position + len(term) + 160]})
                    score += 3 if field in ("name", "internal_path") else 1
        if include_text and terms and item.get("preview", {}).get("viewer") == "text" and item["preview"].get("supported"):
            if preview_count >= MAXIMUM_TEXT_PREVIEWS or text_bytes >= MAXIMUM_TEXT_BYTES:
                text_budget_exhausted = True
            else:
                from cutcontent.core.service import preview_item
                try:
                    preview = preview_item(report["build_id"], item["id"])
                    remaining = MAXIMUM_TEXT_BYTES - text_bytes
                    raw = preview.body[:remaining]
                    text_budget_exhausted |= len(preview.body) > remaining
                    text_bytes += len(raw)
                    preview_count += 1
                    text = raw.decode("utf-8", errors="replace")
                    folded = normalise_search_text(text)
                    for term in terms:
                        position = folded.find(normalise_search_text(term))
                        if position >= 0:
                            matches.append({"field": "decoded_text", "term": term,
                                            "excerpt": text[max(0, position - 80):position + len(term) + 160]})
                            score += 4
                except (OSError, ValueError) as error:
                    unreadable.append({"item_id": item["id"], "reason": str(error)})
        if matches:
            candidates.append({"item_id": item["id"], "kind": item["kind"], "name": item["name"],
                               "score": score, "matches": matches[:32], "location": item.get("location", {}),
                               "preview": item.get("preview", {}), "evidence": item["evidence"],
                               "release_history": item.get("release_history", {})})
    candidates.sort(key=lambda item: (-item["score"], item["name"].casefold()))
    return {
        "build_id": report["build_id"], "terms": terms, "requested_kinds": sorted(selected_kinds),
        "candidate_count": len(candidates), "candidates": candidates[:limit],
        "coverage": {"inventory_items_checked": len(report.get("items", [])), "text_previews_read": preview_count,
                     "text_bytes_read": text_bytes, "text_budget_exhausted": text_budget_exhausted,
                     "results_truncated": len(candidates) > limit, "preview_errors": unreadable,
                     "reader_limits": report.get("limits", []) + report.get("warnings", []),
                     "meaning": "Inventory/decoded-text retrieval only. Unopened archives, unknown formats and unreadable areas are not searched contents. No hits do not prove absence."},
    }


def create_investigation(build_id: str, question: str, terms: list[str] | None = None,
                         kinds: list[str] | None = None) -> dict:
    from cutcontent.core.scan_report import load_report
    from cutcontent.core.folders import require_inside_allowed_folder
    report = load_report(build_id)
    if report is None:
        raise ValueError("Scan the selected game first.")
    require_inside_allowed_folder(report["path"])
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
        raise ValueError("Describe the investigation in 1 to 4000 characters.")
    search = search_report(report, terms or [], kinds or [], include_text=True)
    case_id = uuid.uuid4().hex[:16]
    directory = data_directory() / "investigations" / case_id
    directory.mkdir(parents=True, mode=0o700)
    request = {"id": case_id, "build_id": build_id, "question": question.strip(), "status": "investigating",
               "terms": terms or [], "content_kinds": kinds or [],
               "next_work": "Interpret the question, expand concepts, inspect real containers and references, research public sources, decode and display relevant content, and verify runtime claims. Retrieval is not a completed investigation."}
    write_json_atomically(directory / "request.json", request)
    write_json_atomically(directory / "search.json", search)
    return {"investigation": request, "search": search}
