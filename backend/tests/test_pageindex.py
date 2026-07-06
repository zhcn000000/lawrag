"""pageindex 测试 (需要运行中的 PostgreSQL 数据库)
使用标记: pytest -m "not db" 跳过数据库测试, pytest -m "db" 仅运行数据库测试
"""

import pytest
from anyio import NamedTemporaryFile as AsyncNamedTemporaryFile
from anyio import Path as AsyncPath
from anyio import TemporaryDirectory as AsyncTemporaryDirectory

from lawrag.database.pageindex import LawPageIndex

TEST_TXT_CONTENT = (
    "《中华人民共和国测试法》第一条规定，为了保护测试主体的合法权益，根据宪法，制定本法。\n"
    "《中华人民共和国测试法》第二条规定，测试法调整测试关系。\n"
    "《中华人民共和国测试法》第三条规定，测试主体依法享有测试权利。\n"
    "《中华人民共和国测试法》第四条规定，测试活动应当遵循自愿原则。\n"
    "《中华人民共和国测试法》第五条规定，测试活动应当遵循公平原则。\n"
)


@pytest.fixture
async def test_law_file() -> AsyncPath:
    """创建临时测试法条文件"""
    async with AsyncNamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    ) as f:
        await f.write(TEST_TXT_CONTENT)
        return AsyncPath(f.wrapped.name)


@pytest.mark.db
async def test_import_and_retrieve(test_law_file: AsyncPath) -> None:

    pageindex = LawPageIndex()

    # Import
    result = await pageindex.aimport_file(file_path=test_law_file)
    assert result["status"] == "ok"
    assert result["count"] == 5

    # List laws
    laws = await pageindex.alist_laws()
    laws_dict = {entry["law_name"]: entry for entry in laws}
    assert "中华人民共和国测试法" in laws_dict
    assert laws_dict["中华人民共和国测试法"]["article_count"] == 5

    # Get single article
    article = await pageindex.aget_by_law_article(
        law_name="中华人民共和国测试法",
        article_number=3,
    )
    assert article is not None
    assert "测试权利" in article["content"]

    # Get article range
    articles = await pageindex.aget_law_articles(
        law_name="中华人民共和国测试法",
        start=2,
        end=4,
    )
    assert len(articles) == 3

    # Search articles
    results = await pageindex.asearch_articles(
        law_name="中华人民共和国测试法",
        query="自愿",
    )
    assert len(results) == 1
    assert results[0]["article_number"] == 4

    # Delete law
    count = await pageindex.adelete_law("中华人民共和国测试法")
    assert count == 5

    # Verify empty
    laws2 = await pageindex.alist_laws()
    laws2_dict = {entry["law_name"]: entry for entry in laws2}
    assert "中华人民共和国测试法" not in laws2_dict

    await test_law_file.unlink(missing_ok=True)


@pytest.mark.db
async def test_import_dir() -> None:
    """测试批量导入目录"""

    pageindex = LawPageIndex()

    async with AsyncTemporaryDirectory() as tmpdir:
        # Create test files
        tmp_dir = AsyncPath(tmpdir)
        file1 = tmp_dir / "测试法A.txt"
        file2 = tmp_dir / "测试法B.txt"
        await file1.write_text(
            "《中华人民共和国测试法A》第一条规定，测试A第一条。\n《中华人民共和国测试法A》第二条规定，测试A第二条。\n",
            encoding="utf-8",
        )
        await file2.write_text(
            "《中华人民共和国测试法B》第一条规定，测试B第一条。\n",
            encoding="utf-8",
        )

        results = await pageindex.aimport_from_dir(dir_path=tmpdir)
        assert len(results) == 2
        assert results[0]["status"] == "ok"
        assert results[1]["status"] == "ok"

        total = sum(r["count"] for r in results)
        assert total == 3

        # Cleanup
        await pageindex.adelete_law("中华人民共和国测试法A")
        await pageindex.adelete_law("中华人民共和国测试法B")
