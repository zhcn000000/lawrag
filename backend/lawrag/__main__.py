import json
import logging
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
import uvloop
from asyncer import runnify
from pydantic import TypeAdapter
from rich import print, traceback
from rich.logging import RichHandler
from rich.table import Table
from typer import Argument, Option, Typer

from lawrag.chat.agent import ModelDeps, agent
from lawrag.database.document import DocumentStore
from lawrag.database.initdb import clean_db, init_db, reset_db
from lawrag.database.law_index import LawIndexManager
from lawrag.database.pageindex import LawPageIndex, TocEntryDict
from lawrag.database.ragsearch import RAGSearch
from lawrag.documents.lawparser import has_parsed_content, parse_multi_level
from lawrag.environments import find_project_directory, settings
from lawrag.eval.dataset import LawRagCase, LawRagCaseFailure, LawRagCaseReport
from lawrag.eval.eval import evaluate
from lawrag.routers import app
from lawrag.spider.runner import run_content_download, run_law_index_spider

logger = logging.getLogger(__name__)

cmd = Typer(pretty_exceptions_enable=False)
database_cmd = Typer(pretty_exceptions_enable=False, help="数据库操作命令")
pageindex_cmd = Typer(pretty_exceptions_enable=False, help="法条索引命令")
spider_cmd = Typer(pretty_exceptions_enable=False, help="法律爬虫命令")


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
async def cli(
    tools: Annotated[
        list[str] | None,
        Option("--tools", "-t", help="Available tools"),
    ] = None,
) -> None:
    """启动交互式命令行"""
    if tools is None:
        toolsets = frozenset({"rag_toolkit", "code_toolkit", "web_toolkit", "subagent_toolkit"})
    else:
        for t in tools:
            if t not in {"rag_toolkit", "code_toolkit", "web_toolkit", "subagent_toolkit"}:
                raise ValueError(f"未知工具: {t}")
        toolsets = frozenset(tools)
    await agent.to_cli(
        ModelDeps(select_toolset=toolsets),  # type: ignore
    )


@cmd.command("search")
@runnify
async def search(
    query: Annotated[str, Argument(help="Search query")],
    law_name: Annotated[str | None, Option("--law", "-l", help="Filter by law name")] = None,
    regex: Annotated[str | None, Option("--regex", "-r", help="Filter by regex pattern")] = None,
    limit: Annotated[int, Option("--limit", "-k", help="Number of results")] = 5,
    vecweight: Annotated[float, Option("--vector-weight", "-v", help="Vector search weight")] = 0.6,
) -> None:
    rag = RAGSearch()
    docs = await rag.ahyprid_search(
        query=query,
        limit=limit,
        law_name=law_name,
        regex=regex,
        vecweight=vecweight,
    )

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
        print(table)
    else:
        print("无搜索结果")


@cmd.command("eval")
@runnify
async def eval(
    input: Annotated[Path | None, Option("--input", "-i", help="评估样本 JSON 输入路径")] = None,
    output: Annotated[Path | None, Option("--output", "-o", help="评估报告 JSON 输出路径")] = None,
    start: Annotated[int, Option("--start", "-s", help="评估样本起始索引")] = 0,
    end: Annotated[int, Option("--end", "-e", "-n", help="评估样本结束索引")] = -1,
    offline: Annotated[bool, Option("--offline", "-f", help="是否离线评估, 禁用 web_toolkit等联网工具")] = False,
) -> None:
    """运行法律问答测试集, 用 LLM 裁判评估 Agent 输出并生成报告。

    从 JSON 测试集文件 (默认 ``examples/case.json``) 读取问答样本, 逐条调用 Agent 生成回答,
    与标准答案对比后由 LLM 裁判判定是否通过, 结果以 rich 表格展示并写入 JSON。
    """
    if output is None:
        output = Path("lawrag_eval_report.json")

    if input is None:
        input = find_project_directory() / "examples" / "case.json"

    cases = TypeAdapter(list[LawRagCase]).validate_json(input.read_bytes())

    logger.info("开始评估 (最多 %s 条样本)...", end if end != -1 else "全部")
    reports = await evaluate(cases, start=start, end=end, offline=offline)

    passed = sum(1 for r in reports if r.success)
    total = len(reports)
    table = Table(title=f"法律问答评估结果 (通过 {passed}/{total})", title_style="bold")
    table.add_column("结果", width=6)
    table.add_column("问题", style="green", width=40)
    table.add_column("评价", style="white")
    for r in reports:
        mark = "[green]PASS[/green]" if r.success else "[red]FAIL[/red]"
        question = r.question.strip().replace("\n", " ")
        question = question[:38] + ("..." if len(question) > 38 else "")
        note = r.evaluation_note if isinstance(r, LawRagCaseReport) else r.error_message
        note = note.strip().replace("\n", " ")
        note = note[:80] + ("..." if len(note) > 80 else "")
        table.add_row(mark, question, note)
    print(table)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        TypeAdapter(list[LawRagCaseReport | LawRagCaseFailure]).dump_json(reports, indent=2, ensure_ascii=False),
    )
    rate = passed / total if total else 0.0
    print(f"通过率: {rate:.1%} ({passed}/{total})")
    print(f"报告已写入: {output}")


