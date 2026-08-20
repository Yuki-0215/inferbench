import httpx
import pytest

from inferbench.adapter import issue_chat_request
from inferbench.main import app
from inferbench.models import RunCreate


@pytest.mark.asyncio
async def test_adapter_parses_mock_sse_usage():
    transport = httpx.ASGITransport(app=app)
    config = RunCreate(
        endpoint="http://inferbench/mock/v1/chat/completions",
        max_tokens=5,
        prompts=["hello"],
    )
    async with httpx.AsyncClient(transport=transport) as client:
        sample = await issue_chat_request(client, config, None, "hello", 0, 0.0)
    assert sample.ok is True
    assert sample.status_code == 200
    assert sample.output_tokens == 5
    assert sample.token_source == "usage"
    assert sample.ttft_ms is not None

