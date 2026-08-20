"""Browser smoke test for the test-chart clipboard snapshot."""

import os

from playwright.sync_api import sync_playwright


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE_URL = os.getenv("INFERBENCH_TEST_URL", "http://127.0.0.1:8080").rstrip("/")
CREATE_RUN = os.getenv("INFERBENCH_CREATE_RUN", "1") != "0"


def main() -> None:
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            permissions=["clipboard-read", "clipboard-write"],
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(BASE_URL, wait_until="networkidle")
        if CREATE_RUN:
            response = page.request.post(
                f"{BASE_URL}/api/runs",
                data={
                    "name": "UI snapshot smoke",
                    "endpoint": f"{BASE_URL}/mock/v1/chat/completions",
                    "model": "demo-model",
                    "concurrency": 1,
                    "requests": 2,
                    "warmup_requests": 0,
                    "max_tokens": 2,
                },
            )
            assert response.ok
            run_id = response.json()["run"]["id"]
            page.wait_for_function(
                """async id => {
                    const run = await fetch(`/api/runs/${id}`).then(response => response.json());
                    return run.run.status === 'completed';
                }""",
                arg=run_id,
            )
        else:
            runs = page.request.get(f"{BASE_URL}/api/runs?limit=100").json()
            completed = next(item for item in runs if item["run"]["status"] == "completed")
            run_id = completed["run"]["id"]
        page.reload(wait_until="networkidle")
        page.locator(f'[data-run-id="{run_id}"]').click()
        button = page.locator("#copyScreenshotBtn")
        button.wait_for(state="visible")

        snapshot = page.evaluate(
            """async () => {
                const blob = await createTestSnapshot();
                return { type: blob.type, size: blob.size };
            }"""
        )
        assert snapshot["type"] == "image/png"
        assert snapshot["size"] > 10_000

        button.click()
        page.locator("#toast", has_text="测试图已复制到剪贴板").wait_for()
        clipboard_types = page.evaluate(
            "async () => (await navigator.clipboard.read()).flatMap(item => item.types)"
        )
        assert "image/png" in clipboard_types
        browser.close()

    if console_errors:
        raise AssertionError(f"browser console errors: {console_errors}")
    print(f"Snapshot smoke passed: {snapshot['size']} byte PNG copied")


if __name__ == "__main__":
    main()
