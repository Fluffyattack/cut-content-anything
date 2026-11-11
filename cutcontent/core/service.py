"""The shared core used by both the command line and the web interface.

Everything the user can do (find games, scan, preview, record evidence, build an
investigation task for an agent, check the setup) goes through these functions,
so the CLI and the GUI always behave the same.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from cutcontent import __version__
from cutcontent.core import folders as folder_rules
from cutcontent.core.content_items import EVIDENCE_LEVEL_TITLES, EVIDENCE_LEVELS
from cutcontent.core.scan_report import build_identifier, list_reports, load_report, save_report
from cutcontent.core.settings import data_directory, write_json_atomically
from cutcontent.platforms import adapter_by_identifier, all_adapters
from cutcontent.platforms.base import Detection, PreviewError, PreviewResult

DISCOVERY_DEPTH = 4
DISCOVERY_ENTRY_LIMIT = 20000
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------- discovery
def detect_path(path: Path) -> list[Detection]:
    for adapter in all_adapters():
        try:
            detections = adapter.detect(path)
        except (OSError, ValueError):
            continue
        if detections:
            return detections
    return []


def discover_builds(folder_list: list[folder_rules.AllowedFolder] | None = None) -> list[dict]:
    """Looks for games inside the allowed folders (shallow, read-only, bounded)."""
    folder_list = folder_rules.allowed_folders() if folder_list is None else folder_list
    found: dict[str, dict] = {}
    for folder in folder_list:
        if not folder.readable:
            continue
        visited = 0
        pending = [(folder.path, 0)]
        while pending and visited < DISCOVERY_ENTRY_LIMIT:
            directory, depth = pending.pop(0)
            detections = detect_path(directory)
            if detections:
                for detection in detections:
                    found.setdefault(build_identifier(detection.path), dict(detection.to_dict(), folder=str(folder.path)))
                continue
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name.lower())
            except OSError:
                continue
            for entry in entries:
                visited += 1
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir():
                    if depth + 1 <= DISCOVERY_DEPTH:
                        pending.append((Path(entry.path), depth + 1))
                elif entry.is_file():
                    for detection in detect_path(Path(entry.path)):
                        found.setdefault(build_identifier(detection.path), dict(detection.to_dict(), folder=str(folder.path)))
    reports = {summary["build_id"]: summary for summary in list_reports()}
    result = []
    for build_id, entry in found.items():
        entry["build_id"] = build_id
        entry["report"] = reports.get(build_id)
        result.append(entry)
    result.sort(key=lambda entry: (entry["title"].lower(), entry["build_label"].lower()))
    write_json_atomically(data_directory() / "library.json", result)
    return result


def group_builds_by_title(builds: list[dict]) -> list[dict]:
    """Groups builds (versions, regions, folders) of the same game under one title."""
    games: dict[str, dict] = {}
    for build in builds:
        key = f"{build['platform']}|{build['title'].strip().lower()}"
        game = games.setdefault(key, {"title": build["title"], "platform": build["platform"], "builds": []})
        game["builds"].append(build)
    return sorted(games.values(), key=lambda game: game["title"].lower())


# ---------------------------------------------------------------------- scan
def scan_path(path: Path | str, adapter_identifier: str | None = None):
    path = Path(os.path.realpath(os.fspath(path)))
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    if adapter_identifier:
        adapter = adapter_by_identifier(adapter_identifier)
    else:
        detections = detect_path(path)
        if detections:
            adapter = adapter_by_identifier(detections[0].adapter)
        elif path.is_dir():
            adapter = adapter_by_identifier("generic_folder")
        else:
            adapter = adapter_by_identifier("generic_artifact")
    report = adapter.scan(path)
    save_report(report)
    return report


def scan_build_in_allowed_folder(path: str):
    """Scan requested by the web interface: only inside allowed folders."""
    resolved = folder_rules.require_inside_allowed_folder(path)
    return scan_path(resolved)


# ------------------------------------------------------------------- preview
def find_item(report: dict, item_id: str) -> dict | None:
    for item in report.get("items", []):
        if item["id"] == item_id:
            return item
    return None


def preview_item(build_id: str, item_id: str, options: dict | None = None, enforce_allowed_folders: bool = True) -> PreviewResult:
    report = load_report(build_id)
    if report is None:
        raise PreviewError("This build has not been scanned yet.")
    if enforce_allowed_folders:
        folder_rules.require_inside_allowed_folder(report["path"])
    item = find_item(report, item_id)
    if item is None:
        raise PreviewError("The item is not part of the latest scan. Scan the build again.")
    if item.get("decoded_scene"):
        from cutcontent.core.decoded_scenes import decoded_scene_preview
        return PreviewResult("application/json", decoded_scene_preview(report, item))
    if not item["preview"]["supported"] and item["preview"]["viewer"] not in ("map3d",):
        raise PreviewError(item["preview"]["reason"] or "No preview is available for this item.")
    adapter = adapter_by_identifier(report["adapter"])
    path = Path(report["path"])
    if item["kind"] == "entity" and item["reference"].get("map"):
        level_item = next((entry for entry in report["items"] if entry["reference"] == {"type": "file", "path": item["reference"]["map"]}), None)
        if level_item is None:
            raise PreviewError("The level that contains this entity is not part of the scan.")
        item = level_item
    return adapter.preview(path, item, options or {})


# -------------------------------------------------------------- agent tasks
CLIENT_HINTS = {
    "claude": "You are running in Claude Code. The project skill is in .claude/skills/cut-content-anything/SKILL.md (invoke it as /cut-content-anything).",
    "codex": "You are running in Codex. The project skill is in .agents/skills/cut-content-anything/SKILL.md (mention it as $cut-content-anything).",
}


def investigation_task(build_id: str, client: str, item_ids: list[str] | None = None, question: str = "") -> str:
    """A ready-to-paste task for Claude Code or Codex, the same text for CLI and GUI."""
    if client not in CLIENT_HINTS:
        raise ValueError("client must be 'claude' or 'codex'")
    report = load_report(build_id)
    if report is None:
        raise ValueError("Scan the build first.")
    if not isinstance(question, str) or len(question) > 4000:
        raise ValueError("The investigation question must contain at most 4000 characters.")
    lines = [
        "Investigate possibly unused content with Cut Content Anything.",
        CLIENT_HINTS[client],
        f"Repository checkout: {REPOSITORY_ROOT}",
        "",
        f"Build: {report['title']} - {report['build_label']} ({report['platform']})",
        f"Path (read-only!): {report['path']}",
        f"Build ID: {build_id}",
        "",
        "User's investigation question: " + (question.strip() or "Find and verify promising unused or hidden content in this game."),
        "Treat this as a question to test; do not assume that the requested content exists.",
        "",
        "Steps:",
        "1. Run `bin/cutcontent doctor`, then `bin/cutcontent report " + build_id + " --findings`. Record the exact source file hash or a documented folder manifest for the build you test.",
        "2. Interpret the question into concepts, aliases and relevant content kinds. Search the whole relevant inventory and decoded contents, including items not labelled unused. Use `cutcontent search " + build_id + " --term CONCEPT --kind map --json` as appropriate; expand and inspect candidates rather than matching only their names.",
        "3. Identify actual container/engine formats from bytes. Existing adapters are readers, not the investigation boundary. For an unknown unencrypted format, use available source/docs and appropriate analysis tools, implement/test a reader or decoder, and keep following the question. Use REA for binary analysis when appropriate and available.",
        "4. Research the game, candidate names and release history on the web. Prefer official releases and developer statements, actually open the sources, compare versions and record URLs/date/what each source establishes. A failed search or an unused filename does not prove unreleased content.",
        "5. For this game, search all accessible data, shipped code and public sources for developer/debug menus, level or stage selection, sound tests and test rooms, even if the question is unrelated. Document each search method, its coverage, candidates, runtime tests and inaccessible areas; do not claim that a hidden function is absent from an incomplete search.",
        "6. Decode relevant content and show it in the appropriate gallery viewer. For a map, decode actual geometry/textures, register the source-bound shared scene with `cutcontent scene register`, and operate the map viewer. For other questions, use the actual image/text/audio/model view. Keep screenshots in the private case unless this is an expressly approved, rights-checked free demo.",
        "7. Start and operate the exact game build in a real engine or emulator for any completed investigation. Load every map reported as a finding in the actual game, including maps absent from normal play; a documented isolated test copy may provide a safe load route while the original stays read-only. Operate each claimed menu, check image/input/sound where available, and retain runtime screenshots. If a lawful local firmware or runtime component is missing, ask whether the owner can provide their own copy; do not download it. Keep a case open with the specific blocker when the game or a reported map cannot be loaded.",
        "8. Record observed runtime behavior with `bin/cutcontent evidence set " + build_id + " <item-id> loaded_under_test yes --basis \"what you did and saw\"`. Direct test loading does not establish normal-play access.",
        "9. Record source-backed publication history with `cutcontent release set`; keep it separate from hidden/unused status and normal-play reachability.",
        "10. Report every finding with its location and keep the four levels separate: "
        + "; ".join(EVIDENCE_LEVEL_TITLES[level] for level in EVIDENCE_LEVELS)
        + ". Name the method (static, runtime) and the limits of each check.",
        "Continue beyond inventory/search results: cross-check failures, resolve relevant decoder/runtime issues, and verify the requested outcome. Never count a filename, generated plan, mock or preview as proof of gameplay. Do not assert absence from partial coverage.",
        "",
        "Rules: work read-only on game files; no DRM, copy-protection, encryption or anti-cheat circumvention; "
        "no downloads of game data, leaks or BIOS files; do not copy original assets or private reports into public places.",
    ]
    if item_ids:
        lines += ["", "Focus on these items:"]
        for item_id in item_ids:
            item = find_item(report, item_id)
            if item:
                location = item["location"]
                where = f"{location.get('container', '')}: {location.get('internal_path', '')}".strip(": ")
                lines.append(f"- {item['id']} {item['kind']} '{item['name']}' at {where}")
                for reason in item["finding_reasons"][:3]:
                    lines.append(f"    finding: {reason}")
    return "\n".join(lines)


# -------------------------------------------------------------------- doctor
def doctor_checks() -> list[dict]:
    checks = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    version_ok = sys.version_info >= (3, 10)
    add("Python", "ok" if version_ok else "problem", f"{platform.python_version()} ({'3.10 or newer is required' if not version_ok else 'supported'})")

    directory = data_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        writable = os.access(directory, os.W_OK)
    except OSError:
        writable = False
    add("Data directory", "ok" if writable else "problem", f"{directory} ({'writable' if writable else 'not writable'}); game folders are never written to")

    environment_folders = folder_rules.environment_rom_folders()
    if environment_folders:
        for path in environment_folders:
            add(f"{folder_rules.ROM_FOLDER_ENVIRONMENT_VARIABLE}", "ok" if path.is_dir() else "problem", f"{path} ({'found' if path.is_dir() else 'does not exist or is not mounted'})")
    else:
        add(folder_rules.ROM_FOLDER_ENVIRONMENT_VARIABLE, "info", "not set")
    share_folders = folder_rules.detect_mounted_rom_share_folders()
    add(
        "Mounted SHARE partition ROM folders",
        "ok" if share_folders else "info",
        ", ".join(map(str, share_folders)) if share_folders else "none mounted (checked: " + ", ".join(folder_rules.MOUNTED_ROM_SHARE_PATTERNS) + ")",
    )
    for folder in folder_rules.allowed_folders():
        add("Allowed folder", "ok" if folder.readable else "warning", f"{folder.path} - {folder.source}{'' if folder.exists else ' (missing)'}")

    rea = shutil.which("rea")
    add("REA (optional binary analysis)", "ok" if rea else "info", rea or "not installed; agents can still use the static scan")
    emucap = shutil.which("emucap") or shutil.which("emucap-control")
    add("emucap (optional emulator tests)", "ok" if emucap else "info", emucap or "not installed; see https://github.com/mcpads/emucap")

    vendor = Path(__file__).resolve().parents[1] / "web" / "static" / "vendor" / "three"
    three_ok = (vendor / "three.module.js").is_file() and (vendor / "three.core.js").is_file()
    add("3D viewer library (three.js)", "ok" if three_ok else "problem", str(vendor) if three_ok else "three.js files are missing from cutcontent/web/static/vendor/three")

    from cutcontent.skill_sync import skill_copies_status

    for copy_path, in_sync in skill_copies_status():
        add("Skill copy", "ok" if in_sync else "warning", f"{copy_path} ({'in sync' if in_sync else 'out of date - run: cutcontent skill sync'})")

    from cutcontent.platforms.browser_engines import quake_browser_engine_status

    engine = quake_browser_engine_status()
    add("Game start in the browser (Quake)", "ok" if engine["available"] else "info", engine["reason"])
    from cutcontent.core.native_gameplay import native_player_status

    native = native_player_status()
    add("Local cartridge interpreter (optional)", "ok" if native["available"] else "info", native["reason"])
    add("Cut Content Anything", "ok", f"version {__version__}")
    return checks


def format_support_rows() -> list[dict]:
    rows = []
    for adapter in all_adapters():
        for support in adapter.format_support():
            rows.append(dict(support.to_dict(), adapter=adapter.identifier))
    return rows


def overview() -> dict:
    return {
        "version": __version__,
        "folders": [folder.to_dict() for folder in folder_rules.allowed_folders()],
        "reports": list_reports(),
    }
