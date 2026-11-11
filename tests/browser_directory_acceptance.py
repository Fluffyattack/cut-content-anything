"""Browser acceptance run: the gallery shows the shared directory's entries for a build.

Not part of the unit suite (it needs Playwright and a running gallery):

    bin/cutcontent gui --no-browser
    python3 tests/browser_directory_acceptance.py --url http://127.0.0.1:8749/ \
        --title LibreQuake --expect maps/dev.bsp --unmatched-title "Cut Content Anything demo" \
        --output /private/folder/directory-panel

The selected builds must already be scanned. Screenshots and the report go to
--output, which must be outside the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PANEL = "#directory-matches"
SETTLED = "() => { const panel = document.querySelector('#directory-matches');" \
          " return panel && !panel.hidden && /shared directory\\)/.test(panel.textContent) && !panel.textContent.includes('Checking'); }"


def open_build(page, title: str) -> str:
    game = page.locator("#game-list .game").filter(has=page.locator("h3", has_text=title)).first
    game.get_by_role("button", name="Open", exact=True).first.click()
    page.wait_for_selector("#build-view:not([hidden])", timeout=60_000)
    page.wait_for_function(f"() => document.querySelector('#build-title').textContent.includes({json.dumps(title)})", timeout=60_000)
    page.wait_for_function(SETTLED, timeout=180_000)
    return page.locator(PANEL).inner_text()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8749/")
    parser.add_argument("--title", required=True, help="library title of a build with directory entries")
    parser.add_argument("--expect", action="append", required=True, help="item that must be listed, repeatable")
    parser.add_argument("--unmatched-title", help="library title of a build without directory entries")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=False)

    errors: list[str] = []
    result: dict = {"passed": False}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(arguments.url)
        page.wait_for_selector("#game-list button", timeout=60_000)

        matched_text = open_build(page, arguments.title)
        page.locator(PANEL).scroll_into_view_if_needed()
        page.screenshot(path=str(output / "matched-build.png"))
        page.locator(PANEL).screenshot(path=str(output / "matched-panel.png"))
        result["matched_panel"] = matched_text
        result["expected_items_listed"] = {item: item in matched_text for item in arguments.expect}
        result["four_statements_listed"] = all(label in matched_text for label in (
            "Present in the data", "Possibly unused", "Loaded under test conditions", "Reachable in normal play"))
        result["source_links"] = page.locator(f"{PANEL} a[href^='https://']").count()

        if arguments.unmatched_title:
            unmatched_text = open_build(page, arguments.unmatched_title)
            page.locator(PANEL).screenshot(path=str(output / "unmatched-panel.png"))
            result["unmatched_panel"] = unmatched_text
            result["unmatched_says_nothing_documented"] = "Nobody has documented content" in unmatched_text
        browser.close()

    result["page_errors"] = errors
    result["passed"] = (all(result["expected_items_listed"].values()) and result["four_statements_listed"]
                        and result["source_links"] > 0 and not errors
                        and result.get("unmatched_says_nothing_documented", True))
    (output / "report.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
