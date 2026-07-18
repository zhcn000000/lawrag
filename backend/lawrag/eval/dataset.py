from typing import Any, Literal

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import LLMJudge, OutputConfig

from lawrag.chat.agent import get_model_settings, model

evaluators = [
    LLMJudge(
        model=model,
        model_settings=get_model_settings(thinking=False, temperature=0.2),
        rubric="""**使用中文输出评测结果**，将Agent模型的输出与预期答案对比，是否回答全面，甚至比预期答案更好等
可以包括准确性，是否冗余，是否存在误导等多角度不同方面。并给出原因，其中，回答出了预期答案的部分或不比预期答案差即为正确，
但是仍然可以给出完整性，准确性等其他方面的意见。**使用中文输出评测结果**""",
        include_input=True,
        include_expected_output=True,
        assertion=OutputConfig(
            evaluation_name="llm_judge",
            include_reason=True,
        ),
    ),
]


def get_dataset(cases: list[Case[str, str, Any]]) -> Dataset[str, str, Any]:
    return Dataset(
        name="法律rag准确性评估",
        cases=cases,
        evaluators=evaluators,
    )


class LawRagCase(BaseModel):
    name: str
    question: str
    expected_answer: str


class LawRagCaseReport(BaseModel):
    type: Literal["report"] = "report"
    name: str
    question: str
    expected_answer: str
    model_output: str
    evaluation_note: str
    success: bool


class LawRagCaseFailure(BaseModel):
    type: Literal["failure"] = "failure"
    name: str
    question: str
    expected_answer: str
    error_message: str
    success: Literal[False] = False
