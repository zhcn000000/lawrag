from collections.abc import AsyncIterator, Awaitable, Callable
from logging import getLogger
from typing import Any

from anyio import create_memory_object_stream
from anyio.streams.memory import MemoryObjectSendStream
from asyncer import create_task_group
from pydantic_ai.retries import RetryConfig
from pydantic_evals import Case
from pydantic_evals.lifecycle import CaseLifecycle
from pydantic_evals.reporting import ReportCase, ReportCaseFailure
from tenacity import stop_after_attempt

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
                    evaluation_note=result.assertions["llm_judge"].reason or "",
                    success=result.assertions["llm_judge"].value,
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
                max_concurrency=5,
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
