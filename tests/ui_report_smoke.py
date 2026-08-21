"""Browser smoke test for automatic illustrated performance reports."""

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
        context = browser.new_context(
            viewport={"width": 1600, "height": 1100},
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = context.new_page()
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(BASE_URL, wait_until="networkidle")
        suite_id = "ui-report-smoke"
        for concurrency in (1, 2):
            for repetition in range(1, 4):
                response = page.request.post(
                    f"{BASE_URL}/api/runs",
                    data={
                        "name": f"UI report smoke · C{concurrency} · R{repetition}",
                        "endpoint": f"{BASE_URL}/mock/v1/chat/completions",
                        "model": "demo-model",
                        "concurrency": concurrency,
                        "requests": 2,
                        "warmup_requests": 0,
                        "max_tokens": 4,
                        "suite_id": suite_id,
                        "suite_name": "UI report smoke",
                        "suite_total_runs": 6,
                        "repetition": repetition,
                        "repetitions": 3,
                    },
                )
                assert response.ok

        page.wait_for_function(
            """async suiteId => {
                const reports = await fetch('/api/reports').then(response => response.json());
                return reports.some(report => report.suite_id === suiteId);
            }""",
            arg=suite_id,
            timeout=30_000,
        )
        page.reload(wait_until="networkidle")
        page.locator('[data-view="report"]').click()
        page.locator("#reportCapture .report-cover").wait_for()
        assert page.locator("#reportCapture .report-line-chart").count() == 2
        assert page.locator("#reportCapture .report-table-section tbody tr").count() == 2
        assert "推荐并发" in page.locator("#reportCapture .report-verdict").inner_text()
        assert "确定性规则" in page.locator("#reportCapture .report-foot").inner_text()

        page.locator("#reportSettingsBtn").click()
        page.locator('#reportSettingsForm [name="min_success_rate"]').fill("99")
        page.locator('#reportSettingsForm [name="hardware"]').fill("UI Test GPU")
        page.locator("#saveReportSettingsBtn").click()
        page.locator("#toast", has_text="评估标准已保存").wait_for()
        assert "成功率 ≥ 99%" in page.locator("#reportCapture .report-foot").inner_text()
        assert "UI Test GPU" in page.locator("#reportCapture .report-foot").inner_text()

        snapshot = page.evaluate(
            """async () => {
                const blob = await createElementSnapshot(
                    document.querySelector('#reportCapture'), 'INFERBENCH REPORT TEST'
                );
                return {type: blob.type, size: blob.size};
            }"""
        )
        assert snapshot["type"] == "image/png"
        assert snapshot["size"] > 10_000
        page.screenshot(path=ARTIFACTS / "performance-report.png", full_page=True)
        browser.close()

    if console_errors:
        raise AssertionError(f"browser console errors: {console_errors}")
    print(f"Report smoke passed: automatic report, settings, charts, {snapshot['size']} byte PNG")


if __name__ == "__main__":
    main()
