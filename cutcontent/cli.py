"""Command line of Cut Content Anything.

    cutcontent doctor                     check the setup (folders, optional tools, skill copies)
    cutcontent scan <path>                scan a game, ROM or disc image and save a report
    cutcontent report <build-id>          show a saved report (add --findings for findings only)
    cutcontent gui                        start the local web interface on 127.0.0.1
    cutcontent list                       list games found in the allowed folders
    cutcontent folders list|add|remove    manage the folders the web interface may read
    cutcontent demo create                build the self-made demo game (no third-party data)
    cutcontent demo librequake            download the free LibreQuake data (BSD-3-Clause art)
    cutcontent evidence set ...           record a runtime observation for one item
    cutcontent task <build-id>            print an investigation task for Claude Code or Codex
    cutcontent formats                    show what each format adapter supports and how it was tested
    cutcontent directory search|match ... search the shared directory or match a scanned build against it
    cutcontent directory validate|build   check data/directory.json and regenerate DIRECTORY.md
    cutcontent mcp                        run the MCP server for coding agents (standard input/output)
    cutcontent skill sync                 copy the skills in skills/ to the Claude Code and Codex skill folders
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from cutcontent import __version__
from cutcontent.core.content_items import EVIDENCE_LEVEL_TITLES, EVIDENCE_LEVELS, METHODS, STATUS_TEXT

STATUS_SYMBOLS = {"ok": "OK  ", "info": "info", "warning": "WARN", "problem": "FAIL"}


def print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1))


def summarise_report(report: dict, findings_only: bool, limit: int) -> None:
    statistics = report["statistics"]
    print(f"{report['title']} - {report['build_label']}")
    print(f"  platform: {report['platform']} | format: {report['format_name']} | adapter: {report['adapter']}")
    print(f"  path:     {report['path']}")
    print(f"  build id: {report['build_id']} | scanned {report['scanned_at']}")
    print(f"  {statistics['items']} items, {statistics['findings']} findings")
    kinds = ", ".join(f"{kind} {count}" for kind, count in sorted(statistics["items_by_kind"].items()))
    print(f"  items by kind: {kinds}")
    items = [item for item in report["items"] if item["is_finding"]] if findings_only else report["items"]
    if items:
        print()
        print("Findings:" if findings_only else "Items:")
    for item in items[:limit]:
        evidence = item["evidence"]
        levels = " | ".join(f"{EVIDENCE_LEVEL_TITLES[level]}: {STATUS_TEXT.get(evidence[level]['status'], evidence[level]['status'])}" for level in EVIDENCE_LEVELS)
        location = item["location"]
        where = f"{location.get('container', '')} {location.get('internal_path', '')}".strip()
        print(f"- [{item['id']}] {item['kind']}: {item['name']}")
        print(f"    where: {where}")
        print(f"    {levels}")
        for reason in item["finding_reasons"][:3]:
            print(f"    finding: {reason}")
    if len(items) > limit:
        print(f"... {len(items) - limit} more (use --limit or --json)")
    if report["limits"] or report["warnings"]:
        print()
        print("Limits of this scan:")
        for text in report["limits"] + report["warnings"]:
            print(f"  * {text}")
    game_launch = report.get("game_launch") or {}
    if game_launch.get("reason"):
        print(f"\nGame start: {game_launch['reason']}")


def command_doctor(arguments) -> int:
    from cutcontent.core.service import doctor_checks

    checks = doctor_checks()
    if arguments.json:
        print_json(checks)
    else:
        print(f"Cut Content Anything {__version__} - setup check")
        for check in checks:
            print(f"[{STATUS_SYMBOLS.get(check['status'], check['status'])}] {check['check']}: {check['detail']}")
    return 1 if any(check["status"] == "problem" for check in checks) else 0


def command_scan(arguments) -> int:
    from cutcontent.core.scan_report import load_report
    from cutcontent.core.service import scan_path

    report = scan_path(Path(arguments.path).expanduser(), arguments.adapter)
    saved = load_report(report.build_id)
    if arguments.json:
        print_json(saved)
    else:
        summarise_report(saved, findings_only=True, limit=arguments.limit)
        print(f"\nSaved report {report.build_id}. Open it in the web interface with: cutcontent gui")
    return 0


def command_report(arguments) -> int:
    from cutcontent.core.scan_report import list_reports, load_report

    if not arguments.build_id:
        for summary in list_reports():
            statistics = summary.get("statistics") or {}
            print(f"{summary['build_id']}  {summary['title']} - {summary['build_label']}  ({statistics.get('findings', 0)} findings, {summary['path']})")
        return 0
    report = load_report(arguments.build_id)
    if report is None:
        print(f"No report with id {arguments.build_id}. Run 'cutcontent report' to list reports.", file=sys.stderr)
        return 2
    if arguments.json:
        print_json(report)
    else:
        summarise_report(report, arguments.findings, arguments.limit)
    return 0


def command_gui(arguments) -> int:
    from cutcontent.web.server import make_server

    server, state = make_server(arguments.port)
    address = f"http://127.0.0.1:{state.port}/"
    print(f"Cut Content Anything is running at {address}", flush=True)
    print("Only this computer can reach it. Press Ctrl+C to stop.", flush=True)
    if not arguments.no_browser and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or sys.platform in ("win32", "darwin")):
        import webbrowser

        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


def command_list(arguments) -> int:
    from cutcontent.core.service import discover_builds

    builds = discover_builds()
    if arguments.json:
        print_json(builds)
        return 0
    if not builds:
        print("No games found in the allowed folders. See 'cutcontent folders list' and 'cutcontent demo create'.")
    for build in builds:
        scanned = "scanned" if build.get("report") else "not scanned"
        print(f"{build['build_id']}  {build['title']} - {build['build_label']} [{build['platform']}, {scanned}]\n    {build['path']}")
    return 0


def command_folders(arguments) -> int:
    from cutcontent.core import folders

    if arguments.action == "add":
        print(f"Allowed: {folders.add_configured_folder(Path(arguments.path))}")
    elif arguments.action == "remove":
        print("Removed." if folders.remove_configured_folder(Path(arguments.path)) else "That folder was not in the list.")
    else:
        for folder in folders.allowed_folders():
            state = "ok" if folder.readable else ("not readable" if folder.exists else "missing")
            print(f"{folder.path}  [{folder.source}; {state}]")
    return 0


def command_demo(arguments) -> int:
    from cutcontent.demo import create_demo_game, download_librequake

    if arguments.action == "create":
        path = create_demo_game()
        print(f"Created the self-made demo game in {path}")
    else:
        path = download_librequake(Path(arguments.from_zip).expanduser() if arguments.from_zip else None)
        print(f"LibreQuake data is ready in {path}")
    print("It is inside the demo folder, which the web interface may read. Press 'Refresh library' in the GUI.")
    return 0


def command_evidence(arguments) -> int:
    from cutcontent.core.scan_report import load_report, record_evidence
    from cutcontent.core.service import find_item

    report = load_report(arguments.build_id)
    if report is None or find_item(report, arguments.item_id) is None:
        print("Unknown build id or item id. See 'cutcontent report <build-id>'.", file=sys.stderr)
        return 2
    entry = record_evidence(arguments.build_id, arguments.item_id, arguments.level, arguments.status, arguments.basis, arguments.method, arguments.access_route)
    print(f"Recorded {EVIDENCE_LEVEL_TITLES[arguments.level]} = {STATUS_TEXT[arguments.status]} for {arguments.item_id} ({entry['recorded_at']}).")
    return 0


def command_task(arguments) -> int:
    from cutcontent.core.service import investigation_task

    print(investigation_task(arguments.build_id, arguments.client, arguments.item or [], arguments.question))
    return 0


def command_search(arguments) -> int:
    from cutcontent.core.content_search import search_report
    from cutcontent.core.scan_report import load_report
    report = load_report(arguments.build_id)
    if report is None:
        raise ValueError("Scan the game first.")
    result = search_report(report, arguments.term or [], arguments.kind or [], not arguments.metadata_only, arguments.limit)
    if arguments.json:
        print_json(result)
    else:
        print(f"{result['candidate_count']} candidates; {result['coverage']['inventory_items_checked']} inventory entries checked.")
        for item in result["candidates"]:
            print(f"- [{item['item_id']}] {item['kind']}: {item['name']}")
            for match in item["matches"][:4]:
                print(f"    {match['field']}: {match.get('excerpt', match.get('value', ''))}")
        print(result["coverage"]["meaning"])
    return 0


def command_investigate(arguments) -> int:
    from cutcontent.core.content_search import create_investigation, normalise_search_text
    from cutcontent.core.service import discover_builds, scan_path
    target = Path(arguments.game).expanduser()
    if not target.exists():
        query = normalise_search_text(arguments.game)
        matches = [build for build in discover_builds()
                   if query in normalise_search_text(build["title"]) or query in normalise_search_text(Path(build["path"]).stem)]
        if len(matches) != 1:
            choices = "\n".join(f"- {build['title']}: {build['path']}" for build in matches[:10])
            raise ValueError(f"Found {len(matches)} matching local builds. Select the intended game path.\n{choices}")
        target = Path(matches[0]["path"])
    report = scan_path(target)
    result = create_investigation(report.build_id, arguments.question, arguments.term or [], arguments.kind or [])
    if arguments.json:
        print_json(result)
    else:
        case = result["investigation"]
        print(f"Investigation {case['id']}: {case['question']}")
        print(f"Build {case['build_id']}; {result['search']['candidate_count']} initial candidates.")
        print(case["next_work"])
    return 0


def command_scene(arguments) -> int:
    from cutcontent.core.decoded_scenes import export_existing_scene, register_decoded_scene
    if arguments.scene_action == "export":
        result = export_existing_scene(arguments.build_id, arguments.item_id, Path(arguments.package),
                                       [Path(path) for path in arguments.source_file])
    else:
        result = register_decoded_scene(arguments.build_id, arguments.item_id, Path(arguments.package))
    print_json(result)
    return 0


def command_release(arguments) -> int:
    from cutcontent.core.release_history import record_release_history
    print_json(record_release_history(arguments.build_id, arguments.item_id, arguments.status,
                                      arguments.basis, arguments.source or [], arguments.scope))
    return 0


def command_formats(arguments) -> int:
    from cutcontent.core.service import format_support_rows

    rows = format_support_rows()
    if arguments.json:
        print_json(rows)
    elif arguments.markdown:
        print(format_support_markdown(rows))
    else:
        for row in rows:
            print(f"{row['platform']}: {row['format_name']} ({row['extensions']}) - {row['level']}")
            print(f"    tested with: {row['tested_with']}")
    return 0


def format_support_markdown(rows: list[dict]) -> str:
    from cutcontent.platforms.base import SUPPORT_LEVELS

    lines = [
        "| Platform | Format | Support | Reads | Unused-content analysis | Preview in the GUI | Not supported / limits | Tested with |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        cells = [row["platform"], f"{row['format_name']} ({row['extensions']})", f"**{row['level']}**", row["reads"], row["analysis"], row["previews"], row["not_supported"], row["tested_with"]]
        lines.append("| " + " | ".join(cell.replace("|", "/").replace("\n", " ") for cell in cells) + " |")
    lines += ["", "Support levels:", ""] + [f"- **{level}**: {text}" for level, text in SUPPORT_LEVELS.items()]
    return "\n".join(lines)


def command_skill(arguments) -> int:
    from cutcontent.skill_sync import install_user_skills, skill_copies_status, sync_skill_copies

    if arguments.action == "install":
        installed = install_user_skills()
        print("Installed complete shared skill: " + ", ".join(map(str, installed)))
        return 0

    if arguments.check:
        status = skill_copies_status()
        for path, in_sync in status:
            print(f"{'in sync ' if in_sync else 'OUTDATED'}  {path}")
        return 0 if status and all(in_sync for _, in_sync in status) else 1
    changed = sync_skill_copies()
    print("Updated: " + ", ".join(map(str, changed)) if changed else "All skill copies are already in sync.")
    return 0


def command_directory(arguments) -> int:
    from cutcontent import directory
    entries = directory.load_entries()
    if arguments.action in ("build", "check"):
        up_to_date = directory.build_page(check_only=arguments.action == "check")
        if arguments.action == "check":
            print("DIRECTORY.md is up to date." if up_to_date else "DIRECTORY.md is out of date - run: cutcontent directory build")
            return 0 if up_to_date else 1
        print("DIRECTORY.md was already up to date." if up_to_date else f"Wrote {directory.DIRECTORY_PAGE.name} with {len(entries)} entries.")
        return 0
    if arguments.action == "validate":
        problems = directory.validate_entries(entries)
        for problem in problems:
            print(f"- {problem}")
        print(f"{len(entries)} entries checked, {len(problems)} problems.")
        return 1 if problems else 0
    if arguments.action == "search":
        results = directory.search_entries(entries, " ".join(arguments.words), arguments.kind or "", arguments.quality or "")
    else:
        from cutcontent.core import folders
        from cutcontent.core.scan_report import load_report
        if not arguments.words:
            raise ValueError("directory match needs a build id (see: cutcontent list)")
        report = load_report(arguments.words[0])
        if report is None:
            raise ValueError("Scan the game first.")
        folders.require_inside_allowed_folder(report["path"])
        results = directory.match_build(entries, directory.build_from_report(report))
    if arguments.json:
        print_json(results)
        return 0
    if not results:
        print("No directory entries found. A missing entry only means nobody has documented it here yet.")
    for entry in results:
        reason = f" [{entry['match_reason']}]" if entry.get("match_reason") else ""
        print(f"- {entry['game']}: {entry['item']} ({entry['kind']}, {entry['quality']}){reason}")
        print(f"    {entry['summary']}")
    return 0


def command_mcp(arguments) -> int:
    from cutcontent.mcp_server import serve
    return serve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cutcontent", description="Find and preview possibly unused content in game data you legally own.")
    parser.add_argument("--version", action="version", version=f"cutcontent {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="check the setup")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=command_doctor)

    scan = commands.add_parser("scan", help="scan a game folder, ROM or disc image (read-only)")
    scan.add_argument("path")
    scan.add_argument("--adapter", help="force an adapter (see 'cutcontent formats')")
    scan.add_argument("--json", action="store_true", help="print the whole report as JSON")
    scan.add_argument("--limit", type=int, default=40, help="how many findings to print")
    scan.set_defaults(handler=command_scan)

    report = commands.add_parser("report", help="show saved reports")
    report.add_argument("build_id", nargs="?")
    report.add_argument("--findings", action="store_true", help="only findings")
    report.add_argument("--json", action="store_true")
    report.add_argument("--limit", type=int, default=60)
    report.set_defaults(handler=command_report)

    gui = commands.add_parser("gui", help="start the local web interface on 127.0.0.1")
    gui.add_argument("--port", type=int, default=8749, help="first port to try (the next free one is used if it is busy)")
    gui.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    gui.set_defaults(handler=command_gui)

    listing = commands.add_parser("list", help="list games found in the allowed folders")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(handler=command_list)

    folders = commands.add_parser("folders", help="folders the web interface may read")
    folders.add_argument("action", choices=["list", "add", "remove"], nargs="?", default="list")
    folders.add_argument("path", nargs="?")
    folders.set_defaults(handler=command_folders)

    demo = commands.add_parser("demo", help="create or download freely licensed demo data")
    demo.add_argument("action", choices=["create", "librequake"])
    demo.add_argument("--from-zip", help="use an already downloaded LibreQuake lite.zip (the checksum is still verified)")
    demo.set_defaults(handler=command_demo)

    evidence = commands.add_parser("evidence", help="record an observation for one item")
    evidence_commands = evidence.add_subparsers(dest="evidence_action", required=True)
    evidence_set = evidence_commands.add_parser("set", help="set one evidence level of an item")
    evidence_set.add_argument("build_id")
    evidence_set.add_argument("item_id")
    evidence_set.add_argument("level", choices=EVIDENCE_LEVELS)
    evidence_set.add_argument("status", choices=list(STATUS_TEXT))
    evidence_set.add_argument("--basis", required=True, help="what was done and what was observed")
    evidence_set.add_argument("--method", choices=list(METHODS), default="runtime")
    evidence_set.add_argument("--access-route", choices=["direct_start", "debug_menu", "normal_play"], help="actual route used in the runtime test")
    evidence_set.set_defaults(handler=command_evidence)

    task = commands.add_parser("task", help="print an investigation task for Claude Code or Codex")
    task.add_argument("build_id")
    task.add_argument("--client", choices=["claude", "codex"], default="claude")
    task.add_argument("--item", action="append", help="focus on an item id (repeatable)")
    task.add_argument("--question", default="", help="the user's free investigation question")
    task.set_defaults(handler=command_task)

    search = commands.add_parser("search", help="retrieve candidates across inventory, metadata and actual decoded text")
    search.add_argument("build_id")
    search.add_argument("--term", action="append", help="concept, alias or text to look for; repeatable")
    search.add_argument("--kind", action="append", help="also retrieve this content kind, such as map, model or sound")
    search.add_argument("--metadata-only", action="store_true")
    search.add_argument("--limit", type=int, default=100)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=command_search)

    investigate = commands.add_parser("investigate", help="start a question-led investigation of a local game")
    investigate.add_argument("game", help="local path, or an unambiguous title from the allowed library")
    investigate.add_argument("--question", required=True)
    investigate.add_argument("--term", action="append")
    investigate.add_argument("--kind", action="append")
    investigate.add_argument("--json", action="store_true")
    investigate.set_defaults(handler=command_investigate)

    scene = commands.add_parser("scene", help="show source-bound exports from any decoder in the shared map viewer")
    scene_commands = scene.add_subparsers(dest="scene_action", required=True)
    for action in ("export", "register"):
        scene_action = scene_commands.add_parser(action)
        scene_action.add_argument("build_id")
        scene_action.add_argument("item_id")
        scene_action.add_argument("package", help="new private output for export; existing package for register")
        if action == "export":
            scene_action.add_argument("--source-file", action="append", required=True, help="original game input actually read by the decoder")
        scene_action.set_defaults(handler=command_scene)

    from cutcontent.core.release_history import RELEASE_LABELS, RELEASE_SCOPES
    release = commands.add_parser("release", help="record web/source-backed publication history for a finding")
    release_commands = release.add_subparsers(dest="release_action", required=True)
    release_set = release_commands.add_parser("set")
    release_set.add_argument("build_id")
    release_set.add_argument("item_id")
    release_set.add_argument("status", choices=RELEASE_LABELS)
    release_set.add_argument("--basis", required=True)
    release_set.add_argument("--source", action="append", help="actual checked source-page URL, repeatable")
    release_set.add_argument("--scope", choices=RELEASE_SCOPES, default="playable_release")
    release_set.set_defaults(handler=command_release)

    formats = commands.add_parser("formats", help="what is supported and how it was tested")
    formats.add_argument("--json", action="store_true")
    formats.add_argument("--markdown", action="store_true")
    formats.set_defaults(handler=command_formats)

    directory_parser = commands.add_parser("directory", help="the shared directory of documented hidden and cut content")
    directory_parser.add_argument("action", choices=["search", "match", "validate", "build", "check"],
                                  help="search words, match a scanned build id, validate the data, build or check DIRECTORY.md")
    directory_parser.add_argument("words", nargs="*", help="search words, or the build id for 'match'")
    directory_parser.add_argument("--kind", help="only entries of this content kind")
    directory_parser.add_argument("--quality", help="only entries with this quality level")
    directory_parser.add_argument("--json", action="store_true")
    directory_parser.set_defaults(handler=command_directory)

    mcp = commands.add_parser("mcp", help="run the Model Context Protocol server for coding agents on standard input/output")
    mcp.set_defaults(handler=command_mcp)

    skill = commands.add_parser("skill", help="keep the agent skill copies in sync")
    skill.add_argument("action", choices=["sync", "install"])
    skill.add_argument("--check", action="store_true", help="only check, do not write")
    skill.set_defaults(handler=command_skill)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "folders" and arguments.action in ("add", "remove") and not arguments.path:
        parser.error("folders add/remove needs a path")
    try:
        return arguments.handler(arguments)
    except (FileNotFoundError, ValueError, PermissionError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
