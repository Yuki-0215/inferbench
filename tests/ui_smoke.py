"""Browser smoke test for a running InferBench instance.

Run with: .venv/bin/python tests/ui_smoke.py
"""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE_URL = os.getenv("INFERBENCH_TEST_URL", "http://127.0.0.1:8080").rstrip("/")


def main() -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(BASE_URL, wait_until="networkidle")
        page.get_by_text("InferBench", exact=True).wait_for()
        assert page.locator("#healthText").inner_text() == "本地在线"
        assert page.locator('[name="concurrency_levels"]').input_value() == "1, 2, 4, 8"
        assert page.locator('[name="repetitions"]').input_value() == "3"
        assert page.locator('[name="requests"]').input_value() == "128"
        assert page.locator('[name="max_tokens"]').input_value() == "128"

        page.route(
            "**/api/discover",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"chat_endpoint":"https://example.com/v1/chat/completions","models":[{"id":"detected-model","max_model_len":32768}]}',
            ),
        )
        page.locator('[name="endpoint"]').fill("https://example.com/v1/models")
        page.locator("#discoverBtn").click()
        assert page.locator('[name="endpoint"]').input_value() == "https://example.com/v1/chat/completions"
        assert page.locator('[name="model"]').input_value() == "detected-model"
        assert page.locator('[name="name"]').input_value() == "detected-model"
        assert "已填写模型与实验名称" in page.locator("#formNote").inner_text()
        page.unroute("**/api/discover")
        page.locator('[data-preset="mock"]').click()

        cancel_ids = []
        for repetition in range(1, 4):
            response = page.request.post(
                f"{BASE_URL}/api/runs",
                data={
                    "name": f"UI cancel smoke · R{repetition}",
                    "endpoint": f"{BASE_URL}/mock/v1/chat/completions",
                    "model": "demo-model",
                    "concurrency": 1,
                    "requests": 100,
                    "warmup_requests": 0,
                    "max_tokens": 128,
                    "suite_id": "ui-cancel-smoke",
                    "suite_name": "UI cancel smoke",
                    "repetition": repetition,
                    "repetitions": 3,
                },
            )
            assert response.ok
            cancel_ids.append(response.json()["run"]["id"])
        page.reload(wait_until="networkidle")
        page.locator("#cancelSuiteBtn").wait_for(state="visible")
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#cancelSuiteBtn").click()
        page.wait_for_function(
            """async ids => {
                const runs = await fetch('/api/runs').then(response => response.json());
                return ids.every(id => runs.find(item => item.run.id === id)?.run.status === 'cancelled');
            }""",
            arg=cancel_ids,
        )

        page.locator('[name="name"]').fill("UI matrix smoke")
        page.locator('[name="concurrency_levels"]').fill("1, 2")
        page.locator('[name="requests"]').fill("2")
        page.locator('[name="max_tokens"]').fill("2")
        page.locator('[name="repetitions"]').fill("3")
        page.locator("details.advanced summary").click()
        page.locator('[name="warmup_requests"]').fill("0")
        page.locator(".launch").click()
        page.locator("#historyList .history-item strong", has_text="UI matrix smoke · C1 · R1").first.wait_for()
        page.locator("#historyList .history-item strong", has_text="UI matrix smoke · C2 · R3").first.wait_for()
        page.wait_for_function("!document.querySelector('#compareBtn').disabled", timeout=30_000)
        assert page.locator("#metricGrid .metric").count() == 4
        assert page.locator('#tokenSpeedChart svg[aria-label="Token throughput over time"]').count() == 1
        assert "峰值" in page.locator("#tokenSpeedMeta").inner_text()
        page.locator("#tokenSpeedChart .token-point").first.click()
        tooltip = page.locator("#tokenSpeedChart .token-speed-tooltip")
        assert tooltip.is_visible()
        assert "tok/s" in tooltip.inner_text()
        assert "压测第" in tooltip.inner_text()
        page.locator("#tokenSpeedChart").click(position={"x": 20, "y": 20})
        assert not tooltip.is_visible()
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=ARTIFACTS / "dashboard.png", full_page=True)

        page.locator('[data-view="compare"]').click()
        page.locator("#compareBtn").click()
        page.locator(".ranking-card").first.wait_for()
        assert page.locator(".ranking-card").count() == 2
        assert "AVG×3" in page.locator(".ranking-card").first.inner_text()
        page.screenshot(path=ARTIFACTS / "comparison.png", full_page=True)

        mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        mobile.goto(BASE_URL, wait_until="networkidle")
        mobile.locator(".launch").scroll_into_view_if_needed()
        assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        mobile.evaluate("window.scrollTo(0, 0)")
        mobile.screenshot(path=ARTIFACTS / "mobile.png", full_page=True)
        mobile.close()
        browser.close()

    if console_errors:
        raise AssertionError(f"browser console errors: {console_errors}")
    print("UI smoke passed: desktop, compare, mobile, zero console errors")


if __name__ == "__main__":
    main()
