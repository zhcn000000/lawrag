import logging
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
import uvloop
from asyncer import runnify
from rich import print as rprint
from rich import traceback
from rich.logging import RichHandler
from rich.table import Table
from typer import Argument, Option, Typer

from lawrag.database.initdb import clean_db, init_db, reset_db
from lawrag.database.pageindex import LawPageIndex
from lawrag.database.ragmode import RAGMode
from lawrag.routers import app
from lawrag.utils.environments import settings

logger = logging.getLogger(__name__)

cmd = Typer(pretty_exceptions_enable=False)
pageindex_cmd = Typer(pretty_exceptions_enable=False, help="法条索引命令")


@cmd.command()
@runnify
async def start() -> None:
    config = uvicorn.Config(
        app,
        host=settings.FASTAPI_HOST,
        port=settings.FASTAPI_PORT,
        log_level="info",
        workers=5,
        log_config=None,
        access_log=True,
        ssl_keyfile=settings.SSL_KEY_PATH
        if settings.SSL_KEY_PATH is not None and settings.SSL_KEY_PATH.exists()
        else None,
        ssl_certfile=settings.SSL_CERT_PATH
        if settings.SSL_CERT_PATH is not None and settings.SSL_CERT_PATH.exists()
        else None,
    )
    server = uvicorn.Server(config)
    await server.serve()


@cmd.command()
@runnify
async def database(
    mode: Annotated[Literal["init", "reset", "clean"], Argument(help="Database operation mode")],
    dbname: Annotated[str | None, Option("--dbname", "-d", help="Name of the database to initialize")] = None,
) -> None:
    if mode == "init":
        await init_db(dbname=dbname)
    elif mode == "reset":
        await reset_db(dbname=dbname)
    elif mode == "clean":
        await clean_db(dbname=dbname)


@cmd.command()
@runnify
async def search(
    query: Annotated[str, Argument(help="Search query")],
    k: Annotated[int, Option("--top", "-k", help="Number of results")] = 5,
) -> None:
    rag = RAGMode()
    docs = await rag.ahyprid_search(query=query, k=k)

    if docs:
        table = Table(title=f'搜索结果: "{query}"', title_style="bold")
        table.add_column("score", style="cyan", width=8)
        table.add_column("title", style="green", width=30)
        table.add_column("content", style="white")
        for doc in docs:
            score = f"{doc.query_score:.4f}" if doc.query_score else "N/A"
            name = doc.name or "Untitled"
            content = doc.content[:100].replace("\n", " ") + ("..." if len(doc.content) > 100 else "")
            table.add_row(score, name, content)
        rprint(table)
    else:
        rprint("无搜索结果")


@pageindex_cmd.command("import")
@runnify
async def pageindex_import(
    path: Annotated[Path, Argument(help="Path to law .txt file or directory")] | None = None,
    category: Annotated[str | None, Option("--category", "-c", help="Category for the laws")] = None,
) -> None:
    pageindex = LawPageIndex()
    if path is None:
        path = settings.DATA_ROOT / "structured_laws"
    if path.is_dir():
        results = await pageindex.aimport_from_dir(dir_path=path, category=category)
    else:
        result = await pageindex.aimport_file(file_path=path, category=category)
        results = [result]
    total = sum(r.get("count", 0) for r in results)
    ok = sum(1 for r in results if r.get("status") == "ok")
    error = sum(1 for r in results if r.get("status") == "error")
    logger.info("导入完成: %d 个文件, 共 %d 条法条 (成功 %d, 失败 %d)", len(results), total, ok, error)


@pageindex_cmd.command("list")
@runnify
async def pageindex_list() -> None:
    pageindex = LawPageIndex()
    laws = await pageindex.alist_laws()
    if not laws:
        rprint("暂无已导入的法律")
        return
    table = Table(title="已导入法律列表", title_style="bold")
    table.add_column("法律名称", style="green")
    table.add_column("法条数量", style="cyan", justify="right")
    for law in laws:
        table.add_row(law["law_name"], str(law["article_count"]))
    rprint(table)


@pageindex_cmd.command("show")
@runnify
async def pageindex_show(
    law_name: Annotated[str, Argument(help="Law name to show")],
    start: Annotated[int | None, Option("--start", "-s", help="Starting article number")] = None,
    end: Annotated[int | None, Option("--end", "-e", help="Ending article number")] = None,
    limit: Annotated[int, Option("--limit", "-l", help="Max articles to show")] = 50,
) -> None:
    pageindex = LawPageIndex()
    articles = await pageindex.aget_law_articles(law_name=law_name, start=start, end=end, limit=limit)
    if not articles:
        rprint(f"未找到法律 '{law_name}' 的法条")
        return
    table = Table(title=f"{law_name} 法条列表", title_style="bold")
    table.add_column("条号", style="cyan", width=8)
    table.add_column("内容", style="white")
    for a in articles:
        content = a["content"][:120].replace("\n", " ") + ("..." if len(a["content"]) > 120 else "")
        table.add_row(f"第{a['article_number']}条", content)
    rprint(table)