@database_cmd.command("init")
@runnify
async def database_init(
    dbname: Annotated[str | None, Option("--dbname", "-d", help="Name of the database to initialize")] = None,
) -> None:
    await init_db(dbname=dbname)


@database_cmd.command("reset")
@runnify
async def database_reset(
    dbname: Annotated[str | None, Option("--dbname", "-d", help="Name of the database to reset")] = None,
) -> None:
    await reset_db(dbname=dbname)


@database_cmd.command("clean")
@runnify
async def database_clean(
    dbname: Annotated[str | None, Option("--dbname", "-d", help="Name of the database to clean")] = None,
) -> None:
    await clean_db(dbname=dbname)


@pageindex_cmd.command("import")
@runnify
async def pageindex_import(
    law_name: Annotated[str | None, Option("--law", "-l", help="Import specific law by name from DB")] = None,
) -> None:
    docstore = DocumentStore()
    results = await docstore.aimport_laws(law_name=law_name)
    total = sum(r.get("count", 0) for r in results)
    ok = sum(1 for r in results if r.get("status") == "ok")
    error = sum(1 for r in results if r.get("status") == "error")
    logger.info("导入完成: %d 个文件, 共 %d 条法条 (成功 %d, 失败 %d)", len(results), total, ok, error)


@pageindex_cmd.command("list")
@runnify
async def pageindex_list() -> None:
    pageindex = LawPageIndex()
    laws = await pageindex.afind_laws()
    if not laws:
        print("暂无已导入的法律")
        return
    table = Table(title="已导入法律列表", title_style="bold")
    table.add_column("法律名称", style="green")
    table.add_column("法条数量", style="cyan", justify="right")
    for law in laws:
        table.add_row(law["law_name"], str(law["article_count"]))
    print(table)


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
        print(f"未找到法律 '{law_name}' 的法条")
        return
    table = Table(title=f"{law_name} 法条列表", title_style="bold")
    table.add_column("条号", style="cyan", width=8)
    table.add_column("内容", style="white")
    for a in articles:
        content = a["content"][:120].replace("\n", " ") + ("..." if len(a["content"]) > 120 else "")
        table.add_row(f"第{a['article_number']}条", content)
    print(table)


@pageindex_cmd.command("toc")
@runnify
async def pageindex_toc(
    law_name: Annotated[str, Argument(help="Law name to show table of contents")],
) -> None:
    pageindex = LawPageIndex()
    toc = await pageindex.aget_law_toc(law_name=law_name)
    if not toc:
        print(f"未找到法律 '{law_name}' 的章节目录")
        return
    unit = {"part": "编", "subpart": "分编", "chapter": "章", "section": "节"}
    table = Table(title=f"{law_name} 目录", title_style="bold")
    table.add_column("层级", style="cyan", width=8)
    table.add_column("编号", style="cyan", width=6)
    table.add_column("标题", style="white")

    def _walk(nodes: list[TocEntryDict], depth: int) -> None:
        for node in nodes:
            u = unit.get(node["node_type"], "")
            num = str(node["number"]) if node.get("number") is not None else "-"
            table.add_row(u, num, f"{'  ' * depth}{node.get('title') or ''}")
            _walk(node.get("children") or [], depth + 1)

    _walk(toc, 0)
    print(table)


@pageindex_cmd.command("embed")
@runnify
async def pageindex_embed(
    law_name: Annotated[str, Argument(help="Law name to embed from law_articles into documents")] | None = None,
    chunk_size: Annotated[int, Option("--chunk-size", "-s", help="Chunk size in tokens")] = 4096,
    chunk_overlap: Annotated[int, Option("--chunk-overlap", "-o", help="Chunk overlap in tokens")] = 128,
    batch_size: Annotated[int, Option("--batch-size", "-b", help="Articles per batch")] = 64,
) -> None:
    docstore = DocumentStore()
    logger.info("开始嵌入法律 '%s' 的法条...", law_name)
    result = await docstore.aembed_laws(
        law_name=law_name,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        batch_size=batch_size,
    )
    print(f"嵌入完成: {result['law_name']}")
    print(f"  法条数: {result['articles_embedded']}")
    print(f"  分块数: {result['chunks_created']}")


