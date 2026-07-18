import logging
from collections.abc import Sequence
from typing import TypedDict
from uuid import UUID, uuid7

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.functions import count
from sqlmodel import col

from lawrag.chat.model import aembed_documents
from lawrag.documents.lawparser import flatten_hierarchy
from lawrag.documents.models import Document
from lawrag.documents.nlp import asplit_document, atokenize_documents

from .database import DatabaseManager
from .law_index import LawIndexManager
from .tables import DocumentTable, LawNode

logger = logging.getLogger(__name__)

EMBEDDABLE_NODE_TYPES = ("article", "part", "subpart", "chapter", "section", "preamble")

_TYPE_UNIT = {"part": "编", "subpart": "分编", "chapter": "章", "section": "节", "article": "条"}


class ImportResultDict(TypedDict):
    """aimport_laws 返回的导入结果。"""

    file: str
    status: str
    count: int
    inserted: int


class EmbedResultDict(TypedDict):
    """aembed_law_articles 返回的嵌入统计。"""

    law_name: str | None
    articles_embedded: int
    chunks_created: int


def _build_embed_text(node: LawNode) -> str:
    """利用导入时预计算的完整层级路径构造嵌入/检索上下文文本。"""
    fp = node.full_path or ""
    if node.node_type == "article":
        return f"{fp}规定，{node.content or ''}。"
    if node.node_type == "preamble":
        return f"{fp} {node.content or ''}"
    return fp


def _node_seg(node_type: str, number: int | None, title: str | None, law_name: str) -> str:
    if node_type == "law":
        return f"《{law_name}》"
    if node_type == "preamble":
        return "序言"
    unit = _TYPE_UNIT.get(node_type, "")
    if number is not None and unit:
        return f"第{number}{unit} {title or ''}".strip()
    return title or ""


