from functools import cache
from typing import Literal
from uuid import UUID

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from pydantic_monty import Monty
from rich.pretty import pretty_repr
from tavily import AsyncTavilyClient

from lawrag.database.ragmode import RAGMode

rag_mode = RAGMode()


async def search_documents_base(
    query: str,
    source_name: str | None = None,
    page_index: int | None = None,
    offset: int = 0,
) -> str:
    source_id: UUID | None = None
    if source_name:
        from lawrag.database.database import DatabaseManager
        from lawrag.database.tables import DocumentSource

        db = DatabaseManager()
        async with db.asession() as session:
            from sqlalchemy import select as sqla_select
            from sqlmodel import col as scol

            stmt = sqla_select(scol(DocumentSource.id)).where(scol(DocumentSource.name) == source_name)
            result = await session.execute(stmt)
            row = result.first()
            if row:
                source_id = row[0]

    docs = await rag_mode.ahyprid_search(
        query=query,
        k=8,
        source_id=source_id,
        page_index=page_index,
        offset=offset,
    )

    if not docs:
        offset_info = f" (第{offset + 1}条起)" if offset else ""
        return f"## 搜索结果{offset_info}\n\n查询: {query}\n\n未找到相关文档。"

    data = []
    for i, doc in enumerate(docs):
        score = doc.query_score if doc.query_score is not None else 0.0
        source = doc.name or "unknown"
        preview = doc.content[:300] + "..." if len(doc.content) > 300 else doc.content
        row = {
            "#": offset + i + 1,
            "来源": source,
            "内容预览": preview,
            "相关性%": f"{min(score, 1.0) * 100:.1f}",
        }
        if doc.page_index is not None:
            row["页码"] = str(doc.page_index)
        if doc.document_index is not None:
            row["文档ID"] = str(doc.document_index)
        data.append(row)

    md = "## 搜索结果\n\n"
    md += f"查询: {query}\n"
    if offset:
        md += f"分页: 第{offset + 1}-{offset + len(docs)}条\n"
    md += f"共 {len(docs)} 条结果\n\n"

    dff = pd.DataFrame(data)
    md += dff.to_markdown(index=False)
    md += f"\n\n> 提示: 使用 `offset={offset + len(docs)}` 翻页查看更多结果。"
    md += "\n> 使用 `get_document_context` 通过文档ID获取完整文档上下文。"

    return md


async def get_document_context_base(document_index: int) -> str:
    context = await rag_mode.aget_document_context(document_index=document_index)

    chunks = context["chunks"]
    doc_id = context["document_index"]

    md = f"## 文档上下文 (ID: {doc_id})\n\n"

    if not chunks:
        md += "未找到该文档。"
        return md

    for chunk in chunks:
        cid = chunk["id"]
        content = chunk["content"]
        page = chunk.get("page_index")
        header = f"### 分块 {cid}"
        if page is not None:
            header += f" (页码: {page})"
        md += f"{header}\n"
        md += f"{content}\n\n"

    return md


@cache
def _get_tavily() -> AsyncTavilyClient:
    return AsyncTavilyClient()


async def search_web_base(
    query: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    include_image: bool = False,
) -> dict:
    try:
        return await _get_tavily().search(
            query,
            max_results=max_results,
            include_domains=include_domains,  # type: ignore
            exclude_domains=exclude_domains,  # type: ignore
            include_image=include_image,
        )
    except Exception as e:
        return {"error": str(e), "results": []}


async def extract_web_base(
    urls: list[str],
    query: str | None = None,
    include_image: bool = False,
) -> dict:
    try:
        return await _get_tavily().extract(
            urls,
            include_images=include_image,
            query=query,  # type: ignore
        )
    except Exception as e:
        return {"error": str(e), "results": []}


async def crawl_web_base(
    url: str,
    max_depth: int = 1,
    max_pages: int = 10,
) -> dict:
    try:
        return await _get_tavily().crawl(
            url,
            max_depth=max_depth,
            max_pages=max_pages,
        )
    except Exception as e:
        return {"error": str(e), "results": []}


async def fetch_web_base(url: str, format: str = "text") -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        html_content = response.text
    if format == "html":
        return html_content
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator="\n")


async def python_repl_base(code: str) -> str:
    monty = Monty(code=code)
    out = []

    def print_callback(stream: Literal["stdout"], content: str) -> None:
        if stream == "stdout":
            out.append(content)

    result = await monty.run_async(print_callback=print_callback)
    output = "表达式结果: " + pretty_repr(result)
    if out:
        output += "\n输出:\n" + "".join(out)
    return output
