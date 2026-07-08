from typing import Annotated, Literal

from exa_py.api import Category, SearchType
from pydantic import Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext, ToolDefinition

from lawrag.tools.base import (
    crawl_web_base,
    extract_web_base,
    fetch_web_base,
    get_articles_under_chapter_base,
    get_law_toc_base,
    python_repl_base,
    search_documents_base,
    search_law_articles_base,
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
支持`regex`正则表达式过滤文档内容。但是可能的话，优先不使用正则表达式避免性能问题。
返回结果包含文档内容，支持翻页查看更多结果。
""",
    prepare=prepare_rag,
)
async def search_documents(
    ctx: RunContext[ModelDeps],
    query: Annotated[str, Field(description="搜索查询语句")],
    regex: Annotated[str | None, Field(description="可选的正则表达式，用于过滤文档内容")] = None,
    offset: Annotated[int, Field(description="分页偏移量,默认0")] = 0,
) -> Annotated[str, Field(description="返回markdown格式的搜索结果表格")]:
    try:
        return await search_documents_base(
            query=query,
            regex=regex,
            offset=offset,
        )
    except Exception as e:
        raise ModelRetry(f"搜索失败: {e!s}") from e


@rag_toolset.tool(
    name="search_law_articles",
    description="""
根据法律名称和法条号或关键词精确查找法条内容。
支持两种查找方式:
1. 精确法条号查找: 指定 law_name + article_number
2. 关键词搜索: 指定 law_name + query, 在指定法律中搜索匹配的法条
也可不指定法律名, 直接搜索所有已导入法律的法条。
""",
    prepare=prepare_rag,
)
async def search_law_articles(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
    query: Annotated[str | None, Field(description="在法条内容中搜索的关键词")] = None,
    article_number: Annotated[int | None, Field(description="精确法条号")] = None,
    start: Annotated[int | None, Field(description="法条号范围起始")] = None,
    end: Annotated[int | None, Field(description="法条号范围结束")] = None,
    limit: Annotated[int, Field(description="返回结果数量上限")] = 10,
) -> Annotated[str, Field(description="返回markdown格式的法条查询结果")]:
    try:
        return await search_law_articles_base(
            law_name=law_name,
            query=query,
            article_number=article_number,
            start=start,
            end=end,
            limit=limit,
        )
    except Exception as e:
        raise ModelRetry(f"法条查找失败: {e!s}") from e


@rag_toolset.tool(
    name="get_law_toc",
    description="获取指定法律的多级目录(章/节标题结构)。用于了解一部法律的整体框架, 或定位某条法条所属的章节。",
    prepare=prepare_rag,
)
async def get_law_toc(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
) -> Annotated[str, Field(description="返回markdown格式的法律章节目录")]:
    try:
        return await get_law_toc_base(law_name=law_name)
    except Exception as e:
        raise ModelRetry(f"获取法律目录失败: {e!s}") from e


@rag_toolset.tool(
    name="get_articles_under_chapter",
    description="获取某部法律某一章(含其下各节)内的全部法条文本。先用 get_law_toc 得到章标题, 再用本工具按章批量取条。",
    prepare=prepare_rag,
)
async def get_articles_under_chapter(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
    chapter_title: Annotated[str, Field(description="章标题, 例如'总则'或'自然人'")],
    limit: Annotated[int, Field(description="返回条文数量上限")] = 200,
) -> Annotated[str, Field(description="返回markdown格式的该章法条列表")]:
    try:
        return await get_articles_under_chapter_base(law_name=law_name, chapter_title=chapter_title, limit=limit)
    except Exception as e:
        raise ModelRetry(f"获取章节法条失败: {e!s}") from e


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
