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
但是仍然可以给出完整性，准确性等其他方面的意见，并给出0-10的评分。

评分标准（0-10）：
- 0-3：完全错误或严重误导，未触及预期答案的核心法律依据
- 4-6：部分正确但存在明显遗漏、冗余或不准确之处，核心要点未完整覆盖
- 7-8：基本正确，覆盖了预期答案的主要法律依据，但略有不完整或不精确的表达
- 9：准确全面，核心法律依据引用正确、回答完整且无误导。
- 10：不仅准确全面，还提供了额外有价值的法律分析或见解，超出预期答案的深度和广度。

**使用中文输出评测结果**""",
        include_input=True,
        include_expected_output=True,
        assertion=OutputConfig(
            evaluation_name="llm_judge_assertion",
            include_reason=True,
        ),
        score=OutputConfig(
            evaluation_name="llm_judge_score",
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
    score: int
    success: bool


class LawRagCaseFailure(BaseModel):
    type: Literal["failure"] = "failure"
    name: str
    question: str
    expected_answer: str
    error_message: str
    success: Literal[False] = False
