from inferbench.database import Repository
from inferbench.models import RunCreate, SampleRecord
from inferbench.reporting import ReportManager, build_report_snapshot


def create_suite(repository: Repository, suite_id: str = "suite-report") -> list[dict]:
    runs = []
    throughput = {1: 100.0, 2: 180.0, 4: 185.0}
    latency = {1: 100.0, 2: 130.0, 4: 300.0}
    for concurrency in (1, 2, 4):
        for repetition in range(1, 4):
            config = RunCreate(
                suite_id=suite_id,
                suite_name="Capacity study",
                suite_total_runs=9,
                concurrency=concurrency,
                repetition=repetition,
                repetitions=3,
                requests=3,
                max_tokens=100,
            )
            run_id = f"c{concurrency}-r{repetition}"
            repository.create_run(
                run_id, run_id, config.framework, config.endpoint, config.model, config.persisted_config()
            )
            for index in range(3):
                repository.add_sample(
                    run_id,
                    SampleRecord(
                        request_index=index,
                        ok=True,
                        status_code=200,
                        latency_ms=latency[concurrency],
                        ttft_ms=latency[concurrency] / 3,
                        input_tokens=20,
                        output_tokens=100,
                        token_source="usage",
                    ),
                )
            repository.finish_run(run_id, "completed")
            elapsed = 300 / throughput[concurrency]
            with repository._connect() as connection:
                connection.execute(
                    "UPDATE runs SET started_at=1000, finished_at=? WHERE id=?",
                    (1000 + elapsed, run_id),
                )
            runs.append(repository.get_run(run_id))
    return runs


def test_report_detects_saturation_and_recommends_previous_level(tmp_path):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    runs = create_suite(repository)
    samples = {run["id"]: repository.list_samples(run["id"]) for run in runs}

    snapshot = build_report_snapshot(runs, samples)

    assert snapshot["saturation"]["detected"] is True
    assert snapshot["saturation"]["concurrency"] == 4
    assert snapshot["headline"]["recommended_concurrency"] == 2
    assert snapshot["headline"]["peak_output_throughput_tps"] == 185.0
    assert len(snapshot["levels"]) == 3
    assert snapshot["levels"][0]["repetitions"] == 3
    assert snapshot["quality"]["grade"] == "A"


def test_report_manager_waits_for_full_suite_and_upserts_snapshot(tmp_path):
    repository = Repository(tmp_path / "bench.db")
    repository.init()
    runs = create_suite(repository)
    manager = ReportManager(repository)
    repository.finish_run(runs[-1]["id"], "running")

    assert manager.maybe_generate("suite-report", 9) is None

    repository.finish_run(runs[-1]["id"], "completed")
    report = manager.maybe_generate("suite-report", 9)
    assert report is not None
    assert report["suite_id"] == "suite-report"
    assert len(report["run_ids"]) == 9

    updated = manager.generate(
        "suite-report",
        criteria={"min_success_rate": 99.9},
        environment={"hardware": "2x H100"},
    )
    assert updated["id"] == report["id"]
    assert updated["criteria"]["min_success_rate"] == 99.9
    assert updated["environment"]["hardware"] == "2x H100"
    assert len(repository.list_reports()) == 1
