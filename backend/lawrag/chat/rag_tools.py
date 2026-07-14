from logging import getLogger
from typing import Annotated, TypedDict

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolDefinition
from pydantic_ai.capabilities import Capability

from lawrag.database.pageindex import (
    ArticleDict,
    BrowseResultDict,
    LawInfoDict,
    LawPageIndex,
    NodeByPathDict,
    TocEntryDict,
)
from lawrag.database.ragsearch import RAGSearch

from .struct import ModelDeps

logger = getLogger(__name__)

rag_capability: Capability[ModelDeps] = Capability()

rag_mode = RAGSearch()
page_index = LawPageIndex()


async def prepare_rag(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "rag_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


@rag_capability.instructions
def rag_instructions(ctx: RunContext[ModelDeps]) -> str | None:
    if "rag_toolkit" not in ctx.deps.select_toolset:
        return None
    text = """当前已经启用rag工具集功能, 用于查询已导入的法律文档库 (法律法规、司法解释等) 的内容, 使用流程如下:

1. 探查法律范围: 不确定有哪些法律时, 先调用
   find_laws(regex?, limit, offset) 列出已导入法律的名称与法条数量, 可用 regex 过滤。
2. 选择入口 (根据用户意图三选一):
   - 语义检索: 关键词/语义不明确时, 用 search_documents(query, regex?, limit, offset)
     返回的 `path` 字段可用于后续下钻。
   - 按条号取: 已知具体法条号或区间,
     用 get_law_articles(law_name, article_number?, start?, end?, limit)。
   - 沿结构浏览: 想了解整体框架或定位章节, 先 get_law_toc(law_name) 看编/章/节目录,
     再 browse_law(law_name, path, limit) 逐级下钻。
3. 取详情/继续下钻:
   - 已知 path 想看完整内容: get_article_by_path(law_name, path)。
   - 想看某层级的全部下级条目: browse_law(law_name, path)。
4. 综合回答: 必要时并行调用上述工具 (例如同时 search_documents 扩大召回
   + get_law_toc 确认结构 + browse_law 补齐上下文), 再用自然语言回答用户。

注意事项:
- `path` 是数据库物化路径, 构成方式如下
path 的格式为各级 `<前缀><编号>` 用 / 连接, 前缀含义: b=编, sb=分编, c=章, s=节, a=条, pre=序言;
path 的开头总是 law0/ (表示法律根节点), 后面跟各级节点,
例如 law0/b2/c2/s1 表示 第2编→第2章→第1节。
path 不是中文标题，而是数据库物化路径
你可以按照规律自己拼以查看其他的法律条款
或 search_documents 等工具返回结果中的 `path` 值传入, 也可以自行构造，但格式需要正确
- `law_name` 必须与 find_laws 或者其他工具返回的法律名称的完全一致。
- 所有工具返回结构化的 dict/list 数据，可被代码沙箱中的 Python 代码直接处理。
"""
    return text


@rag_capability.tool(
    name="find_laws",
    description=(
        "列出所有已导入的法律及其法条数量。支持正则过滤和分页。"
        "返回 list[dict]，每个 dict 含 law_name 和 article_count。"
    ),
    prepare=prepare_rag,
    include_return_schema=True,
)
async def find_laws(
    ctx: RunContext[ModelDeps],
    regex: Annotated[str | None, Field(description="正则表达式过滤法律名称, 如'刑法|民法典'")] = None,
    limit: Annotated[int, Field(description="返回数量上限, 默认50")] = 50,
    offset: Annotated[int, Field(description="分页偏移量, 默认0")] = 0,
) -> Annotated[list[LawInfoDict], Field(description="法律列表，每项含 law_name, article_count")]:
    try:
        return await page_index.afind_laws(regex=regex, limit=limit, offset=offset)
    except Exception as e:
        raise ModelRetry(f"获取法律列表失败: {e!s}") from e


class DocumentResult(TypedDict):
    content: str
    name: str
    path: str
    score: float
    source: str


@rag_capability.tool(
    name="search_documents",
    description=(
        "根据查询语义搜索法律文档库，返回分页的文档列表。支持 regex 过滤。"
        "每条结果含 content/name/path/score/source 字段。"
    ),
    prepare=prepare_rag,
    include_return_schema=True,
)
async def search_documents(
    ctx: RunContext[ModelDeps],
    query: Annotated[str, Field(description="搜索查询语句")],
    law_name: Annotated[str | None, Field(description="可选按照法律过滤内容，留空或不填写则在所有法律范围搜索")] = None,
    regex: Annotated[str | None, Field(description="可选的正则表达式，用于过滤文档内容，留空或不填写则不过滤")] = None,
    limit: Annotated[int, Field(description="返回结果数量上限")] = 5,
    vecweight: Annotated[
        float,
        Field(
            description="向量搜索的权重，1-向量搜索权重即为bm25搜索权重，搜索为bm25+向量双通道，修改权重可以调节搜索侧重点",
            ge=0,
            le=1,
        ),
    ] = 0.6,
) -> Annotated[list[DocumentResult], Field(description="搜索结果列表，每项含 content/name/path/score/source")]:
    try:
        docs = await rag_mode.ahyprid_search(
            query=query,
            law_name=law_name,
            limit=limit,
            regex=regex,
            vecweight=vecweight,
        )
        return [
            DocumentResult(
                content=doc.content,
                name=doc.name or "",
                path=doc.node_path or "",
                score=doc.query_score or 0.0,
                source=doc.page_index or doc.name or "",
            )
            for doc in docs
        ]
    except Exception as e:
        raise ModelRetry(f"搜索失败: {e!s}") from e


@rag_capability.tool(
    name="get_article_by_path",
    description="根据层级路径 path 获取该 path 本身对应的法条(或章节)信息。需要输入law_name和path两个参数。"
    "返回 dict，含 law_name/path/content/node_type/number/full_path。",
    prepare=prepare_rag,
    include_return_schema=True,
)
async def get_article_by_path(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
    path: Annotated[str, Field(description="层级路径, 原样取自其它工具返回的 `path` 值, 如 'law0/b2/c2/s1'")],
) -> Annotated[NodeByPathDict, Field(description="法条 dict 或 null，含 law_name/path/content/node_type 等")]:
    try:
        return await page_index.aget_node_by_path(law_name=law_name, path=path)
    except Exception as e:
        raise ModelRetry(f"获取法条信息失败: {e!s}") from e


@rag_capability.tool(
    name="get_law_articles",
    description="获取某个范围的法条内容。start=end可以返回单条法律内容",
    prepare=prepare_rag,
    include_return_schema=True,
)
async def get_law_articles(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
    start: Annotated[int | None, Field(description="法条号范围起始")] = None,
    end: Annotated[int | None, Field(description="法条号范围结束")] = None,
    limit: Annotated[int, Field(description="返回结果数量上限")] = 10,
) -> Annotated[list[ArticleDict], Field(description="单条 dict 或列表，未找到返回 null")]:
    try:
        return await page_index.aget_law_articles(law_name=law_name, start=start, end=end, limit=limit)
    except Exception as e:
        raise ModelRetry(f"法条查找失败: {e!s}") from e


@rag_capability.tool(
    name="get_law_toc",
    description="获取指定法律的多级目录(编/分编/章/节标题结构)。"
    "返回嵌套 list[dict]，每节点含 node_type/number/title/path/children。",
    prepare=prepare_rag,
    include_return_schema=True,
)
async def get_law_toc(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
) -> Annotated[list[TocEntryDict], Field(description="嵌套目录树，每节点含 node_type/number/title/path/children")]:
    try:
        return await page_index.aget_law_toc(law_name=law_name)
    except Exception as e:
        raise ModelRetry(f"获取法律目录失败: {e!s}") from e


@rag_capability.tool(
    name="browse_law",
    description="按层级路径 path 逐级浏览一部法律 (编/分编/章/节/条)。"
    "返回 dict，含 law_name/path/node_type/title/children。",
    prepare=prepare_rag,
)
async def browse_law(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
    path: Annotated[
        str | None,
        Field(description="层级路径, 原样取自其它工具返回的 `path` 值 (如 'b2/c2/s1'); 留空(null)浏览顶层"),
    ] = None,
    limit: Annotated[int, Field(description="返回条目数量上限")] = 200,
) -> Annotated[BrowseResultDict, Field(description="浏览结果 dict, 含 law_name/path/node_type/title/children")]:
    try:
        if path is None or not path.strip():
            path = "law0/"
        return await page_index.abrowse_law(law_name=law_name, path=path, limit=limit)
    except Exception as e:
        raise ModelRetry(f"浏览法律层级失败: {e!s}") from e
