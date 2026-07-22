import statistics
from collections.abc import AsyncIterator, Awaitable, Callable
from logging import getLogger
from pathlib import Path
from typing import Any

import matplotlib
from anyio import create_memory_object_stream
from anyio.streams.memory import MemoryObjectSendStream
from asyncer import create_task_group
from pydantic_ai.retries import RetryConfig
from pydantic_evals import Case
from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting import ReportCase, ReportCaseFailure
from tenacity import stop_after_attempt

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lawrag.chat.agent import agent, get_model_settings
from lawrag.chat.struct import ModelDeps

from .dataset import LawRagCase, LawRagCaseFailure, LawRagCaseReport, get_dataset

logger = getLogger(__name__)


def get_task(offline: bool = False) -> Callable[[str], Awaitable[str]]:
    async def task(text: str) -> str:
        deps = ModelDeps()
        deps.select_toolset = deps.select_toolset - {"code_toolkit"}
        if offline:
            deps.select_toolset = deps.select_toolset - {"web_toolkit"}
        result = await agent.run(text, deps=deps, model_settings=get_model_settings(thinking=True))
        logger.debug("Evaluating case: %s Model output: %s", text, result.output)
        answer = result.output
        retries = 0
        while (
            ("<tool_call>" in answer and "</tool_call>" in answer)
            or ("<tool_code>" in answer and "</tool_code>" in answer)
        ) and retries < 3:
            logger.warning("Model Tool Call Failed, Attempt %s", retries + 1)
            message_history = result.all_messages()
            result = await agent.run(
                "工具调用未被正确解析，请使用标准工具调用格式，继续",
                deps=deps,
                message_history=message_history,
                model_settings=get_model_settings(thinking=True),
            )
            answer = result.output
            logger.debug("Evaluating case: %s Retries: %s Model output: %s", text, retries, answer)
            retries += 1
        return answer

    return task


class LawRagCaseLifecycle(CaseLifecycle[str, str, Any]):
    def __init__(
        self,
        case: Case[str, str, Any],
        send_stream: MemoryObjectSendStream[LawRagCaseReport | LawRagCaseFailure],
    ) -> None:
        self._case = case
        self._send_stream = send_stream

    async def teardown(
        self,
        result: ReportCase[str, str, Any] | ReportCaseFailure[str, str, Any] | None,
    ) -> None:
        logger.debug("Teardown for case %s Result: %s", self._case.name, result)
        if isinstance(result, ReportCaseFailure):
            await self._send_stream.send(
                LawRagCaseFailure(
                    name=result.name,
                    question=result.inputs,
                    expected_answer=result.expected_output or "",
                    error_message=result.error_message,
                    success=False,
                ),
            )
        elif isinstance(result, ReportCase):
            await self._send_stream.send(
                LawRagCaseReport(
                    name=result.name,
                    question=result.inputs,
                    expected_answer=result.expected_output or "",
                    model_output=result.output,
                    evaluation_note=result.assertions["llm_judge_assertion"].reason or "",
                    success=result.assertions["llm_judge_assertion"].value,
                    score=result.scores["llm_judge_score"].value,
                ),
            )


def get_lifecycle(
    send_stream: MemoryObjectSendStream[LawRagCaseReport | LawRagCaseFailure],
) -> Callable[[Case[str, str, Any]], LawRagCaseLifecycle]:
    def lifecycle(case: Case[str, str, Any]) -> LawRagCaseLifecycle:
        return LawRagCaseLifecycle(case=case, send_stream=send_stream)

    return lifecycle


