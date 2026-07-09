from lawrag.chat.model import agent
from lawrag.chat.struct import ModelDeps

from .dataset import LawRagCaseReport, LawRagFailureReport, get_dataset


async def task(text: str) -> str:
    result = await agent.run(text, deps=ModelDeps())
    return result.output


async def evaluate(max_cases: int | None = None) -> list[LawRagCaseReport | LawRagFailureReport]:
    dataset = get_dataset(max_cases=max_cases)
    results = await dataset.evaluate(task=task)
    reports: list[LawRagCaseReport | LawRagFailureReport] = []
    for case in results.cases:
        report = LawRagCaseReport(
            question=case.inputs,
            expected_answer=case.expected_output or "",
            model_output=case.output,
            evaluation_note=case.assertions["llm_judge"].reason or "",
            success=case.assertions["llm_judge"].value,
        )
        reports.append(report)
    for case in results.failures:
        report = LawRagFailureReport(
            question=case.inputs,
            expected_answer=case.expected_output or "",
            error_message=case.error_message,
            success=False,
        )
        reports.append(report)
    return reports
