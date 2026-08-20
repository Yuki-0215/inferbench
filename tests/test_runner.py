import asyncio

from inferbench.database import Repository
from inferbench.models import RunCreate
from inferbench.runner import ActiveRun, RunManager


async def test_cancel_immediately_cancels_task_and_persists_status(tmp_path):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    config = RunCreate(suite_id="suite-a")
    repository.create_run(
        "run-a", "run", config.framework, config.endpoint, config.model, config.persisted_config()
    )
    task = asyncio.create_task(asyncio.sleep(60))
    manager = RunManager(repository)
    manager.active["run-a"] = ActiveRun(task, asyncio.Event(), "suite-a")

    assert manager.cancel("run-a") is True
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert repository.get_run("run-a")["status"] == "cancelled"


async def test_cancel_suite_only_stops_matching_active_runs(tmp_path):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    manager = RunManager(repository)
    tasks = []
    for run_id, suite_id in (("run-a", "suite-a"), ("run-b", "suite-a"), ("run-c", "suite-b")):
        config = RunCreate(suite_id=suite_id)
        repository.create_run(
            run_id, run_id, config.framework, config.endpoint, config.model, config.persisted_config()
        )
        task = asyncio.create_task(asyncio.sleep(60))
        tasks.append(task)
        manager.active[run_id] = ActiveRun(task, asyncio.Event(), suite_id)

    assert manager.cancel_suite("suite-a") == 2
    await asyncio.sleep(0)

    assert tasks[0].cancelled()
    assert tasks[1].cancelled()
    assert not tasks[2].done()
    assert repository.get_run("run-c")["status"] == "queued"
    tasks[2].cancel()
    await asyncio.gather(tasks[2], return_exceptions=True)
