from pydantic_evals import Case

from lawrag.chat.model import agent
from lawrag.chat.struct import ModelDeps

from .dataset import LawRagCase, LawRagCaseFailure, LawRagCaseReport, get_dataset


async def task(text: str) -> str:
    result = await agent.run(text, deps=ModelDeps())
    return result.output


async def evaluate(cases: list[LawRagCase], max_cases: int | None = None) -> list[LawRagCaseReport | LawRagCaseFailure]:
    if cases is not None:
        dataset_cases = [
            Case(
                name=case.name,
                inputs=case.question,
                expected_output=case.expected_answer,
            )
            for case in cases
        ]
    else:
        dataset_cases = None
    dataset = get_dataset(cases=dataset_cases, max_cases=max_cases)
    results = await dataset.evaluate(task=task)
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
