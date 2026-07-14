"""pageindex 测试 (需要运行中的 PostgreSQL 数据库)
使用标记: pytest -m "not db" 跳过数据库测试, pytest -m "db" 仅运行数据库测试
"""

import json

import pytest
from anyio import NamedTemporaryFile as AsyncNamedTemporaryFile
from anyio import Path as AsyncPath

from lawrag.database.document import DocumentStore
from lawrag.database.pageindex import LawPageIndex
from lawrag.environments import settings

STRUCTURED_LAWS_DIR = settings.DATA_ROOT / "structured_laws"

TEST_JSON = {
    "law_name": "中华人民共和国测试法",
    "preamble": None,
    "parts": [
        {
            "number": 1,
            "title": "总则",
            "chapters": [
                {
                    "number": 1,
                    "title": "基本规定",
                    "articles": [
                        {"number": 1, "content": "为了保护测试主体的合法权益，根据宪法，制定本法。"},
                        {"number": 2, "content": "测试法调整测试关系。"},
                    ],
                },
            ],
        },
        {
            "number": 2,
            "title": "权利",
            "chapters": [
                {
                    "number": 2,
                    "title": "权利与原则",
                    "sections": [
                        {
                            "number": 1,
                            "title": "权利",
                            "articles": [{"number": 3, "content": "测试主体依法享有测试权利。"}],
                        },
                        {
                            "number": 2,
                            "title": "原则",
                            "articles": [
                                {"number": 4, "content": "测试活动应当遵循自愿原则。"},
                                {"number": 5, "content": "测试活动应当遵循公平原则。"},
                            ],
                        },
                    ],
                },
            ],
        },
    ],
}


@pytest.fixture
async def test_law_file() -> AsyncPath:
    """创建临时结构化测试法条 JSON 文件 (文件名即法律名)"""
    async with AsyncNamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        await f.write(json.dumps(TEST_JSON, ensure_ascii=False))
        return AsyncPath(f.wrapped.name)


@pytest.mark.db
async def test_import_and_retrieve(test_law_file: AsyncPath) -> None:
    pageindex = LawPageIndex()
    docstore = DocumentStore()
    law_name = test_law_file.stem

    result = await docstore.aimport_file(file_path=test_law_file)
    assert result["status"] == "ok"
    assert result["count"] == 5

    laws = await pageindex.afind_laws()
    laws_dict = {entry["law_name"]: entry for entry in laws}
    assert law_name in laws_dict
    assert laws_dict[law_name]["article_count"] == 5

    article = await pageindex.aget_by_law_article(law_name=law_name, article_number=3)
    assert article is not None
    assert "测试权利" in article["content"]
    assert article["chapter_title"] == "权利与原则"
    assert article["section_title"] == "权利"

    article1 = await pageindex.aget_by_law_article(law_name=law_name, article_number=1)
    assert article1 is not None
    assert article1["chapter_title"] == "基本规定"
    assert article1["section_title"] is None

    articles = await pageindex.aget_law_articles(law_name=law_name, start=2, end=4)
    assert len(articles) == 3

    toc = await pageindex.aget_law_toc(law_name=law_name)
    assert [c["title"] for c in toc] == ["总则", "权利"]
    assert all(c["node_type"] == "part" for c in toc)
    assert all("path" in c for c in toc)
    rights_part = toc[1]
    assert rights_part["children"][0]["title"] == "权利与原则"
    assert [s["title"] for s in rights_part["children"][0]["children"]] == ["权利", "原则"]

    top = await pageindex.abrowse_law(law_name=law_name, path="law0")
    assert top["node_type"] == "law"
    assert [c["node_type"] for c in top["children"]] == ["part", "part"]
    part2_path = top["children"][1]["path"]

    part2 = await pageindex.abrowse_law(law_name=law_name, path=part2_path)
    assert [c["node_type"] for c in part2["children"]] == ["chapter"]
    chap_path = part2["children"][0]["path"]

    chap = await pageindex.abrowse_law(law_name=law_name, path=chap_path)
    assert [c["node_type"] for c in chap["children"]] == ["section", "section"]
    assert all(not c["is_leaf"] for c in chap["children"])
    sec2_path = chap["children"][1]["path"]

    sec2 = await pageindex.abrowse_law(law_name=law_name, path=sec2_path)
    assert {c["number"] for c in sec2["children"]} == {4, 5}
    assert all(c["is_leaf"] for c in sec2["children"])

    # 重复导入应保持幂等 (delete-then-insert + (law_name, path) 唯一约束)
    await docstore.aimport_file(file_path=test_law_file)
    laws_again = {e["law_name"]: e for e in await pageindex.afind_laws()}
    assert laws_again[law_name]["article_count"] == 5

    count = await docstore.adelete_law(law_name)
    assert count == 5

    laws2 = await pageindex.afind_laws()
    assert law_name not in {entry["law_name"] for entry in laws2}

    await test_law_file.unlink(missing_ok=True)


