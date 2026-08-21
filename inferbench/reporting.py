from __future__ import annotations

import hashlib
import logging
import math
import time
from collections import Counter
from typing import Any
from urllib.parse import urlparse, urlunparse

from .database import Repository
from .metrics import aggregate_repetitions, summarize


ANALYSIS_VERSION = "1.0"
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
logger = logging.getLogger(__name__)


def _redact_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    return urlunparse(parsed._replace(query="", fragment=""))


def _change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in {None, 0}:
        return None
    return round((current - previous) / previous * 100, 2)


def _passes_criteria(summary: dict[str, Any], criteria: dict[str, Any]) -> bool:
    checks = (
        ("min_success_rate", summary.get("success_rate"), lambda value, target: value >= target),
        (
            "min_output_throughput_tps",
            summary.get("output_throughput_tps"),
            lambda value, target: value >= target,
        ),
        ("max_ttft_p95_ms", summary.get("ttft_ms", {}).get("p95"), lambda value, target: value <= target),
        (
            "max_latency_p95_ms",
            summary.get("latency_ms", {}).get("p95"),
            lambda value, target: value <= target,
        ),
    )
    return all(
        target is None or (value is not None and predicate(float(value), float(target)))
        for key, value, predicate in checks
        if (target := criteria.get(key)) is not None
    )


