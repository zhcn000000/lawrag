from functools import cache
from typing import Annotated, Literal

import httpx
from bs4 import BeautifulSoup
from exa_py import AsyncExa
from exa_py.api import Category, SearchType
from pydantic import Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext, ToolDefinition

from .struct import ModelDeps

web_toolset: FunctionToolset[ModelDeps] = FunctionToolset()


async def prepare_web(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "web_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


@cache
def _get_exa() -> AsyncExa:
    return AsyncExa()


@web_toolset.tool(
    prepare=prepare_web,
    name="search_web",
    description="网络搜索工具，输入搜索关键词，返回搜索结果摘要。可用于补充法律法规、司法解释等背景信息。",
)
async def search_web(
    ctx: RunContext[ModelDeps],
    query: Annotated[str, Field(description="搜索关键词")],
    max_results: Annotated[int, Field(description="返回的最大搜索结果数量")] = 5,
    include_domains: Annotated[list[str] | None, Field(description="要包含的域名列表")] = None,
    exclude_domains: Annotated[list[str] | None, Field(description="要排除的域名列表")] = None,
    search_type: Annotated[SearchType | None, Field(description="搜索类型: auto/fast/deep等")] = None,
    category: Annotated[Category | None, Field(description="搜索类别: company, news, research paper等")] = None,
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
        raise ModelRetry(f"网络搜索失败: {e!s}") from e


@web_toolset.tool(
    prepare=prepare_web,
    name="extract_web",
    description="提取网页内容工具，输入网页URL列表，返回网页的主要内容摘要。",
)
async def extract_web(
    ctx: RunContext[ModelDeps],
    urls: Annotated[list[str], Field(description="要提取内容的网页URL列表")],
    query: Annotated[str | None, Field(description="可选的查询关键词，用于指导内容提取")] = None,
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
        raise ModelRetry(f"网页内容提取失败: {e!s}") from e


@web_toolset.tool(
    prepare=prepare_web,
    name="crawl_web",
    description="网页爬取工具，输入网页URL，递归爬取并返回网页文本内容。",
)
async def crawl_web(
    ctx: RunContext[ModelDeps],
    url: Annotated[str, Field(description="要爬取内容的网页URL")],
    max_depth: Annotated[int, Field(description="爬取的最大深度")] = 1,
    max_pages: Annotated[int, Field(description="爬取的最大页面数量")] = 10,
) -> str:
    try:
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
    except Exception as e:
        raise ModelRetry(f"网页爬取失败: {e!s}") from e


@web_toolset.tool(
    prepare=prepare_web,
    name="fetch_web",
    description="获取网页原始内容工具，输入网页URL，返回网页的文本内容。",
)
async def fetch_web(
    ctx: RunContext[ModelDeps],
    url: Annotated[str, Field(description="要获取内容的网页URL")],
    format: Annotated[Literal["text", "html"], Field(description="内容格式，支持html和text两种格式")] = "text",
) -> str:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            html_content = response.text
        if format == "html":
            return html_content
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.get_text(separator="\n")
    except Exception as e:
        raise ModelRetry(f"网页获取失败: {e!s}") from e
