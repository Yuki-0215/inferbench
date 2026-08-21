from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


class RunCreate(BaseModel):
    name: str = Field(default="Untitled run", min_length=1, max_length=80)
    framework: Literal["vllm", "sglang", "openai-compatible"] = "vllm"
    endpoint: str = "http://127.0.0.1:8080/mock/v1/chat/completions"
    model: str = Field(default="demo-model", min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    concurrency: int = Field(default=4, ge=1, le=256)
    requests: int = Field(default=20, ge=1, le=10_000)
    warmup_requests: int = Field(default=1, ge=0, le=100)
    max_tokens: int = Field(default=128, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_s: float = Field(default=120.0, ge=1.0, le=1800.0)
    prompts: list[str] = Field(
        default_factory=lambda: [
            "Explain why batching improves LLM inference throughput in three sentences.",
            "Write a compact Python function that computes a percentile.",
            "Compare tensor parallelism and pipeline parallelism for inference.",
        ],
        min_length=1,
        max_length=1000,
    )
    extra_body: dict[str, Any] = Field(default_factory=dict)
    suite_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    suite_name: str | None = Field(default=None, min_length=1, max_length=80)
    repetition: int = Field(default=1, ge=1, le=20)
    repetitions: int = Field(default=1, ge=1, le=20)
    suite_total_runs: int | None = Field(default=None, ge=1, le=160)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an absolute http(s) URL")
        normalized = value.rstrip("/")
        if normalized.endswith("/v1/models"):
            normalized = normalized[: -len("/models")] + "/chat/completions"
        return normalized

    @field_validator("prompts")
    @classmethod
    def validate_prompts(cls, prompts: list[str]) -> list[str]:
        cleaned = [prompt.strip() for prompt in prompts if prompt.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty prompt is required")
        if any(len(prompt) > 20_000 for prompt in cleaned):
            raise ValueError("each prompt must be at most 20,000 characters")
        return cleaned

    @model_validator(mode="after")
    def validate_extra_body(self) -> "RunCreate":
        protected = {"model", "messages", "stream", "stream_options"}
        overlap = protected.intersection(self.extra_body)
        if overlap:
            raise ValueError(f"extra_body cannot override: {', '.join(sorted(overlap))}")
        return self

    def persisted_config(self) -> dict[str, Any]:
        prompt_fingerprint = hashlib.sha256(
            json.dumps(self.prompts, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "concurrency": self.concurrency,
            "requests": self.requests,
            "warmup_requests": self.warmup_requests,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout_s": self.timeout_s,
            "prompt_count": len(self.prompts),
            "prompt_chars": sum(len(prompt) for prompt in self.prompts),
            "prompt_fingerprint": prompt_fingerprint,
            "extra_body": self.extra_body,
            "credential_source": "env" if self.api_key_env else ("inline" if self.api_key else "none"),
            "suite_id": self.suite_id,
            "suite_name": self.suite_name,
            "repetition": self.repetition,
            "repetitions": self.repetitions,
            "suite_total_runs": self.suite_total_runs,
        }


class ReportCriteria(BaseModel):
    min_success_rate: float | None = Field(default=None, ge=0, le=100)
    min_output_throughput_tps: float | None = Field(default=None, ge=0)
    max_ttft_p95_ms: float | None = Field(default=None, ge=0)
    max_latency_p95_ms: float | None = Field(default=None, ge=0)


class ReportCreate(BaseModel):
    suite_id: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str | None = Field(default=None, min_length=1, max_length=120)
    criteria: ReportCriteria = Field(default_factory=ReportCriteria)
    environment: dict[str, str] = Field(default_factory=dict)


class ReportUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    criteria: ReportCriteria | None = None
    environment: dict[str, str] | None = None


class SampleRecord(BaseModel):
    request_index: int
    ok: bool
    status_code: int | None = None
    latency_ms: float
    ttft_ms: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    token_source: Literal["usage", "estimated"] = "estimated"
    error: str | None = None
    started_offset_ms: float = 0.0


class DiscoveryRequest(BaseModel):
    endpoint: str
    api_key: str | None = Field(default=None, max_length=4096)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an absolute http(s) URL")
        return value.rstrip("/")
