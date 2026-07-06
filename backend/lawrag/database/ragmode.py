from operator import itemgetter
from uuid import UUID

from sqlalchemy import cast, func, select
from sqlalchemy.sql.functions import count
from sqlmodel import col

from lawrag.documents.embedder import aembed_documents, arerank_documents
from lawrag.documents.models import Document
from lawrag.documents.tokenizer import atokenize_document

from .database import DatabaseManager
from .tables import DocumentTable, LawArticle
from .types import BM25Vector


class RAGMode:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    @staticmethod
    async def _vector_search(
        query: str,
        topn: int,
        session,
        regex: str | None = None,
    ) -> list[UUID]:
        query_vectors = await aembed_documents([query])
        query_vector = query_vectors[0]

        stmt = select(col(DocumentTable.id))
        if regex:
            stmt = stmt.where(col(DocumentTable.content).op("~")(regex))
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
        regex: str | None = None,
    ) -> list[UUID]:
        query_count = await atokenize_document(query)

        stmt = select(col(DocumentTable.id))
        if regex:
            stmt = stmt.where(col(DocumentTable.content).op("~")(regex))

        stmt = stmt.order_by(
            col(DocumentTable.bmvector).neg_bm25_rank(  # type: ignore
                func.to_bm25query("idx_documents_bmvector", cast(query_count, BM25Vector)),
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

    async def _get_law_name(self, law_id: UUID | None, session) -> str | None:
        if law_id is None:
            return None
        stmt = select(col(LawArticle.law_name)).where(col(LawArticle.id) == law_id)
        result = await session.execute(stmt)
        row = result.first()
        return row[0] if row else None

    async def _fetch_documents(self, doc_ids: list[UUID], session) -> list[Document]:
        if not doc_ids:
            return []
        stmt = select(DocumentTable).where(col(DocumentTable.id).in_(doc_ids))
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            Document(
                content=row.content or "",
                name=await self._get_law_name(row.law_id, session),
                id=row.id,
            )
            for row in rows
        ]

    async def ahyprid_search(
        self,
        query: str,
        k: int = 4,
        regex: str | None = None,
        vector_weight: float = 0.6,
        bm25_weight: float = 0.4,
        offset: int = 0,
        use_rerank: bool = True,
    ) -> list[Document]:
        async with self.__db.asession() as session:
            search_topn = max(k * 3, 15)

            vector_ids = await self._vector_search(
                query=query,
                topn=search_topn,
                session=session,
                regex=regex,
            )

            bm25_ids = await self._bm25_search(
                query=query,
                topn=search_topn,
                session=session,
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
            fused_ids = fused_ids[offset : offset + k]

            documents = await self._fetch_documents(fused_ids, session)

            if use_rerank:
                documents = await arerank_documents(query, documents, topn=k)

            for doc in documents:
                doc.query_score = doc.query_score or 0.0

            documents.sort(key=lambda d: d.query_score or 0, reverse=True)
            return documents

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
