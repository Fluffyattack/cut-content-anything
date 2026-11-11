#!/usr/bin/env python3
"""Verify real Qwasm gameplay through the gallery, then enable this exact build.

Requires Playwright/Chromium, a separately built engine, and local LibreQuake
data. Use --record-verification to enable the engine after a successful run.
Original game files are hashed before and after; reports use a temporary folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cutcontent.core.settings import data_directory, write_json_atomically
from cutcontent.platforms.browser_engines import ENGINE_FILES, engine_directory


def file_hashes(paths: list[Path]) -> dict[str, str]:
    results = {}
    for path in paths:
        with path.open("rb") as handle:
            checksum = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                checksum.update(chunk)
            results[path.name] = checksum.hexdigest()
    return results


def run(game: Path, engine: Path, screenshots: Path | None, record_verification: bool) -> dict:
    from playwright.sync_api import sync_playwright
    from cutcontent.core import service
    from cutcontent.web.server import make_server

    game, engine = game.expanduser().resolve(), engine.expanduser().resolve()
    engine_hashes = file_hashes([engine / name for name in ENGINE_FILES])
    game_paths = sorted(game.glob("*.pak"))
    if not game_paths:
        raise ValueError("Point --game at LibreQuake's id1 directory containing pak0.pak.")
    before = file_hashes(game_paths)
    results = {"engine": "Qwasm", "files": engine_hashes, "levels": [], "page_errors": []}
    saved_environment = {key: os.environ.get(key) for key in ("CUT_CONTENT_DATA_DIR", "CUT_CONTENT_ROM_DIR", "CUT_CONTENT_QWASM_DIR")}
    with tempfile.TemporaryDirectory(prefix="cut-content-game-acceptance-") as temporary:
        os.environ["CUT_CONTENT_DATA_DIR"] = str(Path(temporary) / "data")
        os.environ["CUT_CONTENT_ROM_DIR"] = str(game)
        os.environ["CUT_CONTENT_QWASM_DIR"] = str(engine)
        server = None
        try:
            report = service.scan_path(game)
            print(f"Scanned {report.title}: {len(report.items)} items", flush=True)
            server, state = make_server(18840)
            state.allow_unverified_engine = True  # exercise the build before authorising it
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{state.port}/"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.set_default_timeout(120_000)
                    page.on("pageerror", lambda error: results["page_errors"].append(str(error)))
                    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                    page.click("#refresh-library")
                    page.wait_for_selector(".game")
                    page.locator(".game button", has_text="Open").first.click()
                    print("Gallery opened", flush=True)
                    for level_name in ("lq_e0m1", "dev"):
                        if not any(item.name == f"maps/{level_name}.bsp" for item in report.items):
                            raise ValueError(f"The expected LibreQuake test level {level_name} is missing.")
                        page.select_option("#status-filter", "all")
                        page.fill("#search", f"maps/{level_name}.bsp")
                        page.locator(f'.card:has(.name:text-is("maps/{level_name}.bsp"))').click()
                        page.wait_for_selector('#viewer-stage[data-ready="level"]', state="attached", timeout=240_000)
                        if page.is_disabled("#viewer-game"):
                            raise AssertionError(page.get_attribute("#viewer-game", "title"))
                        started = time.monotonic()
                        print(f"Starting {level_name} in Qwasm", flush=True)
                        page.click("#viewer-game")
                        frame_element = page.wait_for_selector("iframe.game-frame")
                        frame = frame_element.content_frame()
                        frame.wait_for_selector('body[data-ready="game"], body[data-failed="true"]', state="attached", timeout=240_000)
                        if frame.get_attribute("body", "data-failed") == "true":
                            raise AssertionError(frame.inner_text("#status") + "\n" + frame.inner_text("#output"))
                        first = frame.evaluate("() => window.cutcontentRuntimeState")
                        assert first["loaded"] and first["map"] == level_name and first["entities"] > 1, first
                        canvas = frame.locator("#canvas")
                        canvas.focus()
                        page.keyboard.down("KeyW")
                        page.wait_for_timeout(2000)
                        page.keyboard.up("KeyW")
                        page.wait_for_timeout(500)
                        last = frame.evaluate("() => window.cutcontentRuntimeState")
                        moved = sum((a - b) ** 2 for a, b in zip(first["position"], last["position"])) > 1
                        assert moved and last["server_time"] > first["server_time"], (first, last)
                        entry = {"map": level_name, "before": first, "after": last, "player_moved": moved, "seconds": round(time.monotonic() - started, 2)}
                        results["levels"].append(entry)
                        if screenshots:
                            screenshots.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(screenshots / f"game-{level_name}.jpg"), type="jpeg", quality=88)
                        print(json.dumps(entry), flush=True)
                        page.click("#viewer-close")
                except Exception:
                    if screenshots and 'page' in locals() and not page.is_closed():
                        screenshots.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screenshots / "game-test-failure.jpg"), type="jpeg", quality=85)
                        print("Browser errors:", results["page_errors"], flush=True)
                        print(page.inner_text("body")[-6000:], flush=True)
                    raise
                finally:
                    browser.close()
        finally:
            if server:
                server.shutdown()
                server.server_close()
            for key, value in saved_environment.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    results["game_files_unchanged"] = before == file_hashes(game_paths)
    results["engine_files_unchanged"] = engine_hashes == file_hashes([engine / name for name in ENGINE_FILES])
    results["passed"] = len(results["levels"]) == 2 and results["game_files_unchanged"] and results["engine_files_unchanged"] and not results["page_errors"]
    if results["passed"] and record_verification:
        write_json_atomically(engine / "browser-verification.json", results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=data_directory() / "demo" / "librequake-v0.09-beta" / "id1")
    parser.add_argument("--engine", type=Path, default=engine_directory())
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--record-verification", action="store_true")
    arguments = parser.parse_args()
    result = run(arguments.game, arguments.engine, arguments.screenshots, arguments.record_verification)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
