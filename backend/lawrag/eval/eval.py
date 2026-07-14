from collections.abc import Awaitable, Callable

from pydantic_evals import Case

from lawrag.chat.model import agent
from lawrag.chat.struct import ModelDeps

from .dataset import LawRagCase, LawRagCaseFailure, LawRagCaseReport, get_dataset


def get_task(offline: bool = False) -> Callable[[str], Awaitable[str]]:
    async def task(text: str) -> str:
        deps = ModelDeps()
        if offline:
            deps.select_toolset = deps.select_toolset - {"web_toolkit"}
        result = await agent.run(text, deps=deps)
        return result.output

    return task


async def evaluate(
    cases: list[LawRagCase],
    max_cases: int | None = None,
    offline: bool = False,
) -> list[LawRagCaseReport | LawRagCaseFailure]:
    dataset_cases = [
        Case(
            name=case.name,
            inputs=case.question,
            expected_output=case.expected_answer,
        )
        for case in cases
    ]

    dataset = get_dataset(cases=dataset_cases, max_cases=max_cases)
    task = get_task(offline=offline)
    results = await dataset.evaluate(task=task, max_concurrency=1)
    reports: list[LawRagCaseReport | LawRagCaseFailure] = []
    for case in results.cases:
        report = LawRagCaseReport(
            name=case.name,
            question=case.inputs,
            expected_answer=case.expected_output or "",
            model_output=case.output,
            evaluation_note=case.assertions["llm_judge"].reason or "",
            success=case.assertions["llm_judge"].value,
        )
        reports.append(report)
    for case in results.failures:
        report = LawRagCaseFailure(
            name=case.name,
            question=case.inputs,
            expected_answer=case.expected_output or "",
            error_message=case.error_message,
            success=False,
        )
        reports.append(report)
    return reports
