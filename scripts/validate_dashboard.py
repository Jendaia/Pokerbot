"""Browser smoke check. Start poker-dashboard first; Playwright is optional tooling.

Run: .venv/bin/python scripts/validate_dashboard.py
Install tooling: .venv/bin/python -m pip install playwright
                 .venv/bin/python -m playwright install chromium
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    artifacts = Path(__file__).resolve().parents[1] / "artifacts/dashboard"
    artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        page.wait_for_function("() => document.getElementById('connection-text').textContent !== 'Connecting'")
        assert page.locator(".category-row").count() == 9
        assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        page.screenshot(path=str(artifacts / "live-desktop.png"), full_page=True, animations="disabled")

        page.get_by_role("tab", name="What if").click()
        page.get_by_role("button", name="Load example").click()
        page.get_by_role("button", name="Calculate odds").click()
        page.wait_for_function("() => document.getElementById('win-value').textContent === '100.0%'")
        assert page.locator("#equity-value").inner_text() == "100.0%"
        assert page.locator("#current-hand").inner_text() == "Straight Flush"
        assert page.locator("#distribution-source").inner_text() == "What-if scenario"
        assert page.locator("#scenario-card-preview .playing-card").count() == 7
        assert "100.0%" in page.locator(".category-row").last.inner_text()
        page.screenshot(path=str(artifacts / "scenario-desktop.png"), full_page=True, animations="disabled")

        # Editing a hand clears old odds; duplicate cards produce a useful error.
        page.locator("#scenario-hero").fill("As As")
        assert not page.locator("#analysis-results").is_visible()
        page.get_by_role("button", name="Calculate odds").click()
        page.locator("#scenario-error").wait_for(state="visible")
        assert "Duplicate" in page.locator("#scenario-error").inner_text()

        page.locator("#scenario-hero").fill("2c 3d")
        page.locator("#scenario-board").fill("As Ks Qs Js Ts")
        page.get_by_role("button", name="Calculate odds").click()
        page.wait_for_function("() => document.getElementById('tie-value').textContent === '100.0%'")
        assert page.locator("#equity-value").inner_text() == "50.0%"
        page.get_by_role("button", name="Pause updates").click()
        assert page.locator("#connection-text").inner_text() == "Paused"
        assert "paused" in page.locator("#connection-notice").inner_text()
        if page.locator("#export-button").is_enabled():
            with page.expect_download() as download_info:
                page.get_by_role("button", name="Export round").click()
            destination = artifacts / "round-export.json"
            download_info.value.save_as(destination)
            exported = json.loads(destination.read_text())
            assert exported["displayed_analysis_source"] == "scenario"
            assert exported["scenario"]["result"]["equity"]["equity_percentage"] == 50
        page.get_by_role("button", name="Resume updates").click()

        # Verify a narrower phone viewport without horizontal scrolling.
        page.set_viewport_size({"width": 390, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        page.screenshot(path=str(artifacts / "scenario-mobile.png"), full_page=True, animations="disabled")
        page.get_by_role("tab", name="Live hand").click()
        assert not page.locator("#scenario-form").is_visible()
        assert not errors, errors
        browser.close()
    print("Browser checks passed: exact win/tie/equity, validation, mode switching, pause, export, and mobile layout.")


if __name__ == "__main__":
    main()
