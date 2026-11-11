#!/usr/bin/env python3
"""Open an actual registered game scene and exercise the question-led gallery.

Requires the user's scanned build, a source-bound registered scene, a recorded
source-backed release assessment, Playwright and Chromium. No fixtures, engine
mock or downloaded game is used. Captures and report stay in a new private folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(arguments) -> dict:
    from playwright.sync_api import sync_playwright
    from cutcontent.core.decoded_scenes import file_sha256
    from cutcontent.core.scan_report import load_report
    from cutcontent.web.server import make_server

    output = arguments.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = load_report(arguments.build)
    item = next(item for item in report["items"] if item["id"] == arguments.item)
    if not item.get("decoded_scene") or not item.get("release_history", {}).get("sources"):
        raise ValueError("Use a real registered scene with an actually researched release assessment.")
    source_files = [Path(path) for path in arguments.source_file]
    before = {str(path): file_sha256(path) for path in source_files}
    result = {"build_id": arguments.build, "item_id": arguments.item, "page_errors": [], "passed": False,
              "source_hashes": before, "source_scene": item["decoded_scene"], "release_history": item["release_history"]}
    server, state = make_server(18900)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            print("Starting a fresh browser context", flush=True)
            browser = playwright.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, permissions=["clipboard-read", "clipboard-write"])
                page = context.new_page()
                page.set_default_timeout(120000)
                page.on("pageerror", lambda error: result["page_errors"].append(str(error)))
                page.goto(f"http://127.0.0.1:{state.port}/", wait_until="domcontentloaded")
                print("Opening the actual finding card", flush=True)
                page.locator(f'.build[data-path={json.dumps(report["path"])}] button', has_text="Open").click()
                question = "Find a hidden test map, show it in the tool and research its release history on the web."
                page.fill("#investigation-question", question)
                page.click("#copy-task-codex")
                page.wait_for_function("() => document.body.dataset.lastTaskClient === 'codex'")
                copied = page.evaluate("() => navigator.clipboard.readText()")
                assert question in copied
                result["free_question_preserved_in_actual_clipboard"] = True
                (output / "actual-agent-task.txt").write_text(copied)
                page.select_option("#status-filter", "all")
                page.fill("#search", item["name"])
                page.locator(f'.card[data-item-id="{arguments.item}"]').click()
                page.wait_for_selector('#viewer-stage[data-ready="level"]', state="attached", timeout=180000)
                assert item["release_history"]["scope_label"] in page.inner_text("#viewer-details")
                assert page.locator("#viewer-details a").filter(has_text=item["release_history"]["sources"][0]).count()
                canvas = page.locator("#viewer-stage canvas")
                first = canvas.screenshot()
                (output / "real-map-before-orbit.png").write_bytes(first)
                bounds = canvas.bounding_box()
                page.mouse.move(bounds["x"] + bounds["width"] * .45, bounds["y"] + bounds["height"] * .55)
                page.mouse.down()
                page.mouse.move(bounds["x"] + bounds["width"] * .7, bounds["y"] + bounds["height"] * .4, steps=20)
                page.mouse.up()
                page.wait_for_timeout(500)
                last = canvas.screenshot()
                (output / "real-map-after-orbit.png").write_bytes(last)
                result["actual_orbit_changed_render"] = hashlib.sha256(first).digest() != hashlib.sha256(last).digest()
                assert result["actual_orbit_changed_render"]
                page.screenshot(path=str(output / "question-map-and-sources.jpg"), type="jpeg", quality=90)
                if arguments.play:
                    facts = page.inner_text("[data-observed-facts]")
                    expected_facts = "Included in the release · Direct launch tested · No regular access found"
                    assert facts == expected_facts, facts
                    from cutcontent.platforms.quake_engine import cached_game_data, resolve_game_directory, QuakeAdapter
                    data = cached_game_data(resolve_game_directory(Path(report["path"])))
                    level = QuakeAdapter._read_level(data, item["reference"]["path"])
                    spawn_entity = next(entity for entity in level.entities if entity.get("classname") == "info_player_start")
                    spawn = [float(value) for value in spawn_entity["origin"].split()]
                    page.click("#viewer-game")
                    print("Game button clicked; waiting for actual engine startup", flush=True)
                    frame = page.wait_for_selector("iframe.game-frame").content_frame()
                    frame.wait_for_selector('body[data-ready="game"], body[data-failed="true"]', state="attached", timeout=240000)
                    if frame.get_attribute("body", "data-failed") == "true":
                        raise AssertionError(frame.inner_text("#status") + "\n" + frame.inner_text("#output"))
                    first = frame.evaluate("() => window.cutcontentRuntimeState")
                    assert first["loaded"] and first["map"] == Path(item["name"]).stem and first["entities"] > 1
                    near_spawn = sum((first["position"][axis] - spawn[axis]) ** 2 for axis in (0, 1)) <= 64 ** 2 and abs(first["position"][2] - spawn[2]) <= 128
                    assert near_spawn, (spawn, first)
                    print(json.dumps({"source_spawn": spawn, "actual_initial": first, "near_spawn": near_spawn}), flush=True)
                    page.wait_for_timeout(500)
                    settled = frame.evaluate("() => window.cutcontentRuntimeState")
                    frame.locator("#canvas").focus()
                    page.keyboard.down("KeyW")
                    page.wait_for_timeout(1500)
                    page.keyboard.up("KeyW")
                    page.wait_for_timeout(500)
                    after = frame.evaluate("() => window.cutcontentRuntimeState")
                    horizontal_distance_squared = sum((after["position"][axis] - settled["position"][axis]) ** 2 for axis in (0, 1))
                    assert horizontal_distance_squared > 16 and after["server_time"] > settled["server_time"], (settled, after)
                    result["fresh_card_game_start"] = {"facts": facts, "source_spawn": spawn, "initial": first,
                                                       "settled_without_input": settled, "after_walking": after,
                                                       "near_source_spawn": near_spawn,
                                                       "horizontal_distance_squared": horizontal_distance_squared}
                    page.screenshot(path=str(output / "fresh-card-actual-game.jpg"), type="jpeg", quality=90)
                    (output / "runtime-observations.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                    print("Actual spawn and horizontal movement passed; closing the viewer", flush=True)
                page.click("#viewer-close")
                print("Viewer closed", flush=True)
                page.select_option("#status-filter", "unreleased")
                result["released_data_not_mislabelled_unreleased"] = page.locator(f'.card[data-item-id="{arguments.item}"]').count() == 0
                assert result["released_data_not_mislabelled_unreleased"]
            finally:
                print("Closing owned browser", flush=True)
                browser.close()
                print("Owned browser closed", flush=True)
        result["source_files_unchanged"] = before == {str(path): file_sha256(path) for path in source_files}
        result["passed"] = result["source_files_unchanged"] and not result["page_errors"]
    except Exception as error:
        result["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        print("Stopping owned test server", flush=True)
        server.shutdown()
        server.server_close()
        (output / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print("Test report saved", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True)
    parser.add_argument("--item", required=True)
    parser.add_argument("--source-file", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--play", action="store_true", help="from this exact card, start the actual engine and verify spawn plus horizontal movement")
    result = run(parser.parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