def _quality(levels: list[dict[str, Any]], samples: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[str] = []
    cvs = [
        level["stability"]["throughput_cv_pct"]
        for level in levels
        if level["stability"]["throughput_cv_pct"] is not None
    ]
    max_cv = max(cvs, default=None)
    repetitions = min((level["repetitions"] for level in levels), default=0)
    if repetitions < 3:
        warnings.append("部分并发档少于 3 轮，均值与稳定性结论仅供参考。")
    if max_cv is not None and max_cv > 10:
        warnings.append(f"吞吐波动最高达到 {max_cv:.1f}%，建议延长预热或增加轮次。")
    estimated = sum(1 for sample in samples if sample.get("token_source") == "estimated")
    successful = sum(1 for sample in samples if sample.get("ok"))
    estimated_ratio = round(estimated / successful * 100, 2) if successful else 0.0
    if estimated_ratio:
        warnings.append(f"{estimated_ratio:.1f}% 的成功样本 token 数来自估算，吞吐结论精度会受影响。")
    if not levels:
        grade, label = "D", "数据不足"
    elif warnings and (repetitions < 3 or (max_cv or 0) > 15):
        grade, label = "C", "谨慎使用"
    elif warnings:
        grade, label = "B", "可用于方向判断"
    else:
        grade, label = "A", "结果稳定"
    return {
        "grade": grade,
        "label": label,
        "warnings": warnings,
        "max_throughput_cv_pct": max_cv,
        "estimated_token_ratio_pct": estimated_ratio,
        "sample_count": len(samples),
    }


def build_report_snapshot(
    runs: list[dict[str, Any]],
    samples_by_run: dict[str, list[dict[str, Any]]],
    criteria: dict[str, Any] | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not runs:
        raise ValueError("suite has no runs")
    criteria = criteria or {}
    environment = environment or {}
    items = [
        {"run": run, "summary": summarize(run, samples_by_run.get(run["id"], []))}
        for run in runs
    ]
    aggregated = sorted(
        aggregate_repetitions(items),
        key=lambda item: int(item["run"]["config"].get("concurrency") or 1),
    )
    levels: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for item in aggregated:
        summary = item["summary"]
        repeat = item.get("repeat_aggregation", {})
        concurrency = int(item["run"]["config"].get("concurrency") or 1)
        raw = [
            candidate
            for candidate in items
            if int(candidate["run"]["config"].get("concurrency") or 1) == concurrency
        ]
        level = {
            "concurrency": concurrency,
            "status": item["run"]["status"],
            "repetitions": len(raw),
            "run_ids": [candidate["run"]["id"] for candidate in raw],
            "summary": summary,
            "stability": {
                "throughput_cv_pct": repeat.get("output_throughput_cv_pct"),
                "latency_p95_cv_pct": repeat.get("latency_p95_cv_pct"),
                "ttft_p50_cv_pct": repeat.get("ttft_p50_cv_pct"),
            },
            "changes": {
                "throughput_pct": _change(
                    summary.get("output_throughput_tps"),
                    previous["summary"].get("output_throughput_tps") if previous else None,
                ),
                "latency_p95_pct": _change(
                    summary.get("latency_ms", {}).get("p95"),
                    previous["summary"].get("latency_ms", {}).get("p95") if previous else None,
                ),
            },
            "meets_criteria": _passes_criteria(summary, criteria),
            "raw_repetitions": [
                {
                    "run_id": candidate["run"]["id"],
                    "repetition": candidate["run"]["config"].get("repetition", 1),
                    "status": candidate["run"]["status"],
                    "output_throughput_tps": candidate["summary"].get("output_throughput_tps"),
                    "latency_p95_ms": candidate["summary"].get("latency_ms", {}).get("p95"),
                    "ttft_p95_ms": candidate["summary"].get("ttft_ms", {}).get("p95"),
                    "success_rate": candidate["summary"].get("success_rate"),
                }
                for candidate in raw
            ],
        }
        levels.append(level)
        previous = level

    saturation: dict[str, Any] = {"detected": False, "concurrency": None, "reason": None}
    for previous, current in zip(levels, levels[1:]):
        gain = current["changes"]["throughput_pct"]
        latency_growth = current["changes"]["latency_p95_pct"]
        success = current["summary"].get("success_rate", 0)
        if success < 99:
            saturation = {
                "detected": True,
                "concurrency": current["concurrency"],
                "reason": f"成功率在 C{current['concurrency']} 降至 {success:.2f}%",
            }
            break
        if gain is not None and latency_growth is not None and gain < 10 and latency_growth > 30:
            saturation = {
                "detected": True,
                "concurrency": current["concurrency"],
                "reason": f"吞吐仅增长 {gain:.1f}%，但 P95 延迟增加 {latency_growth:.1f}%",
            }
            break

    eligible = [level for level in levels if level["meets_criteria"]]
    if not any(value is not None for value in criteria.values()):
        eligible = [level for level in levels if level["summary"].get("success_rate", 0) >= 99]
    if saturation["detected"]:
        before = [level for level in eligible if level["concurrency"] < saturation["concurrency"]]
        if before:
            eligible = before
    candidates = eligible or levels
    recommended = max(candidates, key=lambda level: level["summary"].get("output_throughput_tps") or 0)
    peak = max(levels, key=lambda level: level["summary"].get("output_throughput_tps") or 0)

    all_samples = [sample for run_samples in samples_by_run.values() for sample in run_samples]
    errors = Counter(
        (sample.get("error") or f"HTTP {sample.get('status_code') or 'unknown'}")[:120]
        for sample in all_samples
        if not sample.get("ok")
    )
    conclusions = [
        {
            "tone": "positive",
            "title": f"推荐并发 C{recommended['concurrency']}",
            "body": (
                f"该档平均输出吞吐为 {recommended['summary'].get('output_throughput_tps', 0):.1f} tok/s，"
                f"P95 延迟 {recommended['summary'].get('latency_ms', {}).get('p95') or 0:.1f} ms，"
                f"成功率 {recommended['summary'].get('success_rate', 0):.2f}%。"
            ),
        },
        {
            "tone": "neutral" if saturation["detected"] else "positive",
            "title": "已识别饱和拐点" if saturation["detected"] else "测试范围内未出现明显饱和",
            "body": saturation["reason"] or "吞吐仍随并发增长，若资源允许可继续扩展更高并发档验证上限。",
        },
    ]
    if errors:
        error_count = sum(errors.values())
        conclusions.append(
            {
                "tone": "warning",
                "title": f"发现 {error_count} 个失败样本",
                "body": "主要错误：" + "；".join(f"{name} × {count}" for name, count in errors.most_common(3)),
            }
        )

    first = runs[0]
    config = first["config"]
    return {
        "schema_version": "1.0",
        "analysis_version": ANALYSIS_VERSION,
        "generated_at": time.time(),
        "suite": {
            "id": config.get("suite_id"),
            "name": config.get("suite_name") or first["name"],
            "framework": first["framework"],
            "model": first["model"],
            "endpoint": _redact_endpoint(first["endpoint"]),
            "run_count": len(runs),
            "completed_runs": sum(run["status"] == "completed" for run in runs),
            "concurrency_levels": [level["concurrency"] for level in levels],
            "repetitions": config.get("repetitions", 1),
            "requests_per_run": config.get("requests"),
            "max_tokens": config.get("max_tokens"),
            "prompt_fingerprint": config.get("prompt_fingerprint"),
        },
        "criteria": criteria,
        "environment": environment,
        "headline": {
            "recommended_concurrency": recommended["concurrency"],
            "recommended": recommended["summary"],
            "peak_concurrency": peak["concurrency"],
            "peak_output_throughput_tps": peak["summary"].get("output_throughput_tps"),
        },
        "saturation": saturation,
        "quality": _quality(levels, all_samples),
        "levels": levels,
        "errors": [{"message": message, "count": count} for message, count in errors.most_common()],
        "conclusions": conclusions,
    }


class ReportManager:
    def __init__(self, repository: Repository):
        self.repository = repository

    def maybe_generate(self, suite_id: str, expected_runs: int | None = None) -> dict[str, Any] | None:
        runs = self.repository.list_suite_runs(suite_id)
        if not runs:
            return None
        expected = expected_runs or max(
            (int(run["config"].get("suite_total_runs") or 0) for run in runs), default=0
        )
        if expected and len(runs) < expected:
            return None
        if any(run["status"] not in TERMINAL_STATUSES for run in runs):
            return None
        return self.generate(suite_id)

    def generate(
        self,
        suite_id: str,
        title: str | None = None,
        criteria: dict[str, Any] | None = None,
        environment: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        runs = self.repository.list_suite_runs(suite_id)
        if not runs:
            raise ValueError("suite not found")
        existing = self.repository.get_report_by_suite(suite_id)
        selected_criteria = criteria if criteria is not None else (existing or {}).get("criteria", {})
        selected_environment = environment if environment is not None else (existing or {}).get("environment", {})
        samples = {run["id"]: self.repository.list_samples(run["id"]) for run in runs}
        snapshot = build_report_snapshot(runs, samples, selected_criteria, selected_environment)
        suite_name = runs[0]["config"].get("suite_name") or runs[0]["name"]
        report_id = (existing or {}).get("id") or "rpt-" + hashlib.sha256(suite_id.encode()).hexdigest()[:12]
        return self.repository.upsert_report(
            report_id=report_id,
            suite_id=suite_id,
            title=title or (existing or {}).get("title") or f"{suite_name} 性能评估报告",
            analysis_version=ANALYSIS_VERSION,
            run_ids=[run["id"] for run in runs],
            criteria=selected_criteria,
            environment=selected_environment,
            snapshot=snapshot,
        )

    def safe_maybe_generate(self, suite_id: str, expected_runs: int | None = None) -> None:
        try:
            self.maybe_generate(suite_id, expected_runs)
        except Exception:
            logger.exception("automatic report generation failed for suite %s", suite_id)
