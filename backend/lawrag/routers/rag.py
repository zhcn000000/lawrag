import logging
from uuid import UUID

from fastapi import APIRouter, UploadFile

from lawrag.database.document import DocumentStore
from lawrag.database.ragmode import RAGMode

from .schema import (
    DocumentUploadResponse,
    SearchRequest,
    SearchResponse,
    SourceInfo,
    SourceListResponse,
)

router = APIRouter()


@router.post("/search")
async def api_search(request: SearchRequest) -> SearchResponse:
    try:
        source_id = UUID(request.source_id) if request.source_id else None
        rag_mode = RAGMode()
        docs = await rag_mode.ahyprid_search(
            query=request.query,
            k=request.k,
            regex=request.regex,
            source_id=source_id,
            page_index=request.page_index,
            offset=request.offset,
        )
        results = [
            {
                "content": d.content,
                "source_name": d.name,
                "score": d.query_score if d.query_score is not None else float("nan"),
                "document_index": d.document_index,
                "page_index": d.page_index,
            }
            for d in docs
        ]
        return SearchResponse(success=True, status="搜索成功", results=results)
    except Exception as e:
        logging.exception(e)
        return SearchResponse(success=False, status=f"搜索失败: {e!s}", results=[])


@router.post("/documents/upload")
async def api_upload_document(
    file: UploadFile,
    category: str | None = None,
) -> DocumentUploadResponse:
    try:
        from pathlib import Path
        from tempfile import NamedTemporaryFile

        suffix = Path(file.filename or "").suffix
        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
            doc_store = DocumentStore()
            doc_ids = await doc_store.aload_from_file(
                file_path=tmp_path,
                source_name=file.filename,
                category=category,
            )
        Path(tmp_path).unlink()  # noqa: ASYNC240
        return DocumentUploadResponse(
            success=True,
            status="文档上传成功",
            doc_ids=[str(d) for d in doc_ids],
        )
    except Exception as e:
        logging.exception(e)
        return DocumentUploadResponse(success=False, status=f"文档上传失败: {e!s}", doc_ids=[])


@router.post("/documents/ingest-dir")
async def api_ingest_directory(
    dir_path: str,
    category: str | None = None,
) -> DocumentUploadResponse:
    try:
        doc_store = DocumentStore()
        results = await doc_store.aload_documents_from_dir(dir_path=dir_path, category=category)
        all_ids: list[UUID] = []
        for doc_ids in results.values():
            all_ids.extend(doc_ids)
        return DocumentUploadResponse(
            success=True,
            status=f"批量导入成功，共 {len(all_ids)} 个文档分块",
            doc_ids=[str(d) for d in all_ids],
        )
    except Exception as e:
        logging.exception(e)
        return DocumentUploadResponse(success=False, status=f"批量导入失败: {e!s}", doc_ids=[])


@router.get("/sources")
async def api_list_sources() -> SourceListResponse:
    try:
        rag_mode = RAGMode()
        sources = await rag_mode.alist_sources()
        return SourceListResponse(
            success=True,
            status="获取来源列表成功",
            sources=[SourceInfo(**s) for s in sources],
        )
    except Exception as e:
        logging.exception(e)
        return SourceListResponse(success=False, status=f"获取来源列表失败: {e!s}", sources=[])


@router.delete("/sources/{source_id}")
async def api_delete_source(source_id: UUID) -> DocumentUploadResponse:
    try:
        doc_store = DocumentStore()
        await doc_store.adelete_source(source_id)
        return DocumentUploadResponse(success=True, status="删除成功", doc_ids=[])
    except Exception as e:
        logging.exception(e)
        return DocumentUploadResponse(success=False, status=f"删除失败: {e!s}", doc_ids=[])
