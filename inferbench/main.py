from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import random
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .database import Repository
from .metrics import aggregate_repetitions, compare_runs, summarize
from .models import DiscoveryRequest, ReportCreate, ReportUpdate, RunCreate
from .reporting import ReportManager
from .runner import RunManager

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_DATA_DIR = Path(os.environ.get("INFERBENCH_DATA_DIR", Path.cwd() / "data"))

repository = Repository(DEFAULT_DATA_DIR / "inferbench.db")
report_manager = ReportManager(repository)
manager = RunManager(repository, report_manager)


def run_payload(run: dict[str, Any], include_samples: bool = False) -> dict[str, Any]:
    samples = repository.list_samples(run["id"])
    payload = {"run": run, "summary": summarize(run, samples)}
    if include_samples:
        payload["samples"] = samples
    return payload


@asynccontextmanager
async def lifespan(_: FastAPI):
    repository.init()
    repository.recover_interrupted_runs()
    yield
    await manager.shutdown()


app = FastAPI(
    title="InferBench Local",
    version="0.1.6",
    description="Local-first benchmark console for OpenAI-compatible inference servers.",
    lifespan=lifespan,
)


@app.middleware("http")
async def disable_frontend_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": app.version, "data_path": str(repository.path)}


def discovery_urls(endpoint: str) -> tuple[str, str]:
    parsed = urlparse(endpoint)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/models"):
        root = path[: -len("/models")]
    elif path.endswith("/v1/chat/completions"):
        root = path[: -len("/chat/completions")]
    elif path.endswith("/v1"):
        root = path
    else:
        root = path + "/v1"
    models_url = urlunparse(parsed._replace(path=root + "/models", query="", fragment=""))
    chat_url = urlunparse(parsed._replace(path=root + "/chat/completions", query="", fragment=""))
    return models_url, chat_url


@app.post("/api/discover")
async def discover_target(config: DiscoveryRequest) -> dict[str, Any]:
    api_key = config.api_key or (os.getenv(config.api_key_env) if config.api_key_env else None)
    if config.api_key_env and not api_key:
        raise HTTPException(status_code=400, detail=f"environment variable {config.api_key_env} is not set")
    models_url, chat_url = discovery_urls(config.endpoint)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    payload: dict[str, Any] | None = None
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=20.0) as client:
        for attempt in range(3):
            try:
                response = await client.get(models_url, headers=headers)
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
    if payload is None:
        status = (
            last_error.response.status_code
            if isinstance(last_error, httpx.HTTPStatusError)
            else None
        )
        if status in {502, 503, 504}:
            detail = f"远端推理服务当前返回 HTTP {status}，可能正在启动、已停止或网关不可达；已自动重试 3 次"
        else:
            detail = f"模型检测失败：{last_error}"
        raise HTTPException(status_code=502, detail=detail)
    models = [
        {
            "id": item.get("id"),
            "owned_by": item.get("owned_by"),
            "max_model_len": item.get("max_model_len"),
        }
        for item in payload.get("data", [])
        if item.get("id")
    ]
    if not models:
        raise HTTPException(status_code=502, detail="the models endpoint returned no model IDs")
    return {"models_url": models_url, "chat_endpoint": chat_url, "models": models}


@app.post("/api/runs", status_code=202)
async def create_run(config: RunCreate) -> dict[str, Any]:
    if config.api_key_env and not os.getenv(config.api_key_env):
        raise HTTPException(status_code=400, detail=f"environment variable {config.api_key_env} is not set")
    run = manager.start(config)
    return run_payload(run)


@app.get("/api/runs")
async def list_runs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return [run_payload(run) for run in repository.list_runs(limit)]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run_payload(run, include_samples=True)


@app.get("/api/runs/{run_id}/export")
async def export_run(
    run_id: str, format: str = Query(default="csv", pattern="^(csv|json)$")
) -> Response:
    run = repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    payload = run_payload(run, include_samples=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", run_id)[:64] or "run"
    if format == "json":
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="inferbench-{safe_id}.json"'},
        )

    fields = [
        "run_id", "run_name", "status", "framework", "model", "endpoint",
        "concurrency", "request_target", "repetition", "repetitions",
        "request_index", "ok", "status_code", "latency_ms", "ttft_ms",
        "input_tokens", "output_tokens", "token_source", "error", "started_offset_ms",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    config = run.get("config", {})
    for sample in payload["samples"]:
        writer.writerow({
            "run_id": run["id"], "run_name": run["name"], "status": run["status"],
            "framework": run["framework"], "model": run["model"], "endpoint": run["endpoint"],
            "concurrency": config.get("concurrency"), "request_target": config.get("requests"),
            "repetition": config.get("repetition"), "repetitions": config.get("repetitions"),
            **sample,
        })
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="inferbench-{safe_id}.csv"'},
    )


