"""pageindex 测试 (需要运行中的 PostgreSQL 数据库)
使用标记: pytest -m "not db" 跳过数据库测试, pytest -m "db" 仅运行数据库测试
"""

import pytest

from lawrag.database.pageindex import LawPageIndex


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
