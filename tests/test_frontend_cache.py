import httpx
import pytest

from inferbench.main import app


@pytest.mark.asyncio
async def test_frontend_responses_disable_stale_browser_caches():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for route in ("/", "/static/app.js?v=test"):
            response = await client.get(route)
            assert response.status_code == 200
            assert response.headers["cache-control"] == (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            assert response.headers["pragma"] == "no-cache"
            assert response.headers["expires"] == "0"