@app.post("/api/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str) -> dict[str, bool]:
    if not repository.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    if not manager.cancel(run_id):
        raise HTTPException(status_code=409, detail="run is not active")
    return {"accepted": True}


@app.post("/api/suites/{suite_id}/cancel", status_code=202)
async def cancel_suite(suite_id: str) -> dict[str, int]:
    return {"cancelled": manager.cancel_suite(suite_id)}


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str) -> dict[str, bool]:
    if manager.is_active(run_id):
        raise HTTPException(status_code=409, detail="cancel the active run before deleting it")
    if not repository.delete_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"deleted": True}


@app.get("/api/compare")
async def compare(
    ids: str = Query(min_length=1), aggregate: bool = Query(default=False)
) -> dict[str, Any]:
    run_ids = [run_id.strip() for run_id in ids.split(",") if run_id.strip()]
    if len(run_ids) < 2 or len(run_ids) > 64:
        raise HTTPException(status_code=400, detail="select between 2 and 64 runs")
    items: list[dict[str, Any]] = []
    for run_id in run_ids:
        run = repository.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")
        items.append(run_payload(run))
    if aggregate:
        items = aggregate_repetitions(items)
    result = compare_runs(items)
    result["aggregation"] = "repetition_mean" if aggregate else "none"
    return result


@app.get("/api/reports")
async def list_reports(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return repository.list_reports(limit)


@app.post("/api/reports", status_code=201)
async def create_report(config: ReportCreate) -> dict[str, Any]:
    try:
        return report_manager.generate(
            config.suite_id,
            title=config.title,
            criteria=config.criteria.model_dump(),
            environment=config.environment,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/reports/by-suite/{suite_id}")
async def get_report_by_suite(suite_id: str) -> dict[str, Any]:
    report = repository.get_report_by_suite(suite_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@app.get("/api/reports/{report_id}")
async def get_report(report_id: str) -> dict[str, Any]:
    report = repository.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return report


@app.put("/api/reports/{report_id}")
async def update_report(report_id: str, config: ReportUpdate) -> dict[str, Any]:
    report = repository.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    return report_manager.generate(
        report["suite_id"],
        title=config.title or report["title"],
        criteria=config.criteria.model_dump() if config.criteria is not None else report["criteria"],
        environment=config.environment if config.environment is not None else report["environment"],
    )


@app.get("/api/reports/{report_id}/export")
async def export_report(report_id: str) -> Response:
    report = repository.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="report not found")
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", report_id)[:64] or "report"
    return Response(
        content=json.dumps(report, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="inferbench-{safe_id}.json"'},
    )


@app.delete("/api/reports/{report_id}")
async def delete_report(report_id: str) -> dict[str, bool]:
    if not repository.delete_report(report_id):
        raise HTTPException(status_code=404, detail="report not found")
    return {"deleted": True}


MOCK_WORDS = (
    "Batching amortizes model execution overhead across requests while keeping the accelerator busy. "
    "The best operating point balances queue delay, memory pressure, and decode throughput. "
    "Measure tail latency and time to first token alongside aggregate tokens per second."
).split()


@app.post("/mock/v1/chat/completions")
async def mock_chat_completions(request: Request) -> StreamingResponse:
    body = await request.json()
    model = body.get("model", "mock-model")
    max_tokens = min(max(int(body.get("max_tokens", 128)), 1), 128)
    messages = body.get("messages") or []
    prompt = " ".join(str(message.get("content", "")) for message in messages)
    prompt_tokens = max(1, (len(prompt) + 3) // 4)
    output_words = [MOCK_WORDS[index % len(MOCK_WORDS)] for index in range(max_tokens)]
    request_id = f"mock-{int(time.time() * 1000)}-{random.randint(100, 999)}"

    async def event_stream():
        await asyncio.sleep(0.035 + random.random() * 0.02)
        for index, word in enumerate(output_words):
            payload = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": word + (" " if index < len(output_words) - 1 else "")},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.004 + random.random() * 0.003)
        usage_payload = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": max_tokens,
                "total_tokens": prompt_tokens + max_tokens,
            },
        }
        yield f"data: {json.dumps(usage_payload)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
