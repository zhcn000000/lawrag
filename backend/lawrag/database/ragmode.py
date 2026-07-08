from operator import itemgetter
from uuid import UUID

from sqlalchemy import cast, func, select
from sqlalchemy.sql.functions import count
from sqlmodel import col

from lawrag.documents.embedder import aembed_documents, arerank_documents
from lawrag.documents.models import Document
from lawrag.documents.tokenizer import atokenize_document

from .database import DatabaseManager
from .tables import DocumentTable, LawNode
from .types import BM25Vector

_NODE_LABEL_UNIT = {
    "part": "编",
    "subpart": "分编",
    "chapter": "章",
    "section": "节",
    "article": "条",
}


def _node_label(node: LawNode) -> str:
    """单个节点在面包屑中的展示文本。"""
    if node.node_type == "law":
        return node.law_name
    if node.node_type == "preamble":
        return "序言"
    unit = _NODE_LABEL_UNIT.get(node.node_type, "")
    head = f"第{node.number}{unit}" if node.number is not None else unit
    return f"{head} {node.content}".strip() if node.content else head


def _node_breadcrumb(node: LawNode, node_map: dict[UUID, LawNode]) -> str:
    """沿 parent_id 上溯构造多级 page index 面包屑,
    例如 '民法典 > 第一编 总则 > 第二章 自然人 > 第一节 ... > 第十三条'。
    """
    labels: list[str] = []
    current: LawNode | None = node
    seen: set[UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        labels.append(_node_label(current))
        current = node_map.get(current.parent_id) if current.parent_id is not None else None
    return " > ".join(reversed(labels))


class RAGMode:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    @staticmethod
    async def _vector_search(
        query: str,
        topn: int,
        session,
        law_name: str | None = None,
        regex: str | None = None,
    ) -> list[UUID]:
        query_vectors = await aembed_documents([query])
        query_vector = query_vectors[0]

        stmt = select(col(DocumentTable.id))
        if law_name:
            stmt = stmt.where(
                col(DocumentTable.node_id).in_(
                    select(col(LawNode.id)).where(col(LawNode.law_name) == law_name),
                ),
            )
        if regex:
            stmt = stmt.where(col(DocumentTable.content).regexp_match(regex))
        stmt = stmt.order_by(
            col(DocumentTable.vector).l2_distance(query_vector),  # type: ignore
        ).limit(topn)

        result = await session.execute(stmt)
        return [row[0] for row in result.fetchall()]

    @staticmethod
    async def _bm25_search(
        query: str,
        topn: int,
        session,
        law_name: str | None = None,
        regex: str | None = None,
    ) -> list[UUID]:
        query_count = await atokenize_document(query)

        stmt = select(col(DocumentTable.id))
        if law_name:
            stmt = stmt.where(
                col(DocumentTable.node_id).in_(
                    select(col(LawNode.id)).where(col(LawNode.law_name) == law_name),
                ),
            )
        if regex:
            stmt = stmt.where(col(DocumentTable.content).regexp_match(regex))

        stmt = stmt.order_by(
            col(DocumentTable.bmvector).neg_bm25_rank(  # type: ignore
                func.to_bm25query("ix_documents_bmvector", cast(query_count, BM25Vector)),
            ),
        ).limit(topn)

        result = await session.execute(stmt)
        return [row[0] for row in result.fetchall()]

    @staticmethod
    def _rrf_fusion(
        ranked_lists: list[list[UUID]],
        k: int = 60,
        topn: int = 10,
    ) -> list[UUID]:
        scores: dict[UUID, float] = {}
        for ranked_ids in ranked_lists:
            for rank, doc_id in enumerate(ranked_ids):
                scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)
        sorted_ids = sorted(scores.items(), key=itemgetter(1), reverse=True)
        return [doc_id for doc_id, _ in sorted_ids[:topn]]

    @staticmethod
    async def _load_nodes_with_ancestors(node_ids: list[UUID], session) -> dict[UUID, LawNode]:
        """加载给定节点及其全部祖先 (沿 parent_id 逐层上溯)。"""
        node_map: dict[UUID, LawNode] = {}
        pending: set[UUID] = set(node_ids)
        while pending:
            rows = (await session.execute(select(LawNode).where(col(LawNode.id).in_(pending)))).scalars().all()
            pending = set()
            for node in rows:
                node_map[node.id] = node
                if node.parent_id is not None and node.parent_id not in node_map:
                    pending.add(node.parent_id)
        return node_map

    async def _fetch_documents(self, doc_ids: list[UUID], session) -> list[Document]:
        if not doc_ids:
            return []
        stmt = select(DocumentTable).where(col(DocumentTable.id).in_(doc_ids))
        result = await session.execute(stmt)
        rows = result.scalars().all()

        node_ids = [row.node_id for row in rows if row.node_id is not None]
        node_map = await self._load_nodes_with_ancestors(node_ids, session)

        documents: list[Document] = []
        for row in rows:
            node = node_map.get(row.node_id) if row.node_id is not None else None
            documents.append(
                Document(
                    content=row.content or "",
                    name=node.law_name if node else None,
                    page_index=_node_breadcrumb(node, node_map) if node else None,
                    node_path=node.path if node else None,
                    id=row.id,
                ),
            )
        return documents

    async def ahyprid_search(
        self,
        query: str,
        limit: int = 4,
        law_name: str | None = None,
        regex: str | None = None,
        vector_weight: float = 0.6,
        bm25_weight: float = 0.4,
        offset: int = 0,
        use_rerank: bool = True,
    ) -> list[Document]:
        async with self.__db.asession() as session:
            search_topn = max(limit * 3, 15)

            vector_ids = await self._vector_search(
                query=query,
                topn=search_topn,
                session=session,
                law_name=law_name,
                regex=regex,
            )

            bm25_ids = await self._bm25_search(
                query=query,
                topn=search_topn,
                session=session,
                law_name=law_name,
                regex=regex,
            )

            ranked_lists: list[list[UUID]] = []
            if vector_weight > 0 and vector_ids:
                ranked_lists.append(vector_ids)
            if bm25_weight > 0 and bm25_ids:
                ranked_lists.append(bm25_ids)

            if not ranked_lists:
                return []

            fused_ids = self._rrf_fusion(ranked_lists, topn=search_topn)
            fused_ids = fused_ids[offset : offset + limit]

            documents = await self._fetch_documents(fused_ids, session)

            if use_rerank:
                documents = await arerank_documents(query, documents, topn=limit)

            for doc in documents:
                doc.query_score = doc.query_score or 0.0

            documents.sort(key=lambda d: d.query_score or 0, reverse=True)
            return documents

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