@pytest.mark.db
async def test_import_dir() -> None:
    """测试批量导入目录 (JSON 格式)"""
    from anyio import TemporaryDirectory as AsyncTemporaryDirectory

    docstore = DocumentStore()

    async with AsyncTemporaryDirectory() as tmpdir:
        tmp_dir = AsyncPath(tmpdir)
        await (tmp_dir / "测试法A.json").write_text(
            json.dumps(
                {
                    "chapters": [
                        {
                            "number": 1,
                            "title": "总则",
                            "articles": [
                                {"number": 1, "content": "测试A第一条。"},
                                {"number": 2, "content": "测试A第二条。"},
                            ],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        await (tmp_dir / "测试法B.json").write_text(
            json.dumps({"articles": [{"number": 1, "content": "测试B第一条。"}]}, ensure_ascii=False),
            encoding="utf-8",
        )

        results = await docstore.aimport_from_dir(dir_path=tmpdir)
        assert len(results) == 2
        assert all(r["status"] == "ok" for r in results)
        assert sum(r["count"] for r in results) == 3

        await docstore.adelete_law("测试法A")
        await docstore.adelete_law("测试法B")


# ── 以下测试使用 session 级 setup_real_db 导入的真实法律 ──


@pytest.mark.db
async def test_real_law_import_and_list(setup_real_db) -> None:
    pageindex = LawPageIndex()
    laws = await pageindex.afind_laws()
    laws_dict = {e["law_name"]: e for e in laws}
    assert "反分裂国家法" in laws_dict
    assert laws_dict["反分裂国家法"]["article_count"] == 10


@pytest.mark.db
async def test_real_law_articles(setup_real_db) -> None:
    pageindex = LawPageIndex()
    articles = await pageindex.aget_law_articles(law_name="反分裂国家法")
    assert len(articles) == 10
    assert all(a["content"] for a in articles)
    assert {a["article_number"] for a in articles} == set(range(1, 11))


@pytest.mark.db
async def test_real_law_single_article(setup_real_db) -> None:
    pageindex = LawPageIndex()
    article = await pageindex.aget_by_law_article(law_name="反分裂国家法", article_number=1)
    assert article is not None
    assert "台独" in article["content"]
    assert article["chapter_title"] is None  # 无章/节结构
    assert article["section_title"] is None


@pytest.mark.db
async def test_real_law_toc(setup_real_db) -> None:
    pageindex = LawPageIndex()
    toc = await pageindex.aget_law_toc(law_name="反分裂国家法")
    assert isinstance(toc, list)
    assert len(toc) == 0  # 无编/章/节, 仅顶层条文


@pytest.mark.db
async def test_real_law_browse(setup_real_db) -> None:
    pageindex = LawPageIndex()
    top = await pageindex.abrowse_law(law_name="反分裂国家法", path="law0")
    assert top["node_type"] == "law"
    assert len(top["children"]) == 10
    assert all(c["is_leaf"] for c in top["children"])
    assert all(c["node_type"] == "article" for c in top["children"])


@pytest.mark.db
async def test_get_node_by_path(setup_real_db) -> None:
    pageindex = LawPageIndex()
    articles = await pageindex.aget_law_articles(law_name="反分裂国家法", limit=1)
    article_num = articles[0]["article_number"]
    node = await pageindex.aget_node_by_path(law_name="反分裂国家法", path=f"law0/a{article_num}")
    assert node["node_type"] == "article"
    assert node["content"] == articles[0]["content"]


@pytest.mark.db
async def test_alist_laws_regex(setup_real_db) -> None:
    """测试按名称正则过滤法律列表"""
    pageindex = LawPageIndex()
    laws = await pageindex.afind_laws(regex="反分裂")
    assert len(laws) > 0
    assert all("反分裂" in e["law_name"] for e in laws)
