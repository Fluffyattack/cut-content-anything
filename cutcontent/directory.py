"""The shared directory of documented hidden, unused and cut content.

``data/directory.json`` is the single source of truth. Every entry describes one
piece of content in one game and keeps the four evidence statements, the release
history and the quality level separate, exactly like a finding in the gallery.
``DIRECTORY.md`` is generated from it with ``cutcontent directory build``; never
edit the table by hand.

The directory serves two purposes:

- before an investigation, an agent checks what other people already documented
  for the game ("verify what is known");
- after an investigation, the agent contributes its checked result back.

The data format is plain JSON so the project keeps working with the Python
standard library only.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from cutcontent.core.release_history import RELEASE_LABELS, RELEASE_SCOPES

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DIRECTORY_DATA = REPOSITORY_ROOT / "data" / "directory.json"
DIRECTORY_PAGE = REPOSITORY_ROOT / "DIRECTORY.md"

CONTENT_KINDS = ("map", "level", "character", "enemy", "item", "weapon", "model", "texture",
                 "audio", "music", "text", "dialogue", "menu", "mechanic", "code", "other")
EVIDENCE_STATEMENTS = {
    "present_in_data": "Present in the data",
    "possibly_unused": "Possibly unused",
    "loaded_under_test": "Loaded under test conditions",
    "reachable_in_normal_play": "Reachable in normal play",
}
EVIDENCE_ANSWERS = ("yes", "no", "unknown")
# The same release vocabulary as `cutcontent release set` (cutcontent/core/release_history.py).
RELEASE_STATUSES = RELEASE_LABELS

# Quality levels say how an entry was proven. They only ever go up with new evidence.
QUALITY_LEVELS = {
    "source-reports": "A public source was opened and states it; not yet checked in actual data",
    "data-verified": "The actual bytes or code were located in an identified build",
    "runtime-verified": "Loaded and observed in the actual game, engine or emulator for an identified build",
}
REQUIRED_FIELDS = ("game", "item", "kind", "platforms", "engine", "summary", "evidence",
                   "release", "quality", "sources", "checked")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_entries(path: Path = DIRECTORY_DATA) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError(f"{path.name} must be an object with an 'entries' list")
    return payload["entries"]


def entry_identifier(entry: dict) -> str:
    """A stable, readable identifier such as 'librequake/maps-dev-bsp'."""
    def slug(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return f"{slug(entry.get('game', ''))}/{slug(entry.get('item', ''))}"


def validate_entry(entry: dict) -> list[str]:
    """Returns every rule an entry breaks; an empty list means it is valid."""
    label = entry_identifier(entry) if isinstance(entry, dict) else "?"
    if not isinstance(entry, dict):
        return [f"{label}: an entry must be an object"]
    problems = [f"{label}: missing field '{field}'" for field in REQUIRED_FIELDS if field not in entry]
    if problems:
        return problems
    if entry["kind"] not in CONTENT_KINDS:
        problems.append(f"{label}: kind '{entry['kind']}' is not one of {', '.join(CONTENT_KINDS)}")
    if not isinstance(entry["platforms"], list) or not entry["platforms"]:
        problems.append(f"{label}: platforms must be a non-empty list")
    evidence = entry["evidence"]
    if not isinstance(evidence, dict):
        problems.append(f"{label}: evidence must be an object")
        evidence = {}
    for statement in EVIDENCE_STATEMENTS:
        value = evidence.get(statement, {})
        answer = value.get("answer") if isinstance(value, dict) else None
        if answer not in EVIDENCE_ANSWERS:
            problems.append(f"{label}: evidence.{statement}.answer must be one of {', '.join(EVIDENCE_ANSWERS)}")
        elif answer != "unknown" and not str(value.get("basis", "")).strip():
            problems.append(f"{label}: evidence.{statement} says '{answer}' but gives no basis")
    release = entry["release"]
    if not isinstance(release, dict) or release.get("status") not in RELEASE_STATUSES:
        problems.append(f"{label}: release.status must be one of {', '.join(RELEASE_STATUSES)}")
    elif release["status"] != "unknown":
        if not str(release.get("basis", "")).strip():
            problems.append(f"{label}: release.status '{release['status']}' needs a basis")
        if release.get("scope") not in RELEASE_SCOPES:
            problems.append(f"{label}: release.scope must be one of {', '.join(RELEASE_SCOPES)}")
    quality = entry["quality"]
    if quality not in QUALITY_LEVELS:
        problems.append(f"{label}: quality must be one of {', '.join(QUALITY_LEVELS)}")
    answers = {statement: (evidence.get(statement) or {}).get("answer") for statement in EVIDENCE_STATEMENTS}
    if quality in ("data-verified", "runtime-verified") and answers["present_in_data"] != "yes":
        problems.append(f"{label}: quality '{quality}' requires present_in_data = yes")
    if quality == "runtime-verified" and answers["loaded_under_test"] != "yes":
        problems.append(f"{label}: quality 'runtime-verified' requires loaded_under_test = yes")
    if quality in ("data-verified", "runtime-verified") and not entry.get("builds"):
        problems.append(f"{label}: quality '{quality}' requires at least one identified build in 'builds'")
    for build in entry.get("builds", []):
        if not isinstance(build, dict) or not build.get("label") or not build.get("identity"):
            problems.append(f"{label}: every build needs a 'label' and an 'identity' (for example a SHA-256)")
    sources = entry["sources"]
    if not isinstance(sources, list) or not sources or not all(isinstance(url, str) and url.startswith("https://") for url in sources):
        problems.append(f"{label}: sources must be a non-empty list of https:// links")
    checked = str(entry["checked"])
    if not DATE_PATTERN.match(checked):
        problems.append(f"{label}: checked must be a YYYY-MM-DD date")
    else:
        try:
            datetime.date.fromisoformat(checked)
        except ValueError:
            problems.append(f"{label}: checked is not a real date")
    write_up = entry.get("write_up")
    if write_up and not (REPOSITORY_ROOT / write_up).is_file():
        problems.append(f"{label}: write_up '{write_up}' does not exist")
    return problems


def validate_entries(entries: list[dict]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        problems.extend(validate_entry(entry))
        identifier = entry_identifier(entry) if isinstance(entry, dict) else ""
        if identifier in seen:
            problems.append(f"{identifier}: duplicate entry (same game and item)")
        seen.add(identifier)
    return problems


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def search_entries(entries: list[dict], query: str = "", kind: str = "", quality: str = "") -> list[dict]:
    """Case-insensitive search over game, item, engine, platforms, summary and aliases."""
    words = _normalized(query).split()
    results = []
    for entry in entries:
        if kind and entry.get("kind") != kind:
            continue
        if quality and entry.get("quality") != quality:
            continue
        haystack = _normalized(" ".join([
            entry.get("game", ""), entry.get("item", ""), entry.get("engine", ""), entry.get("summary", ""),
            " ".join(entry.get("platforms", [])), " ".join(entry.get("internal_names", [])),
            " ".join(entry.get("match", {}).get("titles", [])),
        ]))
        if all(word in haystack for word in words):
            results.append(dict(entry, id=entry_identifier(entry)))
    return results


def _contains_words(text: str, phrase: str) -> bool:
    """Whole-word match on normalised text, so 'Quake' does not match 'LibreQuake'."""
    phrase = _normalized(phrase)
    return bool(phrase) and f" {phrase} " in f" {text} "


def match_build(entries: list[dict], build: dict) -> list[dict]:
    """Entries that document content for a scanned or discovered build.

    A build matches by full SHA-256, by product code (for example a cartridge
    serial) or by a known title. Title matches are candidates only: the exact
    build identity still has to be compared before following an entry.
    """
    title = _normalized(build.get("title", ""))
    label = _normalized(build.get("build_label", ""))
    hashes = {str(value).lower() for value in build.get("sha256", []) if value}
    matches = []
    for entry in entries:
        rules = entry.get("match", {})
        reason = ""
        if hashes & {value.lower() for value in rules.get("sha256", [])}:
            reason = "same SHA-256"
        elif any(code and _normalized(code) in label.split() for code in rules.get("codes", [])):
            reason = "same product code"
        elif any(_contains_words(title, alias) or _contains_words(label, alias)
                 for alias in rules.get("titles", []) + [entry.get("game", "")]):
            reason = "same title (compare the exact build before following this entry)"
        if reason:
            matches.append(dict(entry, id=entry_identifier(entry), match_reason=reason))
    return matches


# Folder builds are identified by the hashes of their larger files (archives,
# executables). The limits keep matching fast on big installs.
IDENTITY_FILE_LIMIT = 32
IDENTITY_MINIMUM_FILE_BYTES = 64 * 1024
IDENTITY_MAXIMUM_FILE_BYTES = 4 * 1024 * 1024 * 1024


def build_from_report(report: dict, maximum_file_bytes: int = IDENTITY_MAXIMUM_FILE_BYTES) -> dict:
    """Title, build label and SHA-256 values of a scanned build, for match_build."""
    from cutcontent.core.decoded_scenes import file_sha256
    source = Path(report.get("path", ""))
    candidates: list[Path] = []
    if source.is_file():
        candidates = [source] if source.stat().st_size <= maximum_file_bytes else []
    elif source.is_dir():
        for path in sorted(source.rglob("*")):
            if len(candidates) >= IDENTITY_FILE_LIMIT or len(path.relative_to(source).parts) > 2:
                continue
            if path.is_file() and not path.is_symlink() and IDENTITY_MINIMUM_FILE_BYTES <= path.stat().st_size <= maximum_file_bytes:
                candidates.append(path)
    hashes = []
    for path in candidates:
        try:
            hashes.append(file_sha256(path))
        except (OSError, ValueError):
            continue
    return {"title": report.get("title", ""), "build_label": report.get("build_label", ""), "sha256": hashes}


def _cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def render_markdown(entries: list[dict]) -> str:
    """Builds DIRECTORY.md. The output is deterministic so CI can compare it."""
    ordered = sorted(entries, key=lambda entry: (entry["game"].lower(), entry["item"].lower()))
    games = sorted({entry["game"] for entry in entries}, key=str.lower)
    lines = [
        "# Directory of documented hidden and cut content",
        "",
        "<!-- Generated from data/directory.json by `cutcontent directory build`. Do not edit by hand. -->",
        "",
        f"{len(entries)} entries for {len(games)} games. Every entry keeps four evidence statements, "
        "the release history and its quality level separate. Schema and rules: [data/SCHEMA.md](data/SCHEMA.md).",
        "",
        "Quality levels:",
        "",
    ]
    lines += [f"- **{level}**: {text}." for level, text in QUALITY_LEVELS.items()]
    lines += ["", "Evidence columns: **D** present in the data · **U** possibly unused · "
              "**T** loaded under test conditions · **N** reachable in normal play.", ""]
    lines.append("| Game | Content | Kind | Platform | D | U | T | N | Release | Quality | Checked |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for entry in ordered:
        evidence = entry["evidence"]
        content = f"`{entry['item']}`"
        if entry.get("write_up"):
            content += f" ([write-up]({entry['write_up']}))"
        cells = [entry["game"] + (f" ({entry['year']})" if entry.get("year") else ""), content, entry["kind"],
                 ", ".join(entry["platforms"])]
        cells += [evidence[statement]["answer"] for statement in EVIDENCE_STATEMENTS]
        release = entry["release"]
        cells += [release["status"] + (f" ({release['scope']})" if release.get("scope") else ""), f"**{entry['quality']}**", entry["checked"]]
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    lines += ["", "## Details", ""]
    for entry in ordered:
        lines += [f"### {entry['game']}: `{entry['item']}`", "", entry["summary"], ""]
        for statement, title in EVIDENCE_STATEMENTS.items():
            value = entry["evidence"][statement]
            basis = f" — {value['basis']}" if value.get("basis") else ""
            lines.append(f"- {title}: **{value['answer']}**{basis}")
        lines.append(f"- Release: **{RELEASE_STATUSES[entry['release']['status']]}**"
                     + (f", scope: {RELEASE_SCOPES[entry['release']['scope']]}" if entry["release"].get("scope") else "")
                     + (f" — {entry['release']['basis']}" if entry["release"].get("basis") else ""))
        for build in entry.get("builds", []):
            lines.append(f"- Checked build: {build['label']} (`{build['identity']}`)")
        if entry.get("notes"):
            lines.append(f"- Notes: {entry['notes']}")
        lines.append("- Sources: " + " · ".join(f"<{url}>" for url in entry["sources"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_page(check_only: bool = False) -> bool:
    """Writes DIRECTORY.md; returns True if it was already up to date."""
    entries = load_entries()
    problems = validate_entries(entries)
    if problems:
        raise ValueError("The directory has problems:\n  - " + "\n  - ".join(problems))
    expected = render_markdown(entries)
    current = DIRECTORY_PAGE.read_text(encoding="utf-8") if DIRECTORY_PAGE.is_file() else ""
    if current == expected:
        return True
    if not check_only:
        DIRECTORY_PAGE.write_text(expected, encoding="utf-8")
    return False
