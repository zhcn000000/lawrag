from functools import cache
from typing import Literal
from uuid import UUID

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from exa_py import AsyncExa
from exa_py.api import Category, SearchType
from pydantic_monty import Monty
from rich.pretty import pretty_repr

from lawrag.database.pageindex import LawPageIndex
from lawrag.database.ragmode import RAGMode

rag_mode = RAGMode()
page_index = LawPageIndex()


async def search_documents_base(
    query: str,
    law_name: str | None = None,
    page_index: int | None = None,
    regex: str | None = None,
    offset: int = 0,
) -> str:
    source_id: UUID | None = None
    if law_name:
        from lawrag.database.database import DatabaseManager
        from lawrag.database.tables import DocumentSource

        db = DatabaseManager()
        async with db.asession() as session:
            from sqlalchemy import select as sqla_select
            from sqlmodel import col as scol

            stmt = sqla_select(scol(DocumentSource.id)).where(scol(DocumentSource.name) == law_name)
            result = await session.execute(stmt)
            row = result.first()
            if row:
                source_id = row[0]

    docs = await rag_mode.ahyprid_search(
        query=query,
        k=8,
        source_id=source_id,
        page_index=page_index,
        regex=regex,
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


async def search_law_articles_base(
    law_name: str,
    query: str | None = None,
    article_number: int | None = None,
    start: int | None = None,
    end: int | None = None,
    limit: int = 10,
) -> str:
    """在指定法律中查找法条, 支持精确法条号查找和关键词搜索"""
    if article_number is not None:
        article = await page_index.aget_by_law_article(law_name=law_name, article_number=article_number)
        if article is None:
            return f"未找到法律 '{law_name}' 第{article_number}条"
        return f"## {law_name} 第{article_number}条\n\n{article['content']}"

    if query:
        articles = await page_index.asearch_articles(law_name=law_name, query=query, limit=limit)
    else:
        articles = await page_index.aget_law_articles(
            law_name=law_name,
            start=start,
            end=end,
            limit=limit,
        )

    if not articles:
        q_desc = query or f"第{start}-{end}条" if start or end else "全部"
        return f"未在法律 '{law_name}' 中找到匹配 '{q_desc}' 的法条"

    data = []
    for a in articles:
        preview = a["content"][:300] + "..." if len(a["content"]) > 300 else a["content"]
        data.append({
            "条号": f"第{a['article_number']}条",
            "内容": preview,
        })

    title = f"## {law_name}"
    if query:
        title += f" 搜索: '{query}'"
    md = f"{title}\n\n共 {len(articles)} 条结果\n\n"
    dff = pd.DataFrame(data)
    md += dff.to_markdown(index=False)
    return md


@cache
def _get_exa() -> AsyncExa:
    return AsyncExa()


async def search_web_base(
    query: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    search_type: SearchType | None = None,
    category: Category | None = None,
) -> str:
    try:
        response = await _get_exa().search(
            query,
            num_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            type=search_type,
            category=category,
        )
        lines: list[str] = []
        for i, result in enumerate(response.results, 1):
            lines.extend([f"{i}. {result.title or '无标题'}", f"   URL: {result.url}"])
            if result.text:
                preview = result.text[:300].replace("\n", " ")
                lines.append(f"   内容: {preview}...")
            lines.append("")
        return "\n".join(lines) if lines else "未找到搜索结果"
    except Exception as e:
        return "Error: " + str(e)


async def extract_web_base(
    urls: list[str],
    query: str | None = None,
) -> str:
    try:
        kwargs: dict = {"text": {"max_characters": 5000}}
        if query:
            kwargs["summary"] = {"query": query}
        response = await _get_exa().get_contents(urls, **kwargs)
        lines = []
        for result in response.results:
            lines.append(f"URL: {result.url}")
            if result.title:
                lines.append(f"标题: {result.title}")
            if result.text:
                lines.append(f"内容: {result.text[:1000]}")
            if result.summary:
                lines.append(f"摘要: {result.summary}")
            lines.append("")
        return "\n".join(lines) if lines else "未提取到内容"
    except Exception as e:
        return "Error: " + str(e)


async def crawl_web_base(url: str, max_depth: int = 1, max_pages: int = 10) -> str:
    visited: set[str] = set()
    results: list[str] = []

    async def _crawl(url: str, depth: int) -> None:
        if depth > max_depth or len(visited) >= max_pages or url in visited:
            return
        visited.add(url)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator="\n").strip()
            results.append(f"## {url}\n{text[:2000]}\n")
            if depth < max_depth and len(visited) < max_pages:
                for a in soup.find_all("a", href=True):
                    href = a.get("href")
                    if not isinstance(href, str):
                        continue
                    next_url = href if href.startswith("http") else url.rstrip("/") + "/" + href.lstrip("/")
                    if next_url.startswith(("http://", "https://")):
                        await _crawl(next_url, depth + 1)
        except Exception:
            pass

    await _crawl(url, 1)
    return "\n---\n".join(results) if results else f"爬取 {url} 失败"


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
