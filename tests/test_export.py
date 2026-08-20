import csv
import io
import json

import httpx
import pytest

from inferbench import main
from inferbench.database import Repository
from inferbench.models import RunCreate, SampleRecord


@pytest.mark.asyncio
async def test_export_run_csv_and_json(tmp_path, monkeypatch):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    monkeypatch.setattr(main, "repository", repository)
    config = RunCreate(
        name="export test",
        endpoint="http://localhost/v1/chat/completions",
        model="demo-model",
    )
    repository.create_run(
        "run-export",
        config.name,
        config.framework,
        config.endpoint,
        config.model,
        config.persisted_config(),
    )
    repository.add_sample(
        "run-export",
        SampleRecord(
            request_index=0,
            ok=True,
            status_code=200,
            latency_ms=123.4,
            ttft_ms=22.3,
            input_tokens=10,
            output_tokens=20,
            token_source="usage",
        ),
    )
    repository.finish_run("run-export", "completed")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        csv_response = await client.get("/api/runs/run-export/export?format=csv")
        json_response = await client.get("/api/runs/run-export/export?format=json")

    assert csv_response.status_code == 200
    assert "attachment" in csv_response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(csv_response.text.lstrip("\ufeff"))))
    assert rows[0]["run_id"] == "run-export"
    assert rows[0]["output_tokens"] == "20"
    assert rows[0]["token_source"] == "usage"

    assert json_response.status_code == 200
    payload = json.loads(json_response.text)
    assert payload["run"]["name"] == "export test"
    assert payload["samples"][0]["latency_ms"] == 123.4


@pytest.mark.asyncio
async def test_export_run_rejects_unknown_format(tmp_path, monkeypatch):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    monkeypatch.setattr(main, "repository", repository)
    repository.create_run(
        "run-format",
        "format test",
        "vllm",
        "http://localhost/v1/chat/completions",
        "demo-model",
        RunCreate().persisted_config(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        response = await client.get("/api/runs/run-format/export?format=xml")

    assert response.status_code == 422
