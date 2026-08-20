from inferbench.metrics import aggregate_repetitions, compare_runs, percentile, summarize


def make_run(run_id: str, throughput_scale: float = 1.0):
    run = {
        "id": run_id,
        "name": run_id,
        "status": "completed",
        "framework": "vllm",
        "model": "demo",
        "config": {"prompt_fingerprint": "same", "max_tokens": 8, "temperature": 0},
        "started_at": 100.0,
        "finished_at": 102.0 / throughput_scale,
    }
    samples = [
        {"ok": True, "latency_ms": 100.0, "ttft_ms": 20.0, "output_tokens": 8, "input_tokens": 5, "token_source": "usage"},
        {"ok": True, "latency_ms": 200.0, "ttft_ms": 30.0, "output_tokens": 8, "input_tokens": 5, "token_source": "usage"},
    ]
    return {"run": run, "summary": summarize(run, samples)}


def test_percentile_uses_linear_interpolation():
    assert percentile([100, 200], 0.95) == 195.0
    assert percentile([], 0.50) is None


def test_summary_has_expected_core_metrics():
    item = make_run("a")
    summary = item["summary"]
    assert summary["success_rate"] == 100.0
    assert summary["latency_ms"]["p50"] == 150.0
    assert summary["ttft_ms"]["p50"] == 25.0
    assert summary["output_tokens"] == 16
    assert summary["estimated_token_samples"] == 0


def test_compare_returns_ranked_items_and_baseline():
    baseline = make_run("baseline")
    challenger = make_run("challenger", throughput_scale=2.0)
    result = compare_runs([baseline, challenger])
    assert result["baseline_id"] == "baseline"
    assert {item["run"]["id"] for item in result["items"]} == {"baseline", "challenger"}
    assert result["items"][0]["score"] >= result["items"][1]["score"]
    assert result["warnings"] == []


def test_repetitions_are_averaged_by_suite_and_concurrency():
    items = []
    for repetition, throughput in enumerate((90.0, 100.0, 110.0), start=1):
        item = make_run(f"repeat-{repetition}")
        item["run"]["name"] = f"matrix · C8 · R{repetition}"
        item["run"]["config"].update(
            {"suite_id": "suite-a", "suite_name": "matrix", "concurrency": 8, "repetition": repetition}
        )
        item["summary"]["output_throughput_tps"] = throughput
        items.append(item)
    grouped = aggregate_repetitions(items)
    assert len(grouped) == 1
    assert grouped[0]["summary"]["output_throughput_tps"] == 100.0
    assert grouped[0]["repeat_aggregation"]["runs"] == 3
    assert grouped[0]["repeat_aggregation"]["output_throughput_cv_pct"] > 0
    assert "AVG×3" in grouped[0]["run"]["name"]
