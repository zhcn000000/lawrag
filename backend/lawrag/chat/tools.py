from typing import Annotated, Literal

from exa_py.api import Category, SearchType
from pydantic import Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext, ToolDefinition

from lawrag.tools.base import (
    crawl_web_base,
    extract_web_base,
    fetch_web_base,
    get_document_context_base,
    python_repl_base,
    search_documents_base,
    search_web_base,
)

from .struct import ModelDeps

rag_toolset: FunctionToolset[ModelDeps] = FunctionToolset()
code_toolset: FunctionToolset[ModelDeps] = FunctionToolset()
web_toolset: FunctionToolset[ModelDeps] = FunctionToolset()


async def prepare_rag(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "rag_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


async def prepare_code(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "code_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


async def prepare_web(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "web_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


@rag_toolset.tool(
    name="search_documents",
    description="""
根据查询语义搜索法律文档库，返回分页的文档列表。
如果用户指定了特定法律名称，可以通过`source_name`限制搜索范围。
如果用户指定了特定页码/条款，可以通过`page_index`精确定位。
返回结果包含文档内容，支持翻页查看更多结果。
""",
    prepare=prepare_rag,
)
async def search_documents(
    ctx: RunContext[ModelDeps],
    query: Annotated[str, Field(description="搜索查询语句")],
    source_name: Annotated[str | None, Field(description="可选的来源名称过滤条件")] = None,
    page_index: Annotated[int | None, Field(description="可选的页码/条款索引")] = None,
    offset: Annotated[int, Field(description="分页偏移量,默认0")] = 0,
) -> Annotated[str, Field(description="返回markdown格式的搜索结果表格")]:
    try:
        return await search_documents_base(
            query=query,
            source_name=source_name,
            page_index=page_index,
            offset=offset,
        )
    except Exception as e:
        raise ModelRetry(f"搜索失败: {e!s}") from e


@rag_toolset.tool(
    name="get_document_context",
    description="""
获取指定文档的完整分块上下文，支持查看文档的前后分块。
当一个文档在搜索中被截断时，使用此工具获取该文档的相邻分块以获得更完整的上下文。
""",
    prepare=prepare_rag,
)
async def get_document_context(
    ctx: RunContext[ModelDeps],
    document_index: Annotated[int, Field(description="文档ID,来自搜索结果")],
) -> Annotated[str, Field(description="返回markdown格式的文档分块上下文")]:
    try:
        return await get_document_context_base(document_index=document_index)
    except Exception as e:
        raise ModelRetry(f"获取文档上下文失败: {e!s}") from e


@code_toolset.tool(
    name="python_repl",
    description="这是一个可以执行Python代码的工具，输入Python代码并返回最后一条表达式的结果和控制台输出。"
    "为了沙盒的安全性，以及沙盒的局限性，该工具不支持任何需要使用import导入的库，除了sys, typing, asyncio",
    prepare=prepare_code,
)
async def python_repl(
    ctx: RunContext[ModelDeps],
    code: Annotated[str, Field(description="要执行的Python代码")],
) -> Annotated[str, Field(description="返回最后一行表达式的结果和控制台输出")]:
    try:
        return await python_repl_base(code=code)
    except Exception as e:
        raise ModelRetry(f"执行Python代码时发生错误: {e}") from e


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
        return await search_web_base(
            query=query,
            max_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            search_type=search_type,
            category=category,
        )
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
        return await extract_web_base(urls=urls, query=query)
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
        return await crawl_web_base(url=url, max_depth=max_depth, max_pages=max_pages)
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
        return await fetch_web_base(url=url, format=format)
    except Exception as e:
        raise ModelRetry(f"网页获取失败: {e!s}") from e
