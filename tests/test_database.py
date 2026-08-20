from inferbench.database import Repository
from inferbench.models import RunCreate, SampleRecord


def test_repository_round_trip_and_secret_sanitization(tmp_path):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    config = RunCreate(api_key="top-secret", prompts=["private prompt"])
    persisted = config.persisted_config()
    assert "api_key" not in persisted
    assert "prompts" not in persisted
    run = repository.create_run("run-1", "test", "vllm", config.endpoint, config.model, persisted)
    repository.set_running(run["id"])
    repository.add_sample(
        run["id"],
        SampleRecord(
            request_index=0,
            ok=True,
            status_code=200,
            latency_ms=120.0,
            ttft_ms=30.0,
            input_tokens=10,
            output_tokens=20,
            token_source="usage",
        ),
    )
    repository.finish_run(run["id"], "completed")
    loaded = repository.get_run(run["id"])
    samples = repository.list_samples(run["id"])
    assert loaded["status"] == "completed"
    assert loaded["completed_requests"] == 1
    assert samples[0]["ok"] is True
    assert samples[0]["output_tokens"] == 20
    assert repository.delete_run(run["id"]) is True


def test_recover_interrupted_runs_and_keep_active_runs_visible(tmp_path):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    config = RunCreate().persisted_config()
    repository.create_run("old", "old", "vllm", "http://localhost/test", "model", config)
    repository.finish_run("old", "completed")
    repository.create_run("new", "new", "vllm", "http://localhost/test", "model", config)
    repository.finish_run("new", "completed")
    repository.create_run("active", "active", "vllm", "http://localhost/test", "model", config)

    visible = repository.list_runs(limit=1)
    assert {run["id"] for run in visible} == {"active", "new"}
    assert repository.recover_interrupted_runs() == 1
    recovered = repository.get_run("active")
    assert recovered["status"] == "cancelled"
    assert recovered["finished_at"] is not None
