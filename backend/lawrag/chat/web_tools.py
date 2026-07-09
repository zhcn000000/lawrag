from functools import cache
from typing import Annotated, Literal, TypedDict

import httpx
from bs4 import BeautifulSoup
from exa_py import AsyncExa
from exa_py.api import Category, SearchType
from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolDefinition
from pydantic_ai.capabilities import Capability

from .struct import ModelDeps

web_capability: Capability[ModelDeps] = Capability()


async def prepare_web(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "web_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


@cache
def _get_exa() -> AsyncExa:
    return AsyncExa()


class SearchResult(TypedDict):
    summery: str
    text: str


@web_capability.tool(
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
) -> list[SearchResult]:
    try:
        response = await _get_exa().search(
            query,
            num_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            type=search_type,
            category=category,
        )
        results: list[SearchResult] = []
        for result in response.results:
            results.append(
                SearchResult(
                    summery=result.summary or "",
                    text=result.text or "",
                ),
            )
        return results

    except Exception as e:
        raise ModelRetry(f"网络搜索失败: {e!s}") from e


@web_capability.tool(
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
