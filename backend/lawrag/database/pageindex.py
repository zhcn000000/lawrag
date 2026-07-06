import logging
from pathlib import Path

from anyio import Path as AsyncPath
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.functions import count
from sqlmodel import col

from lawrag.database.document import DocumentStore
from lawrag.documents.lawparser import parse_content

from .database import DatabaseManager
from .tables import LawArticle


class LawPageIndex:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    async def aimport_file(
        self,
        file_path: str | Path | AsyncPath,
        category: str | None = None,
    ) -> dict:
        path = AsyncPath(file_path)
        source_name = path.stem
        content = await path.read_text(encoding="utf-8")

        articles = parse_content(content)

        if not articles:
            return {"file": source_name, "status": "empty", "count": 0}

        values = [
            {
                "law_name": law_name,
                "article_number": article_number,
                "content": article_content,
                "category": category,
            }
            for law_name, article_number, article_content in articles
        ]

        async with self.__db.asession() as session:
            stmt = (
                insert(LawArticle)
                .values(values)
                .on_conflict_do_nothing(constraint="uq_law_article")
                .returning(col(LawArticle.id))
            )
            result = await session.execute(stmt)
            row_count = len(result.fetchall())
            await session.commit()

        logging.info("Imported %s: %d articles", source_name, row_count)
        return {"file": source_name, "status": "ok", "count": row_count}

    async def aimport_from_dir(
        self,
        dir_path: str | Path | AsyncPath,
        category: str | None = None,
    ) -> list[dict]:
        path = AsyncPath(dir_path)
        if not await path.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        results: list[dict] = []
        paths = sorted([file_path async for file_path in path.rglob("*.txt")])

        for file_path in paths:
            if await file_path.is_file() and not file_path.name.startswith("."):
                try:
                    result = await self.aimport_file(file_path=file_path, category=category)
                    results.append(result)
                except Exception:
                    logging.exception("Failed to import %s", file_path)
                    results.append({"file": file_path.stem, "status": "error", "count": 0})
        return results

    async def aget_by_law_article(
        self,
        law_name: str,
        article_number: int,
    ) -> dict | None:
        async with self.__db.asession() as session:
            stmt = select(LawArticle).where(
                (col(LawArticle.law_name) == law_name) & (col(LawArticle.article_number) == article_number),
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return None
            return {
                "id": str(row.id),
                "law_name": row.law_name,
                "article_number": row.article_number,
                "content": row.content,
                "metadata": row.meta,
            }

    async def aget_law_articles(
        self,
        law_name: str,
        start: int | None = None,
        end: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        async with self.__db.asession() as session:
            stmt = select(LawArticle).where(col(LawArticle.law_name) == law_name)
            if start is not None:
                stmt = stmt.where(col(LawArticle.article_number) >= start)
            if end is not None:
                stmt = stmt.where(col(LawArticle.article_number) <= end)
            stmt = stmt.order_by(col(LawArticle.article_number)).offset(offset).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "id": str(row.id),
                    "law_name": row.law_name,
                    "article_number": row.article_number,
                    "content": row.content,
                }
                for row in rows
            ]

    async def asearch_articles(
        self,
        law_name: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        async with self.__db.asession() as session:
            stmt = (
                select(LawArticle)
                .where(
                    (col(LawArticle.law_name) == law_name) & col(LawArticle.content).ilike(f"%{query}%"),
                )
                .order_by(col(LawArticle.article_number))
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "id": str(row.id),
                    "law_name": row.law_name,
                    "article_number": row.article_number,
                    "content": row.content,
                }
                for row in rows
            ]

    async def alist_laws(self) -> list[dict]:
        async with self.__db.asession() as session:
            stmt = (
                select(
                    col(LawArticle.law_name),
                    count(col(LawArticle.id)).label("count"),
                )
                .group_by(col(LawArticle.law_name))
                .order_by(col(LawArticle.law_name))
            )
            result = await session.execute(stmt)
            return [{"law_name": row[0], "article_count": row[1]} for row in result.fetchall()]

    async def adelete_law(self, law_name: str) -> int:
        async with self.__db.asession() as session:
            stmt = delete(LawArticle).where(col(LawArticle.law_name) == law_name).returning(col(LawArticle.id))
            result = await session.execute(stmt)
            count = len(result.fetchall())
            await session.commit()

            logging.info("Deleted %d articles from law: %s", count, law_name)
            return count

    async def aembed_law_articles(
        self,
        law_name: str | None = None,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
        batch_size: int = 50,
    ) -> dict:

        doc_store = DocumentStore()

        offset = 0
        total_articles = 0
        total_chunks = 0

        while True:
            async with self.__db.asession() as session:
                stmt = select(LawArticle)
                if law_name is not None:
                    stmt = stmt.where(col(LawArticle.law_name) == law_name).order_by(col(LawArticle.law_name))
                stmt = stmt.order_by(col(LawArticle.article_number)).offset(offset).limit(batch_size)
                result = await session.execute(stmt)
                rows = result.scalars().all()

            if not rows:
                break

            texts = [
                (
                    f"《{row.law_name}》第{row.article_number}条规定，{row.content}。",
                    row.id,
                    law_name,
                )
                for row in rows
            ]

            try:
                chunk_count = await doc_store.abatch_load_from_texts(
                    texts=texts,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                total_chunks += chunk_count
                total_articles += len(rows)
            except Exception:
                logging.exception("Failed to embed batch of %d articles for %s", len(rows), law_name)

            offset += batch_size
            logging.info("Embedded %s: %d articles so far...", law_name, total_articles)

        logging.info("Embedded %s: %d articles, %d chunks total", law_name, total_articles, total_chunks)
        return {
            "law_name": law_name,
            "articles_embedded": total_articles,
            "chunks_created": total_chunks,
        }
