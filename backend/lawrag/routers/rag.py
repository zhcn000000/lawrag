import logging

from anyio import Path as AsyncPath
from fastapi import APIRouter
from pydantic import TypeAdapter

from lawrag.database.pageindex import LawPageIndex
from lawrag.database.ragmode import RAGMode
from lawrag.routers.schema import LawInfoItem, PageIndexImportResultItem, SearchItem, TocEntryItem

from .schema import (
    LawArticleDetailResponse,
    LawArticleListResponse,
    LawArticleResponse,
    LawListResponse,
    LawTocResponse,
    PageIndexImportRequest,
    PageIndexImportResponse,
    SearchRequest,
    SearchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/search")
async def api_search(request: SearchRequest) -> SearchResponse:
    try:
        rag_mode = RAGMode()
        docs = await rag_mode.ahyprid_search(
            query=request.query,
            limit=request.k,
            regex=request.regex,
            vecweight=request.vecweight,
        )
        results = [
            SearchItem(
                content=d.content,
                source_name=d.name,
                page_index=d.page_index,
                score=d.query_score if d.query_score is not None else float("nan"),
            )
            for d in docs
        ]
        return SearchResponse(success=True, status="搜索成功", results=results)
    except Exception as e:
        logger.exception("Search failed")
        return SearchResponse(success=False, status=f"搜索失败: {e!s}", results=[])


@router.post("/pageindex/import")
async def api_pageindex_import(request: PageIndexImportRequest) -> PageIndexImportResponse:
    try:
        pageindex = LawPageIndex()
        path = request.path

        p = AsyncPath(path)
        if await p.is_dir():
            results = await pageindex.aimport_from_dir(dir_path=path)
        else:
            result = await pageindex.aimport_file(file_path=path)
            results = [result]
        results = TypeAdapter(list[PageIndexImportResultItem]).validate_python(results)
        total = sum(r.count for r in results)
        return PageIndexImportResponse(
            success=True,
            status=f"导入完成, 共 {total} 条法条",
            results=results,
        )
    except Exception as e:
        logger.exception("Page index import failed")
        return PageIndexImportResponse(success=False, status=f"导入失败: {e!s}", results=[])


@router.get("/pageindex/laws")
async def api_pageindex_list_laws() -> LawListResponse:
    try:
        pageindex = LawPageIndex()
        laws = await pageindex.alist_laws()
        laws_model = TypeAdapter(list[LawInfoItem]).validate_python(laws)
        return LawListResponse(success=True, status="获取法律列表成功", laws=laws_model)
    except Exception as e:
        logger.exception("List laws failed")
        return LawListResponse(success=False, status=f"获取失败: {e!s}", laws=[])


@router.get("/pageindex/laws/{law_name}/articles")
async def api_pageindex_get_articles(
    law_name: str,
    start: int | None = None,
    end: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> LawArticleListResponse:
    try:
        pageindex = LawPageIndex()
        articles = await pageindex.aget_law_articles(
            law_name=law_name,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )
        return LawArticleListResponse(
            success=True,
            status=f"获取 {law_name} 法条成功",
            articles=[LawArticleResponse(**a) for a in articles],
        )
    except Exception as e:
        logger.exception("Get law articles failed")
        return LawArticleListResponse(success=False, status=f"获取失败: {e!s}", articles=[])


@router.get("/pageindex/laws/{law_name}/toc")
async def api_pageindex_get_toc(law_name: str) -> LawTocResponse:
    try:
        pageindex = LawPageIndex()
        toc = await pageindex.aget_law_toc(law_name=law_name)
        toc_model = TypeAdapter(list[TocEntryItem]).validate_python(toc)
        return LawTocResponse(success=True, status=f"获取 {law_name} 目录成功", law_name=law_name, toc=toc_model)
    except Exception as e:
        logger.exception("Get law toc failed")
        return LawTocResponse(success=False, status=f"获取失败: {e!s}", law_name=law_name, toc=[])


@router.get("/pageindex/laws/{law_name}/articles/{article_number}")
async def api_pageindex_get_article(
    law_name: str,
    article_number: int,
) -> LawArticleDetailResponse:
    try:
        pageindex = LawPageIndex()
        article = await pageindex.aget_by_law_article(law_name=law_name, article_number=article_number)
        return LawArticleDetailResponse(
            success=True,
            status="查找成功" if article else "未找到",
            article=LawArticleResponse(**article) if article else None,
        )
    except Exception as e:
        logger.exception("Get law article failed")
        return LawArticleDetailResponse(success=False, status=f"查找失败: {e!s}", article=None)
