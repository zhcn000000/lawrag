"""评估流程测试 (需要运行中的 PostgreSQL + LLM 服务)

使用标记: pytest -m "not db" 跳过, pytest -m "db" 运行
"""

import pytest
from pydantic import TypeAdapter

from lawrag.environments import find_project_directory
from lawrag.eval.dataset import LawRagCase, LawRagCaseReport
from lawrag.eval.eval import evaluate

MAX_CASES = 5


@pytest.mark.db
async def test_evaluate_first_five_cases() -> None:
    """从 examples/case.json 取前五条样本跑完整评估流程"""
    case_path = find_project_directory() / "examples" / "case.json"
    cases = TypeAdapter(list[LawRagCase]).validate_json(case_path.read_bytes())
    assert len(cases) >= MAX_CASES

    reports = await evaluate(cases, end=MAX_CASES, offline=True)

    assert len(reports) == MAX_CASES
    expected_names = {c.name for c in cases[:MAX_CASES]}
    assert {r.name for r in reports} == expected_names
    for r in reports:
        assert r.question
        assert r.expected_answer
        if isinstance(r, LawRagCaseReport):
            assert r.model_output
            assert r.evaluation_note
