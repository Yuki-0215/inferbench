from __future__ import annotations

import math
import copy
import statistics
import time
from typing import Any, Iterable


def percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 3)


def summarize(run: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [sample for sample in samples if sample["ok"]]
    latencies = [sample["latency_ms"] for sample in successful]
    ttfts = [sample["ttft_ms"] for sample in successful if sample["ttft_ms"] is not None]
    tpots = [
        (sample["latency_ms"] - sample["ttft_ms"]) / max(sample["output_tokens"] - 1, 1)
        for sample in successful
        if sample["ttft_ms"] is not None and sample["output_tokens"] > 0
    ]
    started_at = run.get("started_at")
    finished_at = run.get("finished_at")
    elapsed_s = 0.0
    if started_at:
        elapsed_s = max(0.0, (finished_at or time.time()) - started_at)
    output_tokens = sum(sample["output_tokens"] for sample in successful)
    input_tokens = sum(sample["input_tokens"] for sample in successful)
    total = len(samples)
    return {
        "total": total,
        "successful": len(successful),
        "failed": total - len(successful),
        "success_rate": round((len(successful) / total * 100) if total else 0.0, 3),
        "elapsed_s": round(elapsed_s, 3),
        "request_throughput_rps": round(len(successful) / elapsed_s, 3) if elapsed_s else 0.0,
        "output_throughput_tps": round(output_tokens / elapsed_s, 3) if elapsed_s else 0.0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "p50": percentile(latencies, 0.50),
            "p90": percentile(latencies, 0.90),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "ttft_ms": {
            "mean": round(sum(ttfts) / len(ttfts), 3) if ttfts else None,
            "p50": percentile(ttfts, 0.50),
            "p95": percentile(ttfts, 0.95),
            "p99": percentile(ttfts, 0.99),
        },
        "tpot_ms": {
            "mean": round(sum(tpots) / len(tpots), 3) if tpots else None,
            "p50": percentile(tpots, 0.50),
            "p95": percentile(tpots, 0.95),
        },
        "estimated_token_samples": sum(
            1 for sample in successful if sample["token_source"] == "estimated"
        ),
    }


def _normalize(values: list[float], higher_is_better: bool) -> list[float]:
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [100.0] * len(values)
    normalized = [(value - low) / (high - low) * 100 for value in values]
    if not higher_is_better:
        normalized = [100 - value for value in normalized]
    return normalized


def compare_runs(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"baseline_id": None, "items": [], "warnings": []}
    baseline = items[0]
    vectors = {
        "throughput": [item["summary"]["output_throughput_tps"] for item in items],
        "ttft": [(item["summary"]["ttft_ms"]["p50"] or 1e12) for item in items],
        "p95": [(item["summary"]["latency_ms"]["p95"] or 1e12) for item in items],
        "success": [item["summary"]["success_rate"] for item in items],
    }
    normalized = {
        "throughput": _normalize(vectors["throughput"], True),
        "ttft": _normalize(vectors["ttft"], False),
        "p95": _normalize(vectors["p95"], False),
        "success": _normalize(vectors["success"], True),
    }

    output: list[dict[str, Any]] = []
    baseline_summary = baseline["summary"]
    for index, item in enumerate(items):
        score = (
            0.35 * normalized["throughput"][index]
            + 0.25 * normalized["ttft"][index]
            + 0.25 * normalized["p95"][index]
            + 0.15 * normalized["success"][index]
        )
        changes: dict[str, float | None] = {}
        pairs = {
            "output_throughput_tps": (
                item["summary"]["output_throughput_tps"],
                baseline_summary["output_throughput_tps"],
            ),
            "ttft_p50_ms": (item["summary"]["ttft_ms"]["p50"], baseline_summary["ttft_ms"]["p50"]),
            "latency_p95_ms": (
                item["summary"]["latency_ms"]["p95"],
                baseline_summary["latency_ms"]["p95"],
            ),
        }
        for key, (value, base_value) in pairs.items():
            changes[key] = (
                round((value - base_value) / base_value * 100, 2)
                if value is not None and base_value not in {None, 0}
                else None
            )
        output.append(item | {"score": round(score, 2), "vs_baseline_pct": changes})

    comparable_fields = ["model", "framework"]
    warnings: list[str] = []
    for field in comparable_fields:
        values = {item["run"].get(field) for item in items}
        if len(values) > 1:
            warnings.append(f"{field} differs across selected runs")
    fingerprints = {item["run"]["config"].get("prompt_fingerprint") for item in items}
    if len(fingerprints) > 1:
        warnings.append("prompt dataset differs across selected runs")
    workloads = {
        (item["run"]["config"].get("max_tokens"), item["run"]["config"].get("temperature"))
        for item in items
    }
    if len(workloads) > 1:
        warnings.append("generation parameters differ across selected runs")
    output.sort(key=lambda item: item["score"], reverse=True)
    return {"baseline_id": baseline["run"]["id"], "items": output, "warnings": warnings}


def _average_nodes(nodes: list[Any]) -> Any:
    if not nodes:
        return None
    if all(isinstance(node, dict) for node in nodes):
        keys = set.intersection(*(set(node.keys()) for node in nodes))
        return {key: _average_nodes([node[key] for node in nodes]) for key in keys}
    numeric = [float(node) for node in nodes if isinstance(node, (int, float)) and node is not None]
    if numeric:
        return round(sum(numeric) / len(numeric), 3)
    return nodes[0]


def _coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = statistics.mean(values)
    return round(statistics.pstdev(values) / mean * 100, 2) if mean else None


def aggregate_repetitions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Average repeated runs while preserving concurrency as the comparison axis."""
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    order: list[tuple[str, int]] = []
    for item in items:
        config = item["run"]["config"]
        suite_id = config.get("suite_id") or item["run"]["id"]
        key = (suite_id, int(config.get("concurrency") or 1))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    aggregated: list[dict[str, Any]] = []
    for suite_id, concurrency in order:
        group = sorted(groups[(suite_id, concurrency)], key=lambda item: item["run"]["config"].get("repetition", 1))
        if len(group) == 1 and not group[0]["run"]["config"].get("suite_id"):
            aggregated.append(group[0])
            continue
        run = copy.deepcopy(group[0]["run"])
        suite_name = run["config"].get("suite_name") or run["name"]
        run["id"] = f"{suite_id}-c{concurrency}"
        run["name"] = f"{suite_name} · C{concurrency} · AVG×{len(group)}"
        run["status"] = "completed" if all(item["run"]["status"] == "completed" for item in group) else "partial"
        run["completed_requests"] = round(
            sum(item["run"].get("completed_requests", item["summary"].get("total", 0)) for item in group)
            / len(group)
        )
        summary = _average_nodes([item["summary"] for item in group])
        throughputs = [item["summary"]["output_throughput_tps"] for item in group]
        latencies = [item["summary"]["latency_ms"]["p95"] for item in group if item["summary"]["latency_ms"]["p95"] is not None]
        ttfts = [item["summary"]["ttft_ms"]["p50"] for item in group if item["summary"]["ttft_ms"]["p50"] is not None]
        aggregated.append(
            {
                "run": run,
                "summary": summary,
                "repeat_aggregation": {
                    "runs": len(group),
                    "run_ids": [item["run"]["id"] for item in group],
                    "output_throughput_cv_pct": _coefficient_of_variation(throughputs),
                    "latency_p95_cv_pct": _coefficient_of_variation(latencies),
                    "ttft_p50_cv_pct": _coefficient_of_variation(ttfts),
                },
            }
        )
    return aggregated
