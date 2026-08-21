"""Browser smoke test for bulk-selecting and deleting completed runs."""

import os

from playwright.sync_api import sync_playwright


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE_URL = os.getenv("INFERBENCH_TEST_URL", "http://127.0.0.1:8080").rstrip("/")


def create_run(page, name: str, requests: int = 1, max_tokens: int = 2) -> str:
    response = page.request.post(
        f"{BASE_URL}/api/runs",
        data={
            "name": name,
            "endpoint": f"{BASE_URL}/mock/v1/chat/completions",
            "model": "demo-model",
            "concurrency": 1,
            "requests": requests,
            "warmup_requests": 0,
            "max_tokens": max_tokens,
        },
    )
    assert response.ok
    return response.json()["run"]["id"]


def main() -> None:
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(BASE_URL, wait_until="networkidle")
        completed_ids = [create_run(page, f"Bulk delete smoke {index}") for index in range(3)]
        page.wait_for_function(
            """async ids => {
                const runs = await fetch('/api/runs').then(response => response.json());
                return ids.every(id => runs.find(item => item.run.id === id)?.run.status === 'completed');
            }""",
            arg=completed_ids,
        )
        active_id = create_run(page, "Bulk delete protected", requests=100, max_tokens=128)
        page.reload(wait_until="networkidle")

        page.locator("#bulkModeBtn").click()
        page.locator("#bulkDeleteBar").wait_for(state="visible")
        assert page.locator(f'[data-delete-id="{active_id}"]').is_disabled()
        page.locator(f'[data-delete-id="{completed_ids[0]}"]').click()
        page.locator(f'[data-delete-id="{completed_ids[1]}"]').click()
        assert page.locator("#bulkSelectedCount").inner_text() == "2"

        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#bulkDeleteBtn").click()
        page.locator("#toast", has_text="已删除 2 个实验").wait_for()
        page.wait_for_function(
            """async ids => {
                const runs = await fetch('/api/runs').then(response => response.json());
                return ids.every(id => !runs.some(item => item.run.id === id));
            }""",
            arg=completed_ids[:2],
        )
        remaining = page.request.get(f"{BASE_URL}/api/runs").json()
        remaining_ids = {item["run"]["id"] for item in remaining}
        assert completed_ids[2] in remaining_ids
        assert active_id in remaining_ids
        assert page.request.post(f"{BASE_URL}/api/runs/{active_id}/cancel").ok
        browser.close()

    if console_errors:
        raise AssertionError(f"browser console errors: {console_errors}")
    print("Bulk delete smoke passed: selected two, protected active run, deleted two")


if __name__ == "__main__":
    main()
