from typing import Annotated

import pandas as pd
from pydantic import Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext, ToolDefinition

from lawrag.database.pageindex import LawPageIndex
from lawrag.database.ragmode import RAGMode

from .struct import ModelDeps

rag_toolset: FunctionToolset[ModelDeps] = FunctionToolset()

rag_mode = RAGMode()
page_index = LawPageIndex()


async def prepare_rag(ctx: RunContext[ModelDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    if "rag_toolkit" in ctx.deps.select_toolset:
        return tool_def
    return None


def _format_location(article: dict) -> str:
    """由法条 dict 的章/节字段构造 '第X章 标题 / 第Y节 标题' 定位串。"""
    parts: list[str] = []
    if article.get("chapter_number") is not None:
        parts.append(f"第{article['chapter_number']}章 {article.get('chapter_title') or ''}".strip())
    if article.get("section_number") is not None:
        parts.append(f"第{article['section_number']}节 {article.get('section_title') or ''}".strip())
    return " / ".join(parts)


@rag_toolset.tool(
    name="list_laws",
    description=(
        "列出所有已导入的法律及其法条数量。支持正则过滤和分页。先调用此工具了解有哪些法律可用, 再调用其他法律查询工具。"
    ),
    prepare=prepare_rag,
)
async def list_laws(
    ctx: RunContext[ModelDeps],
    regex: Annotated[str | None, Field(description="正则表达式过滤法律名称, 如'刑法|民法典'")] = None,
    limit: Annotated[int, Field(description="返回数量上限, 默认50")] = 50,
    offset: Annotated[int, Field(description="分页偏移量, 默认0")] = 0,
) -> Annotated[str, Field(description="返回markdown格式的法律列表")]:
    try:
        laws = await page_index.alist_laws(regex=regex, limit=limit, offset=offset)
        if not laws:
            return "暂无已导入的法律。"
        dff = pd.DataFrame(laws)
        header = "## 已导入法律列表"
        if regex:
            header += f" (匹配: `{regex}`)"
        if offset:
            header += f" (第{offset + 1}条起)"
        return f"{header}\n\n共 {len(laws)} 部\n\n{dff.to_markdown(index=False)}"
    except Exception as e:
        raise ModelRetry(f"获取法律列表失败: {e!s}") from e


@rag_toolset.tool(
    name="search_documents",
    description="""
根据查询语义搜索法律文档库，返回分页的文档列表。
支持`regex`正则表达式过滤文档内容。但是可能的话，优先不使用正则表达式避免性能问题。
返回结果包含文档内容，支持翻页查看更多结果。
每条结果附带 `path` 列 (该法条在其法律中的层级路径)，可将其原样传给 browse_law 浏览同章节的其它法条。
""",
    prepare=prepare_rag,
)
async def search_documents(
    ctx: RunContext[ModelDeps],
    query: Annotated[str, Field(description="搜索查询语句")],
    regex: Annotated[str | None, Field(description="可选的正则表达式，用于过滤文档内容")] = None,
    limit: Annotated[int, Field(description="返回结果数量上限")] = 5,
    offset: Annotated[int, Field(description="分页偏移量,默认0")] = 0,
) -> Annotated[str, Field(description="返回markdown格式的搜索结果表格")]:
    try:
        docs = await rag_mode.ahyprid_search(
            query=query,
            limit=limit,
            regex=regex,
            offset=offset,
        )

        if not docs:
            offset_info = f" (第{offset + 1}条起)" if offset else ""
            return f"## 搜索结果{offset_info}\n\n查询: {query}\n\n未找到相关文档。"

        data = []
        for i, doc in enumerate(docs):
            score = doc.query_score if doc.query_score is not None else 0.0
            source = doc.page_index or doc.name or "unknown"
            preview = doc.content[:300] + "..." if len(doc.content) > 300 else doc.content
            data.append({
                "#": offset + i + 1,
                "来源": source,
                "path": doc.node_path or "-",
                "内容预览": preview,
                "相关性%": f"{min(score, 1.0) * 100:.1f}",
            })

        md = "## 搜索结果\n\n"
        md += f"查询: {query}\n"
        if offset:
            md += f"分页: 第{offset + 1}-{offset + len(docs)}条\n"
        md += f"共 {len(docs)} 条结果\n\n"

        dff = pd.DataFrame(data)
        md += dff.to_markdown(index=False)
        md += f"\n\n> 提示: 使用 `offset={offset + len(docs)}` 翻页查看更多结果。"
        md += "\n> 提示: `path` 列为该法条的层级路径, 可传给 browse_law 浏览同章节其它法条。"

        return md
    except Exception as e:
        raise ModelRetry(f"搜索失败: {e!s}") from e


@rag_toolset.tool(
    name="get_article_by_path",
    description="""根据层级路径 `path` 获取该 path 本身对应的法条(或章节)信息, 返回格式同 search_documents 的单条结果。
`path` 原样取自 search_documents / get_law_toc / browse_law 返回的 `path` 列 (如 'law0/b2/c2/s1' 或 'b2/c2/s1')。
适用于已知某条法条的 path, 想直接查看它的完整内容与所属章节面包屑, 而无需再次搜索。""",
    prepare=prepare_rag,
)
async def get_article_by_path(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
    path: Annotated[str, Field(description="层级路径, 原样取自其它工具返回的 `path` 列, 如 'law0/b2/c2/s1'")],
) -> Annotated[str, Field(description="返回markdown格式的单条法条信息")]:
    try:
        node = await page_index.aget_node_by_path(law_name=law_name, path=path)
        if node is None:
            return (
                f"未在法律 '{law_name}' 中找到 path='{path}'。"
                "path 应原样取自 search_documents / get_law_toc / browse_law 返回的 `path` 值。"
            )

        data = [
            {
                "路径": node["path"],
                "内容": node["content"] or "-",
                "来源": node["full_path"] or "-",
            },
        ]
        md = "## 法条信息\n\n"
        dff = pd.DataFrame(data)
        md += dff.to_markdown(index=False)
        return md
    except Exception as e:
        raise ModelRetry(f"获取法条信息失败: {e!s}") from e


@rag_toolset.tool(
    name="get_law_articles",
    description="""获取某个范围的法条内容""",
    prepare=prepare_rag,
)
async def get_law_articles(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
    article_number: Annotated[int | None, Field(description="精确法条号")] = None,
    start: Annotated[int | None, Field(description="法条号范围起始")] = None,
    end: Annotated[int | None, Field(description="法条号范围结束")] = None,
    limit: Annotated[int, Field(description="返回结果数量上限")] = 10,
) -> Annotated[str, Field(description="返回markdown格式的法条查询结果")]:
    try:
        if article_number is not None:
            article = await page_index.aget_by_law_article(law_name=law_name, article_number=article_number)
            if article is None:
                return f"未找到法律 '{law_name}' 第{article_number}条"
            location = _format_location(article)
            header = f"## {law_name} 第{article_number}条"
            if location:
                header += f"\n\n> {location}"
            return f"{header}\n\n{article['content']}"

        articles = await page_index.aget_law_articles(
            law_name=law_name,
            start=start,
            end=end,
            limit=limit,
        )

        if not articles:
            q_desc = f"第{start}-{end}条" if start or end else "全部"
            return f"未在法律 '{law_name}' 中找到匹配 '{q_desc}' 的法条"

        data = []
        for a in articles:
            preview = a["content"][:300] + "..." if len(a["content"]) > 300 else a["content"]
            data.append({
                "章/节": _format_location(a) or "-",
                "条号": f"第{a['article_number']}条",
                "内容": preview,
            })

        title = f"## {law_name}"
        md = f"{title}\n\n共 {len(articles)} 条结果\n\n"
        dff = pd.DataFrame(data)
        md += dff.to_markdown(index=False)
        return md
    except Exception as e:
        raise ModelRetry(f"法条查找失败: {e!s}") from e


@rag_toolset.tool(
    name="get_law_toc",
    description="""获取指定法律的多级目录(编/分编/章/节标题结构)。用于了解一部法律的整体框架, 或定位某条法条所属的章节。
目录每个节点都带有 `path` (层级路径)。要查看某编/章/节下的具体法条时, 复制对应节点的 `path` 传给 browse_law。""",
    prepare=prepare_rag,
)
async def get_law_toc(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
) -> Annotated[str, Field(description="返回markdown格式的法律章节目录")]:
    try:
        toc = await page_index.aget_law_toc(law_name=law_name)
        if not toc:
            return f"法律 '{law_name}' 暂无章节目录 (可能未导入或该法律不分章)。"
        unit = {"part": "编", "subpart": "分编", "chapter": "章", "section": "节"}
        lines = [
            f"## {law_name} 目录",
            "",
            "> 每行末尾方括号内为该节点的 `path`, 可直接传给 browse_law 浏览其下法条。",
            "",
        ]

        def _walk(nodes: list[dict], depth: int) -> None:
            for node in nodes:
                u = unit.get(node["node_type"], "")
                num = f"第{node['number']}{u}" if node.get("number") is not None else u
                title = node.get("title") or ""
                path = node.get("path") or ""
                lines.append(f"{'    ' * depth}- {num} {title} [path: {path}]".rstrip())
                children = node.get("children") or []
                if children:
                    _walk(children, depth + 1)

        _walk(toc, 0)
        return "\n".join(lines)
    except Exception as e:
        raise ModelRetry(f"获取法律目录失败: {e!s}") from e


@rag_toolset.tool(
    name="browse_law",
    description="""像浏览文件夹一样按层级路径 `path` 逐级浏览一部法律 (编/分编/章/节/条)。
关键: `path` 不是自己拼的中文标题, 而是数据库里的物化路径, 请直接复制 get_law_toc
或 search_documents 返回结果中的 `path` 值传入, 也可以自行构造
path 的格式为各级 `<前缀><编号>` 用 / 连接, 前缀含义: b=编, sb=分编, c=章, s=节, a=条, pre=序言;
path 的开头总是 law0/ (表示法律根节点), 后面跟各级节点, 例如 law0/b2/c2/s1 表示 第2编→第2章→第1节。
例如 'b2/c2/s1' 表示 第2编→第2章→第1节。
- 不传 path: 返回该法律最顶层的条目 (编 或 章 或 条)。
- 传 path: 返回该节点的直接下一层级 (编→章, 章→节或条, 节→条)。
返回列表中每行仍带 `path`, 复制它继续下钻即可。若只想按关键词/条号找法条, 请用 search_law_articles。""",
    prepare=prepare_rag,
)
async def browse_law(
    ctx: RunContext[ModelDeps],
    law_name: Annotated[str, Field(description="法律名称, 例如'中华人民共和国民法典'")],
    path: Annotated[
        str | None,
        Field(
            description=(
                "层级路径, 原样取自 get_law_toc / search_documents 返回的 `path` 列 (如 'b2/c2/s1'); 留空浏览顶层"
            ),
        ),
    ] = None,
    limit: Annotated[int, Field(description="返回条目数量上限")] = 200,
) -> Annotated[str, Field(description="返回markdown格式的下一层级条目列表, 含可继续下钻的 path")]:
    try:
        result = await page_index.abrowse_law(law_name=law_name, path=path, limit=limit)

        if result.get("error"):
            err = result["error"]
            if err == "law_not_found":
                return f"未找到法律 '{law_name}'。可先用 list_laws 查看已导入的法律。"
            if err == "path_not_found":
                return (
                    f"在 '{law_name}' 中未找到 path='{path}'。"
                    "path 应原样取自 get_law_toc 或 search_documents 返回的 `path` 值。"
                )
            return f"浏览 '{law_name}' 失败: {err}"

        children = result["children"]
        loc = result["title"] or f"《{law_name}》"
        cur_path = result.get("path") or ""
        if not children:
            return f"## {loc}\n\n该层级下暂无内容。"

        if all(c["is_leaf"] for c in children):
            data = [
                {
                    "条号": f"第{c['number']}条",
                    "path": c["path"],
                    "内容": (c["content"] or "")[:300] + ("..." if len(c["content"] or "") > 300 else ""),
                }
                for c in children
            ]
            md = f"## {loc} `[{cur_path}]`\n\n共 {len(children)} 条法条\n\n"
            return md + pd.DataFrame(data).to_markdown(index=False)

        data = [
            {
                "path": c["path"],
                "类型": {"part": "编", "subpart": "分编", "chapter": "章", "section": "节", "article": "条"}.get(
                    c["node_type"],
                    c["node_type"],
                ),
                "编号": c["number"] if c["number"] is not None else "-",
                "标题/内容": (c["title"] or c["content"] or "")[:200],
            }
            for c in children
        ]
        md = f"## {loc} `[{cur_path}]`\n\n共 {len(children)} 个下级条目 (把某行的 `path` 传给 browse_law 继续下钻)\n\n"
        return md + pd.DataFrame(data).to_markdown(index=False)
    except Exception as e:
        raise ModelRetry(f"浏览法律层级失败: {e!s}") from e
