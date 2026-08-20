from __future__ import annotations

import json
import math
import time
from typing import Any

import httpx

from .models import RunCreate, SampleRecord


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4)) if text else 0


async def issue_chat_request(
    client: httpx.AsyncClient,
    config: RunCreate,
    api_key: str | None,
    prompt: str,
    request_index: int,
    run_started_perf: float,
) -> SampleRecord:
    started = time.perf_counter()
    first_token_at: float | None = None
    status_code: int | None = None
    output_parts: list[str] = []
    usage: dict[str, Any] | None = None
    headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body: dict[str, Any] = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        **config.extra_body,
    }
    try:
        async with client.stream("POST", config.endpoint, json=body, headers=headers) as response:
            status_code = response.status_code
            if response.status_code < 200 or response.status_code >= 300:
                payload = (await response.aread()).decode("utf-8", errors="replace")[:1000]
                raise RuntimeError(f"HTTP {response.status_code}: {payload}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("usage"):
                    usage = event["usage"]
                choices = event.get("choices") or []
                if choices:
                    content = (choices[0].get("delta") or {}).get("content")
                    if isinstance(content, str) and content:
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                        output_parts.append(content)
        ended = time.perf_counter()
        output = "".join(output_parts)
        input_tokens = int((usage or {}).get("prompt_tokens") or estimate_tokens(prompt))
        output_tokens = int((usage or {}).get("completion_tokens") or estimate_tokens(output))
        token_source = "usage" if usage and usage.get("completion_tokens") is not None else "estimated"
        return SampleRecord(
            request_index=request_index,
            ok=True,
            status_code=status_code,
            latency_ms=(ended - started) * 1000,
            ttft_ms=((first_token_at - started) * 1000) if first_token_at else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            token_source=token_source,
            started_offset_ms=(started - run_started_perf) * 1000,
        )
    except Exception as exc:
        ended = time.perf_counter()
        return SampleRecord(
            request_index=request_index,
            ok=False,
            status_code=status_code,
            latency_ms=(ended - started) * 1000,
            ttft_ms=((first_token_at - started) * 1000) if first_token_at else None,
            input_tokens=estimate_tokens(prompt),
            output_tokens=estimate_tokens("".join(output_parts)),
            token_source="estimated",
            error=str(exc)[:1000],
            started_offset_ms=(started - run_started_perf) * 1000,
        )

