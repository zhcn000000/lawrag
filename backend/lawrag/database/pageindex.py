import logging
import pathlib

from sqlalchemy import delete, select
from sqlalchemy import func as sqla_func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from lawrag.documents.lawparser import parse_content

from .database import DatabaseManager
from .tables import DocumentSource, LawArticle


class LawPageIndex:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    async def aimport_file(
        self,
        file_path: str | pathlib.Path,
        category: str | None = None,
    ) -> dict:
        """导入单个 .txt 法律文件, 解析法条并存入 law_articles 和 document_source"""
        path = pathlib.Path(file_path)
        source_name = path.stem
        content = path.read_text(encoding="utf-8")  # noqa: ASYNC240

        articles = parse_content(content)

        if not articles:
            return {"file": source_name, "status": "empty", "count": 0}

        law_name_set = {a[0] for a in articles}
        if len(law_name_set) == 1:
            law_name = law_name_set.pop()
        else:
            law_name = source_name

        async with self.__db.asession() as session:
            stmt = select(col(DocumentSource.id)).where(col(DocumentSource.name) == source_name)
            result = await session.execute(stmt)
            row = result.first()
            if row:
                source_id = row[0]
            else:
                stmt = (
                    insert(DocumentSource)
                    .values(
                        name=source_name,
                        category=category,
                        meta={"law_name": law_name},
                    )
                    .returning(col(DocumentSource.id))
                )
                result = await session.execute(stmt)
                source_id = result.scalar_one()

            count = 0
            for _law_name, article_number, article_content in articles:
                stmt = select(col(LawArticle.id)).where(
                    (col(LawArticle.law_name) == law_name) & (col(LawArticle.article_number) == article_number),
                )
                result = await session.execute(stmt)
                if result.first():
                    continue

                stmt = insert(LawArticle).values(
                    source_id=source_id,
                    law_name=law_name,
                    article_number=article_number,
                    content=article_content,
                )
                await session.execute(stmt)
                count += 1

            await session.commit()

        logging.info("Imported %s: %d articles", source_name, count)
        return {"file": source_name, "status": "ok", "count": count, "source_id": str(source_id)}

    async def aimport_from_dir(
        self,
        dir_path: str | pathlib.Path,
        category: str | None = None,
    ) -> list[dict]:
        """批量导入目录下所有 .txt 法律文件"""
        dir_path = pathlib.Path(dir_path)
        if not dir_path.is_dir():  # noqa: ASYNC240
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        results: list[dict] = []
        for file_path in sorted(dir_path.rglob("*.txt")):
            if file_path.is_file() and not file_path.name.startswith("."):  # noqa: ASYNC240
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
        """按法律名+法条号精确查找"""
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
        """按法条号范围或分页查询某部法律的法条"""
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
        """在指定法律中按内容搜索法条(使用 PostgreSQL ILIKE)"""
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
        """列出所有已导入的法律名称及法条数量"""
        async with self.__db.asession() as session:
            stmt = (
                select(
                    col(LawArticle.law_name),
                    sqla_func.count(col(LawArticle.id)).label("count"),
                )
                .group_by(col(LawArticle.law_name))
                .order_by(col(LawArticle.law_name))
            )
            result = await session.execute(stmt)
            return [{"law_name": row[0], "article_count": row[1]} for row in result.fetchall()]

    async def aenrich_search_results(self, documents: list) -> list[dict]:
        """将向量检索的 Document 结果 补充对应 LawArticle 的精确法条信息"""
        if not documents:
            return []

        enriched: list[dict] = []
        for doc in documents:
            entry: dict = {
                "content": doc.content if hasattr(doc, "content") else doc.get("content", ""),
                "source_name": doc.name if hasattr(doc, "name") else doc.get("name"),
                "score": doc.query_score if hasattr(doc, "query_score") else doc.get("query_score"),
                "document_index": doc.document_index if hasattr(doc, "document_index") else doc.get("document_index"),
                "page_index": doc.page_index if hasattr(doc, "page_index") else doc.get("page_index"),
            }

            source_name = entry["source_name"]
            if source_name:
                try:
                    async with self.__db.asession() as session:
                        stmt = select(col(DocumentSource.meta)).where(
                            col(DocumentSource.name) == source_name,
                        )
                        result = await session.execute(stmt)
                        row = result.first()
                        if row and row[0]:
                            meta = row[0] if isinstance(row[0], dict) else {}
                            law_name = meta.get("law_name", source_name)
                            entry["law_name"] = law_name
                            article_info = meta.get("article_info", {})
                            article_num = article_info.get("article_number") if isinstance(article_info, dict) else None
                            if article_num:
                                article = await self.aget_by_law_article(law_name, article_num)
                                if article:
                                    entry["article"] = article
                except Exception:
                    pass

            enriched.append(entry)

        return enriched

    async def adelete_law(self, law_name: str) -> int:
        """删除某部法律的所有法条, 返回删除的行数"""
        async with self.__db.asession() as session:
            stmt = delete(LawArticle).where(col(LawArticle.law_name) == law_name).returning(col(LawArticle.id))
            result = await session.execute(stmt)
            count = len(result.fetchall())
            await session.commit()

            logging.info("Deleted %d articles from law: %s", count, law_name)
            return count

    async def aembed_law_articles(
        self,
        law_name: str,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
        batch_size: int = 50,
    ) -> dict:
        """从 law_articles 表中取出法条, 流式嵌入到 DocumentTable

        分两步:
        1. 从 law_articles 按法条号流式读取
        2. 每批法条拼接后送入 DocumentStore 嵌入

        Returns: {"law_name": str, "articles_embedded": int, "chunks_created": int}
        """
        from lawrag.database.document import DocumentStore

        doc_store = DocumentStore()

        offset = 0
        total_articles = 0
        total_chunks = 0

        while True:
            async with self.__db.asession() as session:
                stmt = (
                    select(LawArticle)
                    .where(col(LawArticle.law_name) == law_name)
                    .order_by(col(LawArticle.article_number))
                    .offset(offset)
                    .limit(batch_size)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

            if not rows:
                break

            for row in rows:
                article_text = f"《{row.law_name}》第{row.article_number}条规定，{row.content}。"
                try:
                    doc_ids = await doc_store.aload_from_text(
                        content=article_text,
                        source_name=law_name,
                        category="法律",
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        page_index=row.article_number,
                    )
                    total_chunks += len(doc_ids)
                    total_articles += 1
                except Exception:
                    logging.exception("Failed to embed article %s 第%d条", law_name, row.article_number)

            offset += batch_size
            logging.info("Embedded %s: %d articles so far...", law_name, total_articles)

        logging.info("Embedded %s: %d articles, %d chunks total", law_name, total_articles, total_chunks)
        return {
            "law_name": law_name,
            "articles_embedded": total_articles,
            "chunks_created": total_chunks,
        }