async def evaluate_stream(
    cases: list[LawRagCase],
    offline: bool = False,
) -> AsyncIterator[LawRagCaseReport | LawRagCaseFailure]:
    send_stream, receive_stream = create_memory_object_stream[LawRagCaseReport | LawRagCaseFailure](max_buffer_size=10)

    dataset_cases = [Case(name=case.name, inputs=case.question, expected_output=case.expected_answer) for case in cases]
    logger.info("Starting evaluation for %d cases", len(dataset_cases))
    dataset = get_dataset(cases=dataset_cases)
    task = get_task(offline=offline)

    async def run_eval_and_close():
        try:
            await dataset.evaluate(
                task=task,
                max_concurrency=1,
                lifecycle=get_lifecycle(send_stream),
                retry_task=RetryConfig(stop=stop_after_attempt(3)),
                retry_evaluators=RetryConfig(stop=stop_after_attempt(3)),
            )
        finally:
            await send_stream.aclose()

    async with create_task_group() as tg:
        tg.soonify(run_eval_and_close)()
        async with receive_stream:
            async for report in receive_stream:
                yield report  # ruff:ignore[yield-in-context-manager-in-async-generator]


async def evaluate(
    cases: list[LawRagCase],
    start: int = 0,
    end: int = -1,
    offline: bool = False,
) -> list[LawRagCaseReport | LawRagCaseFailure]:
    reports: list[LawRagCaseReport | LawRagCaseFailure] = []
    eval_cases = cases if end < 0 else cases[start:end]
    async for report in evaluate_stream(cases=eval_cases, offline=offline):
        reports.append(report)
    return reports


def plot_score_stats(
    reports: list[LawRagCaseReport | LawRagCaseFailure],
    output_path: Path | str = "lawrag_eval_stats.png",
) -> None:
    scores = [r.score for r in reports if isinstance(r, LawRagCaseReport)]
    total = len(reports)
    passed = sum(1 for r in reports if r.success)
    failed = total - passed

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle("LawRAG Eval Score Statistics", fontsize=14, fontweight="bold")

    if scores:
        ax = axes[0]
        bins = list(range(12))
        ax.hist(scores, bins=bins, color="steelblue", edgecolor="white", alpha=0.85, align="left")
        mean_score = statistics.mean(scores)
        median_score = int(statistics.median(scores))
        ax.axvline(mean_score, color="red", linestyle="--", linewidth=1.5, label=f"Mean: {mean_score:.1f}")
        ax.axvline(median_score, color="orange", linestyle="--", linewidth=1.5, label=f"Median: {median_score}")
        ax.set_xlabel("Score (0-10)")
        ax.set_ylabel("Count")
        ax.set_xticks(range(11))
        ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
        ax.set_title(f"Score Distribution (n={len(scores)})")
        ax.legend(fontsize=8)

        ax = axes[1]
        stats_text = "\n".join([
            f"Count: {len(scores)}/{total}",
            f"Mean: {mean_score:.1f}",
            f"Median: {median_score}",
            f"Std: {statistics.stdev(scores):.1f}" if len(scores) > 1 else "Std: N/A",
            f"Min: {int(min(scores))}",
            f"Max: {int(max(scores))}",
        ])
        ax.axis("off")
        ax.text(
            0.5,
            0.5,
            stats_text,
            transform=ax.transAxes,
            fontsize=12,
            fontfamily="monospace",
            verticalalignment="center",
            horizontalalignment="center",
            bbox={"boxstyle": "round", "facecolor": "lightgray", "alpha": 0.5},
        )
    else:
        axes[0].axis("off")
        axes[1].text(
            0.5,
            0.5,
            "No scores available",
            transform=axes[1].transAxes,
            fontsize=14,
            ha="center",
            va="center",
        )

    ax = axes[2]
    colors = ["#2ecc71", "#e74c3c"]
    bars = ax.bar(["Pass", "Fail"], [passed, failed], color=colors, edgecolor="white")
    ax.set_ylabel("Count")
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.set_title(f"Pass/Fail ({total} total)")
    for bar, count in zip(bars, [passed, failed], strict=False):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(1, total * 0.01),
            str(count),
            ha="center",
            fontsize=11,
            fontweight="bold",
        )
    rate = passed / total * 100 if total else 0
    ax.text(
        0.5,
        0.85,
        f"Pass Rate: {rate:.1f}%",
        transform=ax.transAxes,
        fontsize=12,
        fontweight="bold",
        ha="center",
        va="center",
    )

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Score statistics plot saved to: %s", output_path)
