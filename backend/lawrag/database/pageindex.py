import logging
from itertools import starmap
from pathlib import Path
from uuid import UUID, uuid4

from anyio import Path as AsyncPath
from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import count
from sqlmodel import col

from lawrag.database.document import DocumentStore
from lawrag.documents.lawparser import parse_structured_law

from .database import DatabaseManager
from .tables import DocumentTable, LawNode

logger = logging.getLogger(__name__)

# 参与向量/BM25 召回的节点类型: 条为初筛主体, 编/分编/章/节标题用于索引到上层, 序言作为整体
EMBEDDABLE_NODE_TYPES = ("article", "part", "subpart", "chapter", "section", "preamble")


def _ancestor_titles(p1: LawNode | None, p2: LawNode | None) -> tuple[LawNode | None, LawNode | None]:
    """由一级/二级父节点还原最近的 (章, 节)。用于 article 的章/节定位。"""
    chapter: LawNode | None = None
    section: LawNode | None = None
    for anc in (p1, p2):
        if anc is None:
            continue
        if anc.node_type == "section" and section is None:
            section = anc
        elif anc.node_type == "chapter" and chapter is None:
            chapter = anc
    return chapter, section


def _article_dict(article: LawNode, p1: LawNode | None, p2: LawNode | None) -> dict:
    chapter, section = _ancestor_titles(p1, p2)
    return {
        "id": str(article.id),
        "law_name": article.law_name,
        "article_number": article.number,
        "content": article.content or "",
        "chapter_number": chapter.number if chapter else None,
        "chapter_title": chapter.title if chapter else None,
        "section_number": section.number if section else None,
        "section_title": section.title if section else None,
    }


def _build_embed_text(node: LawNode, p1: LawNode | None, p2: LawNode | None) -> str:
    """为不同层级的节点构造用于嵌入/检索的上下文文本。"""
    law = node.law_name
    if node.node_type == "part":
        return f"《{law}》第{node.number}编 {node.title}"
    if node.node_type == "subpart":
        return f"《{law}》第{node.number}分编 {node.title}"
    if node.node_type == "chapter":
        return f"《{law}》第{node.number}章 {node.title}"
    if node.node_type == "section":
        chapter, _ = _ancestor_titles(p1, p2)
        chapter_part = f"{chapter.title} " if chapter else ""
        return f"《{law}》{chapter_part}第{node.number}节 {node.title}"
    if node.node_type == "preamble":
        return f"《{law}》序言 {node.content}"
    chapter, section = _ancestor_titles(p1, p2)
    prefix = "".join(part for part in (chapter.title if chapter else "", section.title if section else "") if part)
    prefix = f"{prefix} " if prefix else ""
    return f"《{law}》{prefix}第{node.number}条规定，{node.content}。"


