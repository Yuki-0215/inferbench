import json

import httpx
import pytest

from inferbench import main
from inferbench.database import Repository
from inferbench.reporting import ReportManager
from tests.test_reporting import create_suite


@pytest.mark.asyncio
async def test_report_crud_update_and_export(tmp_path, monkeypatch):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    create_suite(repository, "api-suite")
    report_manager = ReportManager(repository)
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(main, "report_manager", report_manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/reports",
            json={"suite_id": "api-suite", "environment": {"hardware": "H100"}},
        )
        assert created.status_code == 201
        report_id = created.json()["id"]

        listed = await client.get("/api/reports")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == report_id

        updated = await client.put(
            f"/api/reports/{report_id}",
            json={"criteria": {"max_latency_p95_ms": 250}},
        )
        assert updated.status_code == 200
        assert updated.json()["criteria"]["max_latency_p95_ms"] == 250

        exported = await client.get(f"/api/reports/{report_id}/export")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        assert json.loads(exported.text)["snapshot"]["analysis_version"] == "1.0"

        deleted = await client.delete(f"/api/reports/{report_id}")
        assert deleted.status_code == 200
        assert (await client.get(f"/api/reports/{report_id}")).status_code == 404
