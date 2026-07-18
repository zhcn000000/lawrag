import logging

from fastapi import APIRouter, BackgroundTasks

from lawrag.database.document import DocumentStore
from lawrag.database.law_index import LawIndexManager
from lawrag.spider.runner import run_content_download, run_law_index_spider

from .schema import (
    KbCrawlRequest,
    KbDownloadRequest,
    KbEmbedRequest,
    KbImportRequest,
    KbLawOverviewItem,
    KbOverviewResponse,
    StatusResponse,
)
from .user import AdminUserDep

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[AdminUserDep])


@router.get("/overview")
async def api_kb_overview(
    law_type: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> KbOverviewResponse:
    try:
        lm = LawIndexManager()
        result = await lm.afind_all_with_status(
            law_type=law_type,
            status=status,
            query=query,
            limit=limit,
            offset=offset,
        )
        laws = [
            KbLawOverviewItem(
                id=i["id"] or None,
                law_name=i["law_name"],
                law_type=i["law_type"],
                status=i["status"],
                publish_date=i["publish_date"].isoformat() if i["publish_date"] else None,
                has_raw=i["has_raw"],
                has_structured=i["has_structured"],
                in_nodes=i["in_nodes"],
                article_count=i["article_count"],
                chunk_count=i["chunk_count"],
            )
            for i in result["items"]
        ]
        return KbOverviewResponse(success=True, status="获取知识库概览成功", laws=laws, total=result["total"])
    except Exception as e:
        logger.exception("KB overview failed")
        return KbOverviewResponse(success=False, status=f"获取失败: {e!s}", laws=[])


@router.post("/crawl")
async def api_kb_crawl(
    background_tasks: BackgroundTasks,
    request: KbCrawlRequest,
) -> StatusResponse:
    background_tasks.add_task(run_law_index_spider, category=request.category)
    logger.info("Crawl task started: category=%s", request.category)
    return StatusResponse(success=True, status=f"爬取任务已启动 (category={request.category})")


@router.post("/download")
async def api_kb_download(
    background_tasks: BackgroundTasks,
    request: KbDownloadRequest,
) -> StatusResponse:
    background_tasks.add_task(run_content_download, request.ids)
    logger.info("Download task started: ids=%s", request.ids)
    return StatusResponse(success=True, status="下载任务已启动")


@router.post("/import")
async def api_kb_import(request: KbImportRequest) -> StatusResponse:
    try:
        docstore = DocumentStore()
        for uid in request.ids:
            await docstore.aimport_laws(id=uid)
        return StatusResponse(success=True, status=f"已开始导入 {len(request.ids)} 部法律")
    except Exception as e:
        logger.exception("KB import failed")
        return StatusResponse(success=False, status=f"导入失败: {e!s}")


@router.post("/embed")
async def api_kb_embed(
    background_tasks: BackgroundTasks,
    request: KbEmbedRequest,
) -> StatusResponse:
    async def _embed() -> None:
        docstore = DocumentStore()
        for uid in request.ids:
            await docstore.aembed_laws(
                id=uid,
                chunk_size=request.chunk_size,
                chunk_overlap=request.chunk_overlap,
                batch_size=request.batch_size,
            )

    background_tasks.add_task(_embed)
    logger.info("Embed task started: laws=%s", request.ids)
    return StatusResponse(success=True, status=f"嵌入任务已启动 ({len(request.ids)} 部法律)")


@router.delete("/laws/{law_name}")
async def api_kb_delete_law(law_name: str) -> StatusResponse:
    try:
        docstore = DocumentStore()
        count = await docstore.adelete_law(law_name)
        return StatusResponse(success=True, status=f"已删除法律 {law_name} (含 {count} 条法条及关联文档块)")
    except Exception as e:
        logger.exception("KB delete failed")
        return StatusResponse(success=False, status=f"删除失败: {e!s}")
