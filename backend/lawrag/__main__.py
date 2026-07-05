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

from lawrag.database.document import DocumentStore
from lawrag.database.initdb import clean_db, init_db, reset_db
from lawrag.database.ragmode import RAGMode
from lawrag.routers import app
from lawrag.utils.environments import settings

cmd = Typer(pretty_exceptions_enable=False)
ingest_cmd = Typer(pretty_exceptions_enable=False, help="文档摄入命令")


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
    page_index: Annotated[int | None, Option("--page", "-p", help="Filter by page index")] = None,
) -> None:
    rag = RAGMode()
    docs = await rag.ahyprid_search(
        query=query,
        k=k,
        page_index=page_index,
    )

    if docs:
        table = Table(title=f'搜索结果: "{query}"', title_style="bold")
        table.add_column("score", style="cyan", width=8)
        table.add_column("title", style="green", width=30)
        table.add_column("page", style="yellow", width=6)
        table.add_column("content", style="white")
        for doc in docs:
            score = f"{doc.query_score:.4f}" if doc.query_score else "N/A"
            name = doc.name or "Untitled"
            page = str(doc.page_index) if doc.page_index is not None else "-"
            content = doc.content[:100].replace("\n", " ") + ("..." if len(doc.content) > 100 else "")
            table.add_row(score, name, page, content)
        rprint(table)
    else:
        rprint("无搜索结果")


@ingest_cmd.command("dir")
@runnify
async def ingest_dir(
    dir_path: Annotated[Path, Argument(help="Directory path containing documents to ingest")],
    category: Annotated[str | None, Option("--category", "-c", help="Category for the documents")] = None,
    chunk_size: Annotated[int, Option("--chunk-size", "-s", help="Chunk size in tokens")] = 4096,
    chunk_overlap: Annotated[int, Option("--chunk-overlap", "-o", help="Chunk overlap in tokens")] = 128,
) -> None:
    store = DocumentStore()
    results = await store.aload_documents_from_dir(
        dir_path=dir_path,
        category=category,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    total = sum(len(ids) for ids in results.values())
    logging.info("已导入 %d 个文档，共 %d 个分块", len(results), total)


@ingest_cmd.command("file")
@runnify
async def ingest_file(
    file_path: Annotated[Path, Argument(help="Path to the file to ingest")],
    category: Annotated[str | None, Option("--category", "-c", help="Category for the document")] = None,
) -> None:
    store = DocumentStore()
    doc_ids = await store.aload_from_file(file_path=file_path, category=category)
    logging.info("已导入 %d 个分块", len(doc_ids))


cmd.add_typer(ingest_cmd, name="ingest")


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
