from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass

import httpx

from .adapter import issue_chat_request
from .database import Repository
from .models import RunCreate
from .reporting import ReportManager


@dataclass
class ActiveRun:
    task: asyncio.Task[None]
    cancel_event: asyncio.Event
    suite_id: str | None


class RunManager:
    def __init__(self, repository: Repository, report_manager: ReportManager | None = None):
        self.repository = repository
        self.report_manager = report_manager or ReportManager(repository)
        self.active: dict[str, ActiveRun] = {}
        # Only one measured run may pressure a target at a time. This keeps
        # matrix levels and repetitions from contaminating each other's data.
        self._benchmark_slot = asyncio.Semaphore(1)

    def start(self, config: RunCreate) -> dict:
        run_id = uuid.uuid4().hex[:12]
        run = self.repository.create_run(
            run_id,
            config.name,
            config.framework,
            config.endpoint,
            config.model,
            config.persisted_config(),
        )
        cancel_event = asyncio.Event()
        task = asyncio.create_task(self._execute_serialized(run_id, config, cancel_event))
        self.active[run_id] = ActiveRun(
            task=task, cancel_event=cancel_event, suite_id=config.suite_id
        )
        task.add_done_callback(lambda _: self.active.pop(run_id, None))
        return run

    def cancel(self, run_id: str) -> bool:
        active = self.active.get(run_id)
        if not active:
            return False
        active.cancel_event.set()
        # Persist the visible state before cancelling so the API/UI reflects the
        # stop immediately, even when the task was still waiting for the slot.
        self.repository.finish_run(run_id, "cancelled", "cancelled by user")
        if active.suite_id:
            self.report_manager.safe_maybe_generate(active.suite_id)
        if not active.task.done():
            active.task.cancel()
        return True

    def cancel_suite(self, suite_id: str) -> int:
        run_ids = [
            run_id
            for run_id, active in list(self.active.items())
            if active.suite_id == suite_id
        ]
        return sum(self.cancel(run_id) for run_id in run_ids)

    def is_active(self, run_id: str) -> bool:
        return run_id in self.active

    async def shutdown(self) -> None:
        active = list(self.active.items())
        for run_id, _ in active:
            self.cancel(run_id)
        if active:
            await asyncio.gather(*(item.task for _, item in active), return_exceptions=True)

    async def _execute_serialized(
        self, run_id: str, config: RunCreate, cancel_event: asyncio.Event
    ) -> None:
        async with self._benchmark_slot:
            await self._execute(run_id, config, cancel_event)

    async def _execute(self, run_id: str, config: RunCreate, cancel_event: asyncio.Event) -> None:
        api_key = config.api_key or (os.getenv(config.api_key_env) if config.api_key_env else None)
        timeout = httpx.Timeout(config.timeout_s, connect=min(15.0, config.timeout_s))
        limits = httpx.Limits(
            max_connections=max(config.concurrency + 4, 10),
            max_keepalive_connections=max(config.concurrency, 5),
        )
        try:
            async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
                warmup_started_perf = time.perf_counter()
                for warmup_index in range(config.warmup_requests):
                    if cancel_event.is_set():
                        break
                    await issue_chat_request(
                        client,
                        config,
                        api_key,
                        config.prompts[warmup_index % len(config.prompts)],
                        -(warmup_index + 1),
                        warmup_started_perf,
                    )

                if cancel_event.is_set():
                    self._finish(run_id, config, "cancelled")
                    return

                # The measured wall time intentionally starts after warmup so
                # throughput is not diluted by cache/model initialization probes.
                self.repository.set_running(run_id)
                run_started_perf = time.perf_counter()

                queue: asyncio.Queue[int] = asyncio.Queue()
                for request_index in range(config.requests):
                    queue.put_nowait(request_index)

                async def worker() -> None:
                    while not cancel_event.is_set():
                        try:
                            request_index = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            return
                        sample = await issue_chat_request(
                            client,
                            config,
                            api_key,
                            config.prompts[request_index % len(config.prompts)],
                            request_index,
                            run_started_perf,
                        )
                        self.repository.add_sample(run_id, sample)
                        queue.task_done()

                workers = [asyncio.create_task(worker()) for _ in range(config.concurrency)]
                await asyncio.gather(*workers)
            if cancel_event.is_set():
                self._finish(run_id, config, "cancelled")
            else:
                self._finish(run_id, config, "completed")
        except asyncio.CancelledError:
            self._finish(run_id, config, "cancelled", "cancelled by user")
            raise
        except Exception as exc:
            self._finish(run_id, config, "failed", str(exc)[:2000])

    def _finish(
        self, run_id: str, config: RunCreate, status: str, error: str | None = None
    ) -> None:
        self.repository.finish_run(run_id, status, error)
        if config.suite_id:
            self.report_manager.safe_maybe_generate(config.suite_id, config.suite_total_runs)
