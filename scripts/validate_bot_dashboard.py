"""Optional Playwright control checks using intercepted APIs, never live input."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    with urlopen(args.url + "/api/state") as response:
        payload = json.load(response)
    # Only this headless browser sees the fixture; all control requests are
    # intercepted so the real bot is never started/stopped or given a test move.
    bot = payload["bot"]
    bot["settings"].update(objective="profit", max_action_chips=None, stop_loss_chips=None, max_hands=None)
    bot.update(enabled=False, status="stopped", message="Controls fixture · autoplay stopped", generation=10,
               controls={"turn_token": "fixture-turn", "legal_actions": ["fold", "check", "call", "raise"],
                         "buttons": [{"action": "call", "title": "Call · 50"}], "raise_open": False,
                         "raise_min": None, "raise_max": None, "raise_value": None, "raise_steps": []})
    bot["decision"] = {"action": {"kind": "raise", "amount": 200}, "method": "river-cfr+",
                       "reason": "River CFR+ fixture", "equity": .72, "pot_odds": .25,
                       "samples": 200, "elapsed_seconds": .4,
                       "diagnostics": {"nash_conv_chips": .3, "limitations": "Restricted subgame only"},
                       "candidates": [{"action": "check", "amount": 0, "ev_chips": 25, "probability": .4, "standard_error": None},
                                      {"action": "raise", "amount": 200, "ev_chips": 27, "probability": .6, "standard_error": None}]}
    requests, errors = [], []
    artifacts = Path(__file__).resolve().parents[1] / "artifacts/bot"
    artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/state", lambda route: route.fulfill(json=deepcopy(payload)))
        def handle(route):
            action = route.request.url.rsplit("/", 1)[-1]
            data = route.request.post_data_json
            requests.append((action, data))
            bot["generation"] += 1
            if action == "start":
                bot.update(enabled=True, status="waiting", message="Controls fixture · autoplay active")
                bot["settings"].update({k: v for k, v in data.items() if k != "expected_generation"})
            elif action == "settings":
                bot["settings"].update({k: v for k, v in data.items() if k != "expected_generation"})
            elif action == "stop":
                bot.update(enabled=False, status="stopped", message="Controls fixture · autoplay stopped")
            elif action == "prepare":
                bot["controls"].update(raise_open=True, raise_min=100, raise_max=500, raise_value=100, raise_steps=[100, 150, 200, 500])
            elif action == "action":
                bot.update(enabled=False, status="stopped", message="Controls fixture · manual action queued")
            route.fulfill(json={"bot": deepcopy(bot)})
        page.route("**/api/bot/*", handle)
        page.goto(args.url)
        page.wait_for_function("() => document.getElementById('bot-message').textContent.includes('fixture')")
        assert "60.0%" in page.locator("#bot-candidates").inner_text()
        assert "72.0%" in page.locator("#bot-search-detail").inner_text()
        assert "Restricted river gap" in page.locator("#bot-search-detail").inner_text()
        page.locator(".bot-settings summary").click()
        assert "No hand limit" in page.locator("#bot-config-summary").inner_text()
        assert page.locator("#bot-max-action").input_value() == ""
        page.locator("#bot-policy").select_option("search")
        page.locator("#bot-max-action").fill("200")
        page.locator("#bot-start").click()
        page.wait_for_function("() => document.getElementById('bot-badge').textContent === 'Autoplay active'")
        assert requests[-1][0] == "start" and requests[-1][1]["max_action_chips"] == 200
        assert requests[-1][1]["expected_generation"] == 10
        assert requests[-1][1]["strategy"] == "search"
        assert requests[-1][1]["objective"] == "profit"
        assert requests[-1][1]["stop_loss_chips"] is None
        assert requests[-1][1]["max_hands"] is None
        page.locator("#bot-objective").select_option("conservative")
        page.locator("#bot-max-action").fill("")
        page.locator("#bot-apply").click()
        page.wait_for_function("() => document.getElementById('bot-config-summary').textContent.includes('Preserve stack')")
        assert requests[-1][0] == "settings"
        assert requests[-1][1]["max_action_chips"] is None
        assert page.locator("#bot-badge").inner_text() == "Autoplay active"
        assert "Full table stack available" in page.locator("#bot-config-summary").inner_text()
        page.locator("#pause-button").click()
        assert page.locator("#bot-stop").is_enabled()
        page.wait_for_timeout(700)
        assert page.locator('[data-poker-action="call"]').is_disabled()
        page.locator("#bot-stop").click()
        page.wait_for_function("() => document.getElementById('bot-badge').textContent === 'Stopped'")
        assert requests[-1][0] == "stop"
        page.locator("#pause-button").click()
        page.locator('[data-poker-action="call"]').click()
        page.wait_for_timeout(100)
        assert requests[-1] == ("action", {"action": "call", "amount": 0, "turn_token": "fixture-turn"})
        page.locator('[data-poker-action="raise"]').click()
        page.wait_for_function("() => document.getElementById('bot-raise-amount').disabled === false")
        assert page.locator("#bot-raise-amount").input_value() == "100"
        page.locator("#bot-raise-amount").fill("200")
        page.locator('[data-poker-action="raise"]').click()
        page.wait_for_timeout(100)
        assert requests[-1] == ("action", {"action": "raise", "amount": 200, "turn_token": "fixture-turn"})
        page.screenshot(path=str(artifacts / "controls-fixture-desktop.png"), full_page=True)
        for width in (390, 320):
            page.set_viewport_size({"width": width, "height": 844})
            assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), width
        page.screenshot(path=str(artifacts / "controls-fixture-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print("Bot UI checks passed: settings, Start/Stop, paused updates, manual call/raise, fresh token, and mobile layout.")


if __name__ == "__main__":
    main()