class LawPageIndex:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    def _article_query(self, law_name: str | None = None):
        """构造 article 节点及其一级/二级父节点的联表查询。"""
        p1 = aliased(LawNode)
        p2 = aliased(LawNode)
        stmt = (
            select(LawNode, p1, p2)
            .join(p1, col(LawNode.parent_id) == col(p1.id), isouter=True)
            .join(p2, col(p1.parent_id) == col(p2.id), isouter=True)
            .where(col(LawNode.node_type) == "article")
        )
        if law_name is not None:
            stmt = stmt.where(col(LawNode.law_name) == law_name)
        return stmt

    async def aimport_file(
        self,
        file_path: str | Path | AsyncPath,
        category: str | None = None,
    ) -> dict:
        path = AsyncPath(file_path)
        law_name = path.stem
        content = await path.read_text(encoding="utf-8")

        nodes = parse_structured_law(content, law_name=law_name)
        articles = sum(1 for n in nodes if n["node_type"] == "article")
        if articles == 0:
            return {"file": law_name, "status": "empty", "count": 0}

        ids = [uuid4() for _ in nodes]
        values = [
            {
                "id": ids[i],
                "law_name": law_name,
                "parent_id": ids[n["parent"]] if n["parent"] is not None else None,
                "node_type": n["node_type"],
                "number": n["number"],
                "title": n["title"],
                "content": n["content"],
                "order_index": i,
                "path": n["path"],
                "category": category,
            }
            for i, n in enumerate(nodes)
        ]

        async with self.__db.asession() as session:
            # 重新导入前先清空该法律的所有节点, 保证幂等
            await session.execute(delete(LawNode).where(col(LawNode.law_name) == law_name))
            # 单条 INSERT 内父节点先于子节点, 自引用外键在语句结束时校验通过;
            # (law_name, path) 唯一约束 + ON CONFLICT DO NOTHING 兜底防止结构重复插入
            stmt = pg_insert(LawNode).values(values)
            stmt = stmt.on_conflict_do_nothing(index_elements=[col(LawNode.law_name), col(LawNode.path)])
            await session.execute(stmt)
            await session.commit()

        logger.info("Imported %s: %d nodes (%d articles)", law_name, len(nodes), articles)
        return {"file": law_name, "status": "ok", "count": articles}

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
                    logger.exception("Failed to import %s", file_path)
                    results.append({"file": file_path.stem, "status": "error", "count": 0})
        return results

    async def aget_by_law_article(
        self,
        law_name: str,
        article_number: int,
    ) -> dict | None:
        async with self.__db.asession() as session:
            stmt = self._article_query(law_name).where(col(LawNode.number) == article_number)
            result = await session.execute(stmt)
            row = result.first()
            if row is None:
                return None
            return _article_dict(*row)

    async def aget_law_articles(
        self,
        law_name: str,
        start: int | None = None,
        end: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        async with self.__db.asession() as session:
            stmt = self._article_query(law_name)
            if start is not None:
                stmt = stmt.where(col(LawNode.number) >= start)
            if end is not None:
                stmt = stmt.where(col(LawNode.number) <= end)
            stmt = stmt.order_by(col(LawNode.order_index)).offset(offset).limit(limit)
            result = await session.execute(stmt)
            return list(starmap(_article_dict, result.all()))

    async def asearch_articles(
        self,
        law_name: str,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        async with self.__db.asession() as session:
            stmt = (
                self
                ._article_query(law_name)
                .where(col(LawNode.content).ilike(f"%{query}%"))
                .order_by(col(LawNode.order_index))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(starmap(_article_dict, result.all()))

    async def aget_articles_under_chapter(
        self,
        law_name: str,
        chapter_title: str,
        limit: int = 200,
    ) -> list[dict]:
        """返回某一章 (含其下各节) 内的全部法条, 支持"查询某章下的多个法条文本"。"""
        async with self.__db.asession() as session:
            p1 = aliased(LawNode)
            p2 = aliased(LawNode)
            stmt = (
                select(LawNode, p1, p2)
                .join(p1, col(LawNode.parent_id) == col(p1.id), isouter=True)
                .join(p2, col(p1.parent_id) == col(p2.id), isouter=True)
                .where(
                    col(LawNode.law_name) == law_name,
                    col(LawNode.node_type) == "article",
                    (
                        ((col(p1.node_type) == "chapter") & (col(p1.title) == chapter_title))
                        | ((col(p2.node_type) == "chapter") & (col(p2.title) == chapter_title))
                    ),
                )
                .order_by(col(LawNode.order_index))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(starmap(_article_dict, result.all()))

    async def aget_law_toc(self, law_name: str) -> list[dict]:
        """返回一部法律的多级目录 (编/分编/章/节 标题), 供 LLM 索引上层结构。

        以 parent_id 还原树状层级, 每个节点含 ``node_type``/``number``/``title``/``children``。
        """
        async with self.__db.asession() as session:
            stmt = (
                select(LawNode)
                .where(
                    col(LawNode.law_name) == law_name,
                    col(LawNode.node_type).in_(("part", "subpart", "chapter", "section")),
                )
                .order_by(col(LawNode.order_index))
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            entries: dict[UUID, dict] = {
                row.id: {
                    "node_type": row.node_type,
                    "number": row.number,
                    "title": row.title,
                    "children": [],
                    "_parent": row.parent_id,
                }
                for row in rows
            }
            toc: list[dict] = []
            for row in rows:
                entry = entries[row.id]
                parent = entries.get(row.parent_id) if row.parent_id is not None else None
                (parent["children"] if parent is not None else toc).append(entry)
            for entry in entries.values():
                entry.pop("_parent", None)
            return toc

    async def alist_laws(self) -> list[dict]:
        async with self.__db.asession() as session:
            stmt = (
                select(
                    col(LawNode.law_name),
                    count(col(LawNode.id)).label("count"),
                )
                .where(col(LawNode.node_type) == "article")
                .group_by(col(LawNode.law_name))
                .order_by(col(LawNode.law_name))
            )
            result = await session.execute(stmt)
            return [{"law_name": row[0], "article_count": row[1]} for row in result.fetchall()]

    async def adelete_law(self, law_name: str) -> int:
        async with self.__db.asession() as session:
            stmt = (
                delete(LawNode)
                .where(col(LawNode.law_name) == law_name, col(LawNode.node_type) == "article")
                .returning(col(LawNode.id))
            )
            result = await session.execute(stmt)
            article_count = len(result.fetchall())
            # 删除该法律的其余节点 (章/节/序言/根)
            await session.execute(delete(LawNode).where(col(LawNode.law_name) == law_name))
            await session.commit()

            logger.info("Deleted law %s (%d articles)", law_name, article_count)
            return article_count

    async def aembed_law_articles(
        self, law_name: str | None = None, chunk_size: int = 4096, chunk_overlap: int = 128, batch_size: int = 64
    ) -> dict:
        doc_store = DocumentStore()

        offset = 0
        total_nodes = 0
        total_chunks = 0

        while True:
            async with self.__db.asession() as session:
                p1 = aliased(LawNode)
                p2 = aliased(LawNode)
                stmt = (
                    select(LawNode, p1, p2)
                    .join(p1, col(LawNode.parent_id) == col(p1.id), isouter=True)
                    .join(p2, col(p1.parent_id) == col(p2.id), isouter=True)
                    .where(col(LawNode.node_type).in_(EMBEDDABLE_NODE_TYPES))
                    .where(~exists(select(1).where(col(DocumentTable.node_id) == col(LawNode.id))))
                )
                if law_name is not None:
                    stmt = stmt.where(col(LawNode.law_name) == law_name)
                stmt = stmt.order_by(col(LawNode.law_name), col(LawNode.order_index)).offset(offset).limit(batch_size)

                result = await session.execute(stmt)
                rows = result.all()

                if not rows:
                    break

                texts = [
                    (_build_embed_text(node, node_p1, node_p2), node.id, node.law_name)
                    for node, node_p1, node_p2 in rows
                ]

            try:
                chunk_count = await doc_store.abatch_load_from_texts(
                    texts=texts,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                total_chunks += chunk_count
                total_nodes += len(rows)
            except Exception:
                logger.exception("Failed to embed batch of %d nodes for %s", len(rows), law_name)

            offset += batch_size
            logger.info("Embedded %s: %d nodes so far...", law_name, total_nodes)

        logger.info("Embedded %s: %d nodes, %d chunks total", law_name, total_nodes, total_chunks)
        return {
            "law_name": law_name,
            "articles_embedded": total_nodes,
            "chunks_created": total_chunks,
        }
