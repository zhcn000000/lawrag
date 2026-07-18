"""law_index 测试 (需要运行中的 PostgreSQL 数据库)
使用标记: pytest -m "not db" 跳过数据库测试, pytest -m "db" 仅运行数据库测试
"""

import pytest

from lawrag.database.law_index import LawIndexManager

TEST_LAW_ID = "test-clear-content"


@pytest.mark.db
async def test_clear_content() -> None:
    lm = LawIndexManager()
    await lm.aupsert(law_id=TEST_LAW_ID, law_name="测试清除法", law_type="法律", status="有效")
    await lm.aset_raw(TEST_LAW_ID, "第一条 测试内容")
    await lm.aset_structured(TEST_LAW_ID, {"title": "测试清除法"})
    entry = await lm.aget(TEST_LAW_ID)
    assert entry is not None
    assert entry["raw"] is not None
    assert entry["structured"] is not None

    law_name = await lm.aclear_content(entry["id"])
    assert law_name == "测试清除法"

    entry = await lm.aget(TEST_LAW_ID)
    assert entry is not None
    assert entry["raw"] is None
    assert entry["structured"] is None

    await lm.adelete(TEST_LAW_ID)


@pytest.mark.db
async def test_clear_content_rejects_imported(setup_real_db) -> None:
    lm = LawIndexManager()
    entries = [e for e in await lm.afind_all() if e["law_name"] == "反分裂国家法"]
    assert entries
    with pytest.raises(ValueError, match="已导入节点"):
        await lm.aclear_content(entries[0]["id"])
