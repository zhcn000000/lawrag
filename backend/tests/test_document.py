"""document 测试 (需要运行中的 PostgreSQL + LLM 服务)

使用标记: pytest -m "not db" 跳过, pytest -m "db" 运行
"""

from uuid import UUID

import pytest

from lawrag.database.document import DocumentStore
from lawrag.database.pageindex import LawPageIndex


@pytest.mark.db
async def test_batch_load_single_text(setup_real_db) -> None:
    """单条文本批量嵌入 (asplit → aembed → atokenize → insert)"""
    law_name = "反分裂国家法"
    pageindex = LawPageIndex()
    articles = await pageindex.aget_law_articles(law_name=law_name, limit=1)
    assert articles

    article = articles[0]
    docstore = DocumentStore()

    count = await docstore.abatch_load_from_texts(
        texts=[(article["content"], UUID(article["id"]), law_name)],
    )
    assert count > 0

    await docstore.adelete_article_chunks(UUID(article["id"]))


@pytest.mark.db
async def test_batch_load_multiple_texts(setup_real_db) -> None:
    """多条文本批量嵌入"""
    law_name = "反分裂国家法"
    pageindex = LawPageIndex()
    articles = await pageindex.aget_law_articles(law_name=law_name, limit=3)
    assert len(articles) >= 2

    texts = [(a["content"], UUID(a["id"]), law_name) for a in articles]

    docstore = DocumentStore()
    count = await docstore.abatch_load_from_texts(texts=texts)
    assert count > 0

    for a in articles:
        await docstore.adelete_article_chunks(UUID(a["id"]))


@pytest.mark.db
async def test_adelete_article_chunks(setup_real_db) -> None:
    """删除文章关联的所有文档块"""
    law_name = "反分裂国家法"
    pageindex = LawPageIndex()
    articles = await pageindex.aget_law_articles(law_name=law_name, limit=1)
    assert articles

    article = articles[0]
    node_id = UUID(article["id"])
    docstore = DocumentStore()

    count = await docstore.abatch_load_from_texts(
        texts=[(article["content"], node_id, law_name)],
    )
    assert count > 0

    await docstore.adelete_article_chunks(node_id)

    # 确认已删: 再次嵌入同一 node_id 不会冲突
    count2 = await docstore.abatch_load_from_texts(
        texts=[(article["content"], node_id, law_name)],
    )
    assert count2 > 0

    await docstore.adelete_article_chunks(node_id)