@pageindex_cmd.command("convert")
@runnify
async def pageindex_convert(
    raw_dir: Annotated[Path | None, Option("--raw-dir", "-r", help="raw_laws 目录路径 (文件回退)")] = None,
    output_dir: Annotated[Path | None, Option("--output-dir", "-o", help="输出目录 (文件回退)")] = None,
    filter_name: Annotated[str | None, Option("--filter", "-f", help="仅转换名称包含此关键词的法律")] = None,
) -> None:
    """从数据库 raw 文本重新解析并更新 structured 数据。

    默认从 law_index 表读取 raw 文本, 运行 parse_multi_level 解析层级结构,
    将结果写回 law_index.structured。指定 --raw-dir/--output-dir 时回退到文件模式。
    """
    if raw_dir is not None or output_dir is not None:
        if raw_dir is None:
            raw_dir = settings.DATA_ROOT / "raw_laws"
        if output_dir is None:
            output_dir = settings.DATA_ROOT / "structured_laws"

        output_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict] = []
        for file in sorted(raw_dir.rglob("*.txt")):
            if file.name.startswith("."):
                continue
            law_name = file.stem
            if filter_name and filter_name not in law_name:
                continue
            try:
                text = file.read_text(encoding="utf-8")
                parsed = parse_multi_level(text)
                if not has_parsed_content(parsed):
                    logger.warning("跳过 %s: 无法解析内容", law_name)
                    results.append({"law_name": law_name, "status": "skipped"})
                    continue
                target = output_dir / f"{law_name}.json"
                target.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
                results.append({"law_name": law_name, "status": "ok"})
            except Exception:
                logger.exception("转换失败: %s", law_name)
                results.append({"law_name": law_name, "status": "error"})

        ok = sum(1 for r in results if r["status"] == "ok")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        errors = sum(1 for r in results if r["status"] == "error")
        logger.info("转换完成: %d OK, %d 跳过, %d 失败 (共 %d)", ok, skipped, errors, len(results))
        return

    lm = LawIndexManager()
    entries = await lm.afind_all(has_raw=True)

    results: list[dict] = []
    for entry in entries:
        law_name = entry["law_name"]
        if filter_name and filter_name not in law_name:
            continue
        try:
            text = entry["raw"]
            if not text:
                results.append({"law_name": law_name, "status": "skipped"})
                continue
            parsed = parse_multi_level(text)
            if not has_parsed_content(parsed):
                logger.warning("跳过 %s: 无法解析内容", law_name)
                results.append({"law_name": law_name, "status": "skipped"})
                continue
            await lm.aset_structured(entry["law_id"], parsed)
            results.append({"law_name": law_name, "status": "ok"})
        except Exception:
            logger.exception("转换失败: %s", law_name)
            results.append({"law_name": law_name, "status": "error"})

    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors = sum(1 for r in results if r["status"] == "error")
    logger.info("转换完成: %d OK, %d 跳过, %d 失败 (共 %d)", ok, skipped, errors, len(results))


@spider_cmd.command("crawl")
@runnify
async def spider_crawl(
    category: Annotated[
        Literal["xf", "flfg", "xzfg", "jcfg", "sfjs", "dfxfg", "all"],
        Option("--category", "-c", help="Law category to crawl"),
    ] = "all",
) -> None:
    """Stage 1: Crawl the NPC law database API to build a law index.

    This only discovers laws; use 'spider download' to download and parse content.
    Categories: xf (宪法), flfg (法律), xzfg (行政法规), jcfg (监察法规), sfjs (司法解释).
    Use dfxfg for 地方性法规 (excluded from 'all').
    """
    logger.info("Running law index spider for category: %s", category)

    await run_law_index_spider(category=category)
    logger.info("Law index crawl completed.")


@spider_cmd.command("download")
@runnify
async def spider_download() -> None:
    """Stage 2+3: Download and parse law content from the NPC database.

    Downloads docx/HTML via signed URLs, converts to text with markitdown,
    parses multi-level structure, and stores results in the law_index DB table.
    """
    await run_content_download()
    logger.info("Download+parse completed.")


cmd.add_typer(spider_cmd, name="spider")
cmd.add_typer(pageindex_cmd, name="pageindex")
cmd.add_typer(database_cmd, name="database")


def main():
    traceback.install()
    uvloop.install()
    logging.captureWarnings(True)

    logging.basicConfig(
        handlers=[RichHandler(rich_tracebacks=True)],
        level=settings.LOG_LEVEL,
    )
    cmd()


if __name__ == "__main__":
    main()
