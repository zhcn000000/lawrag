from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from lawrag.documents.embedder import aembed_documents
from lawrag.documents.models import Document
from lawrag.documents.splitter import asplit_document
from lawrag.documents.tokenizer import atokenize_document

from .database import DatabaseManager
from .tables import DocumentTable


class DocumentStore:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    async def _ingest_document(
        self,
        document: Document,
        node_id: UUID,
        chunk_size: int = 512,
        chunk_overlap: int = 32,
    ) -> list[UUID]:
        chunks: list[Document] = []
        async for chunk in asplit_document(document, chunk_size, chunk_overlap):
            chunks.append(chunk)

        if not chunks:
            return []

        contents = [c.content for c in chunks]
        embeddings = await aembed_documents(contents)

        doc_ids: list[UUID] = []
        for i, chunk in enumerate(chunks):
            bmvector = await atokenize_document(chunk.content)
            embeddings_i = embeddings[i] if i < len(embeddings) else []

            async with self.__db.asession() as session:
                stmt = (
                    insert(DocumentTable)
                    .values(
                        node_id=node_id,
                        content=chunk.content,
                        vector=embeddings_i,
                        bmvector=dict(bmvector),
                    )
                    .returning(col(DocumentTable.id))
                )
                result = await session.execute(stmt)
                doc_id = result.scalar_one()
                doc_ids.append(doc_id)
        return doc_ids

    async def aload_from_text(
        self,
        content: str,
        node_id: UUID,
        name: str | None = None,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
    ) -> list[UUID]:
        document = Document(content=content, name=name)
        return await self._ingest_document(
            document=document,
            node_id=node_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

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

        contents = [c[1] for c in all_chunks]
        embeddings = await aembed_documents(contents)

        insert_values: list[dict] = []
        for i, (node_id, content) in enumerate(all_chunks):
            bmvector = await atokenize_document(content)
            embeddings_i = embeddings[i] if i < len(embeddings) else []
            insert_values.append({
                "node_id": node_id,
                "content": content,
                "vector": embeddings_i,
                "bmvector": dict(bmvector),
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

    async def adelete_article_chunks(self, node_id: UUID) -> None:
        async with self.__db.asession() as session:
            await session.execute(delete(DocumentTable).where(col(DocumentTable.node_id) == node_id))
            await session.commit()
