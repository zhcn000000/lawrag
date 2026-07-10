from typing import Any, Literal

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import LLMJudge, OutputConfig

from lawrag.chat.model import get_model_settings, model

evaluators = [
    LLMJudge(
        model=model,
        model_settings=get_model_settings(thinking=False, temperature=0.2),
        rubric="**使用中文输出评测结果**，将Agent模型的输出与预期答案对比，是否回答全面，可以包括准确性，是否冗余，是否存在误导等多角度不同方面。并给出原因，**使用中文输出评测结果**",
        include_input=True,
        include_expected_output=True,
        assertion=OutputConfig(
            evaluation_name="llm_judge",
            include_reason=True,
        ),
    ),
]


def get_dataset(cases: list[Case[str, str, Any]], max_cases: int | None = None):
    if max_cases is None:
        max_cases = len(cases)
    return Dataset(
        name="法律rag准确性评估",
        cases=cases[:max_cases],
        evaluators=evaluators,
    )


class LawRagCase(BaseModel):
    name: str
    question: str
    expected_answer: str


class LawRagCaseReport(BaseModel):
    name: str
    question: str
    expected_answer: str
    model_output: str
    evaluation_note: str
    success: bool


class LawRagCaseFailure(BaseModel):
    name: str
    question: str
    expected_answer: str
    error_message: str
    success: Literal[False] = False