@pageindex_cmd.command("toc")
@runnify
async def pageindex_toc(
    law_name: Annotated[str, Argument(help="Law name to show table of contents")],
) -> None:
    pageindex = LawPageIndex()
    toc = await pageindex.aget_law_toc(law_name=law_name)
    if not toc:
        rprint(f"未找到法律 '{law_name}' 的章节目录")
        return
    unit = {"part": "编", "subpart": "分编", "chapter": "章", "section": "节"}
    table = Table(title=f"{law_name} 目录", title_style="bold")
    table.add_column("层级", style="cyan", width=8)
    table.add_column("编号", style="cyan", width=6)
    table.add_column("标题", style="white")

    def _walk(nodes: list[dict], depth: int) -> None:
        for node in nodes:
            u = unit.get(node["node_type"], "")
            num = str(node["number"]) if node.get("number") is not None else "-"
            table.add_row(u, num, f"{'  ' * depth}{node.get('title') or ''}")
            _walk(node.get("children") or [], depth + 1)

    _walk(toc, 0)
    rprint(table)


@pageindex_cmd.command("search")
@runnify
async def pageindex_search(
    law_name: Annotated[str, Argument(help="Law name to search in")],
    query: Annotated[str, Argument(help="Search query")],
    limit: Annotated[int, Option("--limit", "-l", help="Max results")] = 10,
) -> None:
    pageindex = LawPageIndex()
    articles = await pageindex.asearch_articles(law_name=law_name, query=query, limit=limit)
    if not articles:
        rprint(f"在 '{law_name}' 中未找到匹配 '{query}' 的法条")
        return
    table = Table(title=f"搜索结果: '{law_name}' 中的 '{query}'", title_style="bold")
    table.add_column("条号", style="cyan", width=8)
    table.add_column("内容", style="white")
    for a in articles:
        content = a["content"][:150].replace("\n", " ") + ("..." if len(a["content"]) > 150 else "")
        table.add_row(f"第{a['article_number']}条", content)
    rprint(table)


@pageindex_cmd.command("embed")
@runnify
async def pageindex_embed(
    law_name: Annotated[str, Argument(help="Law name to embed from law_articles into documents")] | None = None,
    chunk_size: Annotated[int, Option("--chunk-size", "-s", help="Chunk size in tokens")] = 4096,
    chunk_overlap: Annotated[int, Option("--chunk-overlap", "-o", help="Chunk overlap in tokens")] = 128,
    batch_size: Annotated[int, Option("--batch-size", "-b", help="Articles per batch")] = 64,
) -> None:
    pageindex = LawPageIndex()
    logger.info("开始嵌入法律 '%s' 的法条...", law_name)
    result = await pageindex.aembed_law_articles(
        law_name=law_name,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        batch_size=batch_size,
    )
    rprint(f"嵌入完成: {result['law_name']}")
    rprint(f"  法条数: {result['articles_embedded']}")
    rprint(f"  分块数: {result['chunks_created']}")


spider_cmd = Typer(pretty_exceptions_enable=False, help="法律爬虫命令")


@spider_cmd.command("crawl")
@runnify
async def spider_crawl(
    category: Annotated[
        Literal["xf", "flfg", "xzfg", "jcfg", "sfjs", "dfxfg", "all"],
        Option("--category", "-c", help="Law category to crawl"),
    ] = "all",
    output: Annotated[
        Path | None, Option("--output", "-o", help="Output JSON path (default: data/law_index/law_index.json)")
    ] = None,
) -> None:
    """Stage 1: Crawl the NPC law database API to build a law index.

    This only discovers laws; use 'spider download' to download and parse content.
    Categories: xf (宪法), flfg (法律), xzfg (行政法规), jcfg (监察法规), sfjs (司法解释).
    Use dfxfg for 地方性法规 (excluded from 'all').
    """
    from pathlib import Path

    from lawrag.spider.runner import run_law_index_spider

    logger.info("Running law index spider for category: %s", category)
    out_path = Path(output) if output else None
    await run_law_index_spider(category=category, output=out_path)
    logger.info("Law index crawl completed.")


@spider_cmd.command("download")
@runnify
async def spider_download(
    index_path: Annotated[Path | None, Argument(help="Path to law index JSON file from 'lawrag spider crawl'")] = None,
    output_dir: Annotated[
        Path | None, Option("--output-dir", "-o", help="Output directory for structured law files")
    ] = None,
    download_dir: Annotated[
        Path | None, Option("--download-dir", "-d", help="Directory for raw downloaded docx files")
    ] = None,
    category: Annotated[
        Literal["xf", "flfg", "xzfg", "jcfg", "sfjs", "dfxfg", "all"] | None,
        Option("--category", "-c", help="Filter by category"),
    ] = None,
) -> None:
    """Stage 2+3: Download and parse law content from previously crawled index.

    Downloads docx/HTML from NPC database, converts to text,
    and parses multi-level structure (chapters/sections/articles).
    """
    from lawrag.spider.runner import run_content_download

    if index_path is None:
        index_path = settings.DATA_ROOT / "law_index" / "law_index.json"

    if category == "all":
        category = None  # 'all' means no filtering

    results = await run_content_download(
        index_path=index_path,
        structured_dir=output_dir,
        download_dir=download_dir,
        category=category,
    )
    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] != "ok")
    logger.info("Download+parse completed: %d OK, %d failed", ok, failed)


cmd.add_typer(spider_cmd, name="spider")
cmd.add_typer(pageindex_cmd, name="pageindex")


def main():
    traceback.install()
    uvloop.install()
    logging.captureWarnings(True)

    logging.basicConfig(
        handlers=[RichHandler(rich_tracebacks=True)],
        level=logging.INFO,
    )
    cmd()


if __name__ == "__main__":
    main()
