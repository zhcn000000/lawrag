"""RAG 混合检索测试 (需要运行中的 PostgreSQL + LLM 服务)

使用标记: pytest -m "not db" 跳过, pytest -m "db" 运行
"""

import pytest

from lawrag.database.document import DocumentStore
from lawrag.database.ragsearch import RAGSearch


@pytest.mark.db
async def test_rag_hybrid_search(setup_real_db) -> None:
    """全流程: 嵌入条文 → 混合检索 → 验证结果"""
    law_name = "反分裂国家法"
    docstore = DocumentStore()
    ragsearch = RAGSearch()

    embed_result = await docstore.aembed_laws(law_name=law_name)
    assert embed_result["chunks_created"] >= 0

    results = await ragsearch.ahyprid_search(query="台湾问题的法律规定", limit=3)
    assert len(results) >= 1
    assert all(r.content for r in results)
    assert all(r.query_score is not None for r in results)
    assert all(r.page_index is not None for r in results)


@pytest.mark.db
async def test_rag_search_with_law_filter(setup_real_db) -> None:
    """限定 law_name 的混合检索"""
    law_name = "反分裂国家法"
    docstore = DocumentStore()
    ragsearch = RAGSearch()

    _ = await docstore.aembed_laws(law_name=law_name)

    results = await ragsearch.ahyprid_search(query="统一", limit=3, law_name=law_name)
    assert len(results) >= 1
    for r in results:
        assert r.name == law_name


@pytest.mark.db
async def test_rag_search_pure_bm25(setup_real_db) -> None:
    """纯 BM25 检索 (vecweight=0)"""
    law_name = "反分裂国家法"
    docstore = DocumentStore()
    ragsearch = RAGSearch()

    _ = await docstore.aembed_laws(law_name=law_name)

    results = await ragsearch.ahyprid_search(query="台湾", limit=3, vecweight=0)
    assert len(results) >= 1
