from uuid import UUID

from sqlalchemy import delete, insert
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
        law_id: UUID,
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
                        law_id=law_id,
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
        law_id: UUID,
        name: str | None = None,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
    ) -> list[UUID]:
        document = Document(content=content, name=name)
        return await self._ingest_document(
            document=document,
            law_id=law_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def adelete_article_chunks(self, law_id: UUID) -> None:
        async with self.__db.asession() as session:
            await session.execute(delete(DocumentTable).where(col(DocumentTable.law_id) == law_id))
            await session.commit()