class DocumentStore:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    # ── 法律导入 ──

    async def aimport_parsed(self, law_name: str, parsed: dict, law_index_id: UUID | None = None) -> ImportResultDict:
        nodes = flatten_hierarchy(parsed, law_name)
        articles = sum(1 for n in nodes if n["node_type"] == "article")
        if articles == 0:
            return ImportResultDict(file=law_name, status="empty", count=0, inserted=0)

        ids = [uuid7() for _ in nodes]

        full_paths: list[str] = [""] * len(nodes)
        for i, n in enumerate(nodes):
            seg = _node_seg(n["node_type"], n["number"], n["title"], law_name)
            parent_idx = n["parent"]
            if parent_idx is not None and parent_idx < i:
                full_paths[i] = f"{full_paths[parent_idx]} {seg}".strip()
            else:
                full_paths[i] = seg

        values = [
            {
                "id": ids[i],
                "law_name": law_name,
                "law_index_id": law_index_id,
                "parent_id": ids[n["parent"]] if n["parent"] is not None else None,
                "node_type": n["node_type"],
                "number": n["number"],
                "content": n["title"] or n["content"],
                "path": n["path"],
                "full_path": full_paths[i],
            }
            for i, n in enumerate(nodes)
        ]

        async with self.__db.asession() as session:
            existing_stmt = select(LawNode).where(col(LawNode.law_name) == law_name).limit(1)
            existing_result = await session.execute(existing_stmt)
            existing_row = existing_result.scalar_one_or_none()
            if existing_row is not None:
                logger.info("Law %s already exists in database, skipping import", law_name)
                return ImportResultDict(file=law_name, status="exists", count=articles, inserted=0)

            stmt = (
                insert(LawNode)
                .values(values)
                .on_conflict_do_nothing(index_elements=[col(LawNode.law_name), col(LawNode.path)])
            ).returning(col(LawNode.id))
            result = await session.execute(stmt)
            inserted = len(result.fetchall())

        logger.info("Imported %s: %d nodes (%d articles)", law_name, len(nodes), articles)
        return ImportResultDict(file=law_name, status="ok", count=articles, inserted=inserted)

    async def aimport_laws(self, law_id: UUID | None = None, law_name: str | None = None) -> list[ImportResultDict]:

        lm = LawIndexManager()
        all_entries = await lm.afind_all()
        entries = [e for e in all_entries if e.get("structured") is not None]
        if law_id is not None:
            entries = [e for e in entries if e["id"] == law_id]
        elif law_name is not None:
            entries = [e for e in entries if e["law_name"] == law_name]

        results: list[ImportResultDict] = []
        for entry in entries:
            try:
                logger.info("Importing %s from database...", entry["law_name"])
                structured = entry["structured"]
                assert structured is not None
                result = await self.aimport_parsed(entry["law_name"], structured, law_index_id=entry["id"])
                results.append(result)
            except Exception:
                logger.exception("Failed to import %s", entry["law_name"])
                results.append(ImportResultDict(file=entry["law_name"], status="error", count=0, inserted=0))
        return results

    # ── 文本嵌入 (批量) ──

    async def abatch_load_from_texts(
        self,
        texts: Sequence[tuple[str, UUID, str | None]],
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
    ) -> int:
        all_chunks: list[tuple[UUID, str]] = []

        for content, node_id, name in texts:
            document = Document(content=content, name=name)
            async for chunk in asplit_document(document, chunk_size, chunk_overlap):
                all_chunks.append((node_id, chunk.content))

        if not all_chunks:
            return 0

        documents: list[Document] = [Document(content=c) for _, c in all_chunks]
        documents = await aembed_documents(documents)
        documents = await atokenize_documents(documents)

        insert_values: list[dict] = []
        for i, (node_id, content) in enumerate(all_chunks):
            doc = documents[i]
            insert_values.append({
                "node_id": node_id,
                "content": content,
                "vector": doc.embedding,
                "bmvector": doc.token_count or {},
            })

        sub_batch = 10
        async with self.__db.asession() as session:
            total = 0
            for i in range(0, len(insert_values), sub_batch):
                batch = insert_values[i : i + sub_batch]
                stmt = insert(DocumentTable).values(batch).returning(col(DocumentTable.id))
                result = await session.execute(stmt)
                total += len(result.fetchall())
            await session.commit()

        return total

    # ── 法条嵌入 ──

    async def aembed_laws(
        self,
        law_id: UUID | None = None,
        law_name: str | None = None,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
        batch_size: int = 64,
    ) -> EmbedResultDict:
        label = str(law_id) if law_id else law_name
        total_nodes = 0
        total_chunks = 0

        while True:
            async with self.__db.asession() as session:
                stmt = (
                    select(LawNode)
                    .outerjoin(DocumentTable, col(DocumentTable.node_id) == col(LawNode.id))
                    .where(col(LawNode.node_type).in_(EMBEDDABLE_NODE_TYPES))
                    .where(col(DocumentTable.node_id).is_(None))
                )
                if law_id is not None:
                    stmt = stmt.where(col(LawNode.law_index_id) == law_id)
                elif law_name is not None:
                    stmt = stmt.where(col(LawNode.law_name) == law_name)
                stmt = stmt.order_by(col(LawNode.law_name), col(LawNode.id)).limit(batch_size)

                result = await session.execute(stmt)
                rows = result.scalars().all()

                if not rows:
                    break

                texts = [(_build_embed_text(node), node.id, node.law_name) for node in rows]

            try:
                chunk_count = await self.abatch_load_from_texts(
                    texts=texts,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                total_chunks += chunk_count
                total_nodes += len(rows)
            except Exception:
                logger.exception("Failed to embed batch of %d nodes for %s", len(rows), label)
                continue

            logger.info("Embedded %s: %d nodes so far...", label, total_nodes)

        logger.info("Embedded %s: %d nodes, %d chunks total", label, total_nodes, total_chunks)
        return EmbedResultDict(
            law_name=label,
            articles_embedded=total_nodes,
            chunks_created=total_chunks,
        )

    # ── 文档块删除 ──

    async def adelete_article_chunks(self, node_id: UUID) -> None:
        async with self.__db.asession() as session:
            await session.execute(delete(DocumentTable).where(col(DocumentTable.node_id) == node_id))
            await session.commit()

    async def adelete_law(self, law_name: str) -> int:
        async with self.__db.asession() as session:
            count_stmt = select(count(col(LawNode.id))).where(
                col(LawNode.law_name) == law_name,
                col(LawNode.node_type) == "article",
            )
            result = await session.execute(count_stmt)
            article_count = result.scalar() or 0
            await session.execute(delete(LawNode).where(col(LawNode.law_name) == law_name))
            await session.commit()

            logger.info("Deleted law %s (%d articles)", law_name, article_count)
            return article_count

    async def alist_laws(self) -> list[str]:
        async with self.__db.asession() as session:
            stmt = select(col(LawNode.law_name)).where(col(LawNode.node_type) == "law").distinct()
            result = await session.execute(stmt)
            return [row[0] for row in result.fetchall()]
