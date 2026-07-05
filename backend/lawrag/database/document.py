import logging
import pathlib
from uuid import UUID

from sqlalchemy import select
from sqlmodel import col

from lawrag.documents.converter import aconvert_file
from lawrag.documents.embedder import aembed_documents
from lawrag.documents.models import Document
from lawrag.documents.splitter import asplit_document
from lawrag.documents.tokenizer import atokenize_document

from .database import DatabaseManager
from .tables import DocumentSource, DocumentTable


class DocumentStore:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    async def acreate_source(
        self,
        name: str,
        category: str | None = None,
        link: str | None = None,
        metadata: dict | None = None,
    ) -> UUID:
        async with self.__db.asession() as session:
            source = DocumentSource(
                name=name,
                category=category,
                link=link,
                meta=metadata or {},
            )  # type: ignore
            session.add(source)
            await session.commit()
            await session.refresh(source)
            return source.id

    async def aget_or_create_source(
        self,
        name: str,
        category: str | None = None,
        link: str | None = None,
    ) -> UUID:
        async with self.__db.asession() as session:
            stmt = select(col(DocumentSource.id)).where(col(DocumentSource.name) == name)
            result = await session.execute(stmt)
            row = result.first()
            if row:
                return row[0]
        return await self.acreate_source(name=name, category=category, link=link)

    async def _ingest_document(
        self,
        document: Document,
        source_id: UUID,
        chunk_size: int = 512,
        chunk_overlap: int = 32,
        offset: int = 0,
    ) -> list[UUID]:
        chunks: list[Document] = []
        page_idx = 0
        async for chunk in asplit_document(document, chunk_size, chunk_overlap):
            chunk.document_index = offset + page_idx
            chunk.page_index = document.page_index
            chunks.append(chunk)
            page_idx += 1

        if not chunks:
            return []

        contents = [c.content for c in chunks]
        embeddings = await aembed_documents(contents)

        doc_ids: list[UUID] = []
        for i, chunk in enumerate(chunks):
            bmvector = await atokenize_document(chunk.content)
            embeddings_i = embeddings[i] if i < len(embeddings) else []

            async with self.__db.asession() as session:
                doc_table = DocumentTable(
                    source_id=source_id,
                    content=chunk.content,
                    vector=embeddings_i,
                    bmvector=dict(bmvector),
                    entities=chunk.entities,
                    document_index=chunk.document_index,
                    page_index=chunk.page_index,
                    image_url=chunk.image_url,
                    meta=chunk.metadata,
                )  # type: ignore
                session.add(doc_table)
                await session.commit()
                await session.refresh(doc_table)
                doc_ids.append(doc_table.id)

        return doc_ids

    async def aload_from_file(
        self,
        file_path: str | pathlib.Path,
        source_name: str | None = None,
        category: str | None = None,
        page_index: int | None = None,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
    ) -> list[UUID]:
        path = pathlib.Path(file_path)
        if source_name is None:
            source_name = path.stem

        document = await aconvert_file(path)
        document.name = source_name
        document.page_index = page_index

        source_id = await self.aget_or_create_source(name=source_name, category=category, link=f"file://{path}")

        return await self._ingest_document(
            document=document,
            source_id=source_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def aload_from_text(
        self,
        content: str,
        source_name: str,
        category: str | None = None,
        page_index: int | None = None,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
    ) -> list[UUID]:
        document = Document(content=content, name=source_name, page_index=page_index)
        source_id = await self.aget_or_create_source(name=source_name, category=category)

        return await self._ingest_document(
            document=document,
            source_id=source_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def aload_documents_from_dir(
        self,
        dir_path: str | pathlib.Path,
        category: str | None = None,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
    ) -> dict[str, list[UUID]]:
        dir_path = pathlib.Path(dir_path)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        results: dict[str, list[UUID]] = {}
        for file_path in sorted(dir_path.rglob("*")):
            if file_path.is_file() and file_path.suffix.lower() in (".md", ".txt", ".pdf", ".docx"):
                source_name = file_path.stem
                sub_category = str(file_path.parent.relative_to(dir_path)) if file_path.parent != dir_path else None
                try:
                    doc_ids = await self.aload_from_file(
                        file_path=file_path,
                        source_name=source_name,
                        category=category or sub_category,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                    )
                    results[source_name] = doc_ids
                    logging.info("Ingested %s: %d chunks", source_name, len(doc_ids))
                except Exception:
                    logging.exception("Failed to ingest %s", file_path)
        return results

    async def adelete_source(self, source_id: UUID) -> None:
        async with self.__db.asession() as session:
            from sqlalchemy import delete as sqla_delete

            await session.execute(sqla_delete(DocumentTable).where(col(DocumentTable.source_id) == source_id))
            await session.execute(sqla_delete(DocumentSource).where(col(DocumentSource.id) == source_id))
            await session.commit()
