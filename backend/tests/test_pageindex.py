"""pageindex 测试 (需要运行中的 PostgreSQL 数据库)
使用标记: pytest -m "not db" 跳过数据库测试, pytest -m "db" 仅运行数据库测试
"""

import pytest
from anyio import NamedTemporaryFile as AsyncNamedTemporaryFile
from anyio import Path as AsyncPath
from anyio import TemporaryDirectory as AsyncTemporaryDirectory

from lawrag.database.pageindex import LawPageIndex

TEST_TXT_CONTENT = "\n".join([
    "=" * 60,
    "中华人民共和国测试法",
    "=" * 60,
    "",
    "第一编  总则",
    "",
    "第一章  基本规定",
    "",
    "    第一条  为了保护测试主体的合法权益，根据宪法，制定本法。",
    "",
    "    第二条  测试法调整测试关系。",
    "",
    "第二编  权利",
    "",
    "第二章  权利与原则",
    "",
    "    第一节  权利",
    "",
    "    第三条  测试主体依法享有测试权利。",
    "",
    "    第二节  原则",
    "",
    "    第四条  测试活动应当遵循自愿原则。",
    "",
    "    第五条  测试活动应当遵循公平原则。",
    "",
])


@pytest.fixture
async def test_law_file() -> AsyncPath:
    """创建临时结构化测试法条文件 (文件名即法律名)"""
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
    law_name = test_law_file.stem

    # Import
    result = await pageindex.aimport_file(file_path=test_law_file)
    assert result["status"] == "ok"
    assert result["count"] == 5

    # List laws (仅统计 article 节点)
    laws = await pageindex.alist_laws()
    laws_dict = {entry["law_name"]: entry for entry in laws}
    assert law_name in laws_dict
    assert laws_dict[law_name]["article_count"] == 5

    # Get single article + 多级 page index
    article = await pageindex.aget_by_law_article(law_name=law_name, article_number=3)
    assert article is not None
    assert "测试权利" in article["content"]
    assert article["chapter_title"] == "权利与原则"
    assert article["section_title"] == "权利"

    # 第一条 → 第一章 基本规定 (第一编 总则 下), 无 节
    article1 = await pageindex.aget_by_law_article(law_name=law_name, article_number=1)
    assert article1 is not None
    assert article1["chapter_title"] == "基本规定"
    assert article1["section_title"] is None

    # Get article range
    articles = await pageindex.aget_law_articles(law_name=law_name, start=2, end=4)
    assert len(articles) == 3

    # Search articles
    results = await pageindex.asearch_articles(law_name=law_name, query="自愿")
    assert len(results) == 1
    assert results[0]["article_number"] == 4

    # TOC: 顶层为编, 编下含章, 章下含节
    toc = await pageindex.aget_law_toc(law_name=law_name)
    assert [c["title"] for c in toc] == ["总则", "权利"]
    assert all(c["node_type"] == "part" for c in toc)
    rights_part = toc[1]
    assert rights_part["children"][0]["title"] == "权利与原则"
    assert [s["title"] for s in rights_part["children"][0]["children"]] == ["权利", "原则"]

    # Articles under chapter (含节)
    under = await pageindex.aget_articles_under_chapter(law_name=law_name, chapter_title="权利与原则")
    assert {a["article_number"] for a in under} == {3, 4, 5}

    # 重复导入应保持幂等 (delete-then-insert + (law_name, path) 唯一约束)
    await pageindex.aimport_file(file_path=test_law_file)
    laws_again = {e["law_name"]: e for e in await pageindex.alist_laws()}
    assert laws_again[law_name]["article_count"] == 5

    # Delete law
    count = await pageindex.adelete_law(law_name)
    assert count == 5

    # Verify empty
    laws2 = await pageindex.alist_laws()
    assert law_name not in {entry["law_name"] for entry in laws2}

    await test_law_file.unlink(missing_ok=True)


@pytest.mark.db
async def test_import_dir() -> None:
    """测试批量导入目录"""
    pageindex = LawPageIndex()

    async with AsyncTemporaryDirectory() as tmpdir:
        tmp_dir = AsyncPath(tmpdir)
        await (tmp_dir / "测试法A.txt").write_text(
            "\n".join([
                "第一章  总则",
                "",
                "    第一条  测试A第一条。",
                "    第二条  测试A第二条。",
            ]),
            encoding="utf-8",
        )
        await (tmp_dir / "测试法B.txt").write_text(
            "第一条  测试B第一条。\n",
            encoding="utf-8",
        )

        results = await pageindex.aimport_from_dir(dir_path=tmpdir)
        assert len(results) == 2
        assert all(r["status"] == "ok" for r in results)
        assert sum(r["count"] for r in results) == 3

        await pageindex.adelete_law("测试法A")
        await pageindex.adelete_law("测试法B")
