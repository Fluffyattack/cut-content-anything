#!/usr/bin/env python3
"""Browser acceptance run for the web interface (needs Playwright with Chromium).

It plays through the acceptance test in a real (headless) browser:

1. open the interface, find the game, scan it;
2. open a level with "Explore in 3D", move with W and the mouse - the camera must move;
3. open a model, drag to turn it - the view angle must change;
4. open a texture (zoomable image) and a sound (player with waveform);
5. copy an investigation task for Claude Code and for Codex;
6. check that "Open in game" is disabled and explains why.

Data: the self-made demo game is always created. If ``CUT_CONTENT_LIBREQUAKE_ZIP``
points to the LibreQuake v0.09-beta lite.zip (checksum verified), LibreQuake is
used instead, which is what the screenshots in the README show.

Usage:
    python3 tests/browser_acceptance.py [--screenshots docs/screenshots]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(screenshot_directory: Path | None) -> int:
    from playwright.sync_api import sync_playwright

    temporary = tempfile.TemporaryDirectory(prefix="cut-content-acceptance-")
    os.environ["CUT_CONTENT_DATA_DIR"] = str(Path(temporary.name) / "data")
    os.environ.pop("CUT_CONTENT_ROM_DIR", None)

    from cutcontent.demo import create_demo_game, download_librequake
    from cutcontent.web.server import make_server

    create_demo_game()
    librequake_zip = os.environ.get("CUT_CONTENT_LIBREQUAKE_ZIP")
    if librequake_zip:
        download_librequake(Path(librequake_zip))
        game_title, level_name, model_name, texture_name, sound_name = "LibreQuake", "maps/lq_e0m1.bsp", "progs/soldier.mdl", "ecop1_1", "sound/player/slmbrn2.wav"
    else:
        game_title, level_name, model_name, texture_name, sound_name = "Cut Content Anything demo", "maps/start.bsp", "progs/cut_robot.mdl", "demo_old_sign", "sound/demo/unused_jingle.wav"

    server, state = make_server(18800)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{state.port}/"
    results: dict[str, object] = {}

    def shot(page, name: str) -> None:
        if screenshot_directory:
            screenshot_directory.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_directory / f"{name}.png"))

    def wait_ready(page, timeout=240_000) -> str:
        page.wait_for_selector("#viewer-stage[data-ready]", state="attached", timeout=timeout)
        return page.get_attribute("#viewer-stage", "data-ready")

    def release_pointer(page) -> None:
        page.evaluate("document.pointerLockElement && document.exitPointerLock()")
        page.wait_for_timeout(200)

    def open_card(page, kind_chip: str, name: str) -> None:
        page.select_option("#status-filter", "all")
        page.locator(".chip", has_text=kind_chip).first.click()
        page.fill("#search", name)
        page.locator(f'.card:has(.name:text-is("{name}"))').first.click()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        context = browser.new_context(viewport={"width": 1440, "height": 900}, bypass_csp=True)
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=url.rstrip("/"))
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        page.click("#refresh-library")
        page.wait_for_selector(f'.game:has(h3:text-is("{game_title}"))')
        page.locator(f'.game:has(h3:text-is("{game_title}"))').locator("button", has_text="Scan").first.click()
        page.wait_for_selector(".card", timeout=300_000)
        results["findings_shown"] = page.locator(".card").count()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)  # thumbnails decode, the toast disappears
        results["thumbnails_loaded"] = page.evaluate("[...document.querySelectorAll('.card img')].filter((image) => image.complete && image.naturalWidth > 0).length")
        shot(page, "gallery")

        open_card(page, "Levels", level_name)
        started = time.time()
        results["level_viewer"] = wait_ready(page)
        results["level_load_seconds"] = round(time.time() - started, 1)
        page.wait_for_timeout(1500)
        shot(page, "level-explore")
        before = page.get_attribute("#viewer-stage", "data-camera-position")
        canvas = page.locator("#viewer-stage canvas")
        canvas.click()
        page.keyboard.down("KeyW")
        page.wait_for_timeout(2000)
        page.keyboard.up("KeyW")
        release_pointer(page)
        box = canvas.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2 + 160, box["y"] + box["height"] / 2 - 30, steps=10)
        page.mouse.up()
        release_pointer(page)
        page.wait_for_timeout(600)
        after = page.get_attribute("#viewer-stage", "data-camera-position")
        results["level_camera_moved"] = before != after
        results["level_camera"] = f"{before} -> {after}"
        # Walk mode: back to the start, switch walking on, walk forward.
        page.click('[data-option="reset"]')
        page.check('[data-option="walk"]')
        walk_start = page.get_attribute("#viewer-stage", "data-camera-position")
        canvas.focus()
        page.keyboard.down("KeyW")
        page.wait_for_timeout(3000)
        page.keyboard.up("KeyW")
        page.wait_for_timeout(500)
        walk_end = page.get_attribute("#viewer-stage", "data-camera-position")
        results["walk_mode"] = page.get_attribute("#viewer-stage", "data-walking") == "true"
        results["walk_camera"] = f"{walk_start} -> {walk_end}"
        start_x, end_x = float(walk_start.split()[0]), float(walk_end.split()[0])
        results["walk_moved"] = walk_start != walk_end
        if not librequake_zip:
            # the demo's pillar spans x -32..32; with the player's half width of 16 the walk must stop near x = -48
            results["walk_blocked_by_pillar"] = start_x < end_x <= -47
        shot(page, "level-walk")
        results["game_button_disabled"] = page.is_disabled("#viewer-game")
        results["game_button_reason"] = page.get_attribute("#viewer-game", "title")
        shot(page, "level-moved")
        page.click("#viewer-close")

        open_card(page, "Models", model_name)
        results["model_viewer"] = wait_ready(page)
        page.wait_for_timeout(1000)
        azimuth_before = page.get_attribute("#viewer-stage", "data-camera-azimuth")
        box = page.locator("#viewer-stage canvas").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2 + 220, box["y"] + box["height"] / 2 + 40, steps=12)
        page.mouse.up()
        page.wait_for_timeout(1200)
        azimuth_after = page.get_attribute("#viewer-stage", "data-camera-azimuth")
        results["model_turned"] = azimuth_before != azimuth_after
        results["model_animation_frame"] = page.get_attribute("#viewer-stage", "data-current-frame")
        shot(page, "model-viewer")
        page.click("#viewer-close")

        open_card(page, "Textures", texture_name)
        results["texture_viewer"] = wait_ready(page)
        shot(page, "texture-viewer")
        page.click("#viewer-close")

        open_card(page, "Sounds", sound_name)
        results["sound_viewer"] = wait_ready(page)
        shot(page, "sound-viewer")
        page.click("#viewer-task-claude")
        page.wait_for_timeout(500)
        claude_task = page.evaluate("navigator.clipboard.readText()")
        page.click("#viewer-task-codex")
        page.wait_for_timeout(500)
        codex_task = page.evaluate("navigator.clipboard.readText()")
        results["task_claude_copied"] = ".claude/skills/cut-content-anything" in claude_task and sound_name in claude_task
        results["task_codex_copied"] = ".agents/skills/cut-content-anything" in codex_task and sound_name in codex_task
        page.click("#viewer-close")
        results["page_errors"] = errors
        browser.close()

    server.shutdown()
    temporary.cleanup()
    checks = ["level_camera_moved", "walk_mode", "walk_moved", "model_turned", "game_button_disabled", "task_claude_copied", "task_codex_copied"]
    if not librequake_zip:
        checks.append("walk_blocked_by_pillar")
    passed = all(results.get(check) for check in checks) and results["level_viewer"] == "level" and results["model_viewer"] == "model" and not results["page_errors"]
    results["passed"] = passed
    print(json.dumps(results, indent=1, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--screenshots", type=Path, help="folder for screenshots")
    arguments = parser.parse_args()
    sys.exit(run(arguments.screenshots))
