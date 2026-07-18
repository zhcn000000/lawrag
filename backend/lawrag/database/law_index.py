import logging
from collections.abc import Sequence
from datetime import date
from typing import TypedDict
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.functions import count
from sqlmodel import col

from .database import DatabaseManager
from .tables import DocumentTable, LawIndex, LawNode

logger = logging.getLogger(__name__)


def _parse_date(value: object) -> date | None:
    if value is None or not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    return None


class LawInfoDict(TypedDict):
    law_types: list[str]
    statuses: list[str]


class LawIndexDict(TypedDict):
    id: UUID
    law_id: str
    law_name: str
    office: str
    publish_date: date | None
    expiry_date: date | None
    law_type: str
    status: str
    detail_url: str
    index_number: str
    raw: str | None
    structured: dict | None


class KbOverviewItem(TypedDict):
    id: UUID
    law_name: str
    law_type: str
    status: str
    publish_date: date | None
    has_raw: bool
    has_structured: bool
    in_nodes: bool
    article_count: int
    chunk_count: int


class KbOverviewResult(TypedDict):
    items: list[KbOverviewItem]
    total: int


class LawIndexManager:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    async def aupsert(
        self,
        *,
        law_id: str,
        law_name: str = "",
        office: str = "",
        publish_date: date | str | None = None,
        expiry_date: date | str | None = None,
        law_type: str = "",
        status: str = "",
        detail_url: str = "",
        index_number: str = "",
    ) -> None:
        """Upsert a law index entry by law_id."""
        values = {
            "law_id": law_id,
            "law_name": law_name,
            "office": office,
            "publish_date": _parse_date(publish_date),
            "expiry_date": _parse_date(expiry_date),
            "law_type": law_type,
            "status": status,
            "detail_url": detail_url,
            "index_number": index_number,
        }
        async with self.__db.asession() as session:
            stmt = (
                insert(LawIndex)
                .values(values)
                .on_conflict_do_update(
                    index_elements=[col(LawIndex.law_id)],
                    set_={k: values[k] for k in values if k != "law_id"},
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def abulk_upsert(
        self,
        entries: Sequence[dict],
    ) -> None:
        for e in entries:
            await self.aupsert(
                law_id=e.get("law_id", ""),
                law_name=e.get("law_name", ""),
                office=e.get("office", ""),
                publish_date=e.get("publish_date"),
                expiry_date=e.get("expiry_date"),
                law_type=e.get("law_type", ""),
                status=e.get("status", ""),
                detail_url=e.get("detail_url", ""),
                index_number=e.get("index_number", ""),
            )

    async def aset_raw(self, law_id: str, text: str) -> None:
        async with self.__db.asession() as session:
            stmt = update(LawIndex).where(col(LawIndex.law_id) == law_id).values(raw=text)
            await session.execute(stmt)
            await session.commit()

    async def aset_structured(self, law_id: str, structured: dict) -> None:
        async with self.__db.asession() as session:
            stmt = update(LawIndex).where(col(LawIndex.law_id) == law_id).values(structured=structured)
            await session.execute(stmt)
            await session.commit()

    async def ahas_raw(self, law_id: str) -> bool:
        async with self.__db.asession() as session:
            stmt = select(col(LawIndex.raw)).where(col(LawIndex.law_id) == law_id)
            result = await session.execute(stmt)
            row = result.first()
            return row is not None and row[0] is not None

    async def aget(self, law_id: str) -> LawIndexDict | None:
        async with self.__db.asession() as session:
            stmt = select(LawIndex).where(col(LawIndex.law_id) == law_id)
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return None
            return LawIndexDict(
                id=row.id,
                law_id=row.law_id,
                law_name=row.law_name,
                office=row.office,
                publish_date=row.publish_date,
                expiry_date=row.expiry_date,
                law_type=row.law_type,
                status=row.status,
                detail_url=row.detail_url,
                index_number=row.index_number,
                raw=row.raw,
                structured=row.structured,
            )

    async def aget_info(self) -> LawInfoDict:
        async with self.__db.asession() as session:
            types_result = await session.execute(
                select(col(LawIndex.law_type)).distinct().order_by(col(LawIndex.law_type)),
            )
            status_result = await session.execute(
                select(col(LawIndex.status)).distinct().order_by(col(LawIndex.status)),
            )
            return LawInfoDict(
                law_types=[r[0] for r in types_result.fetchall() if r[0]],
                statuses=[r[0] for r in status_result.fetchall() if r[0]],
            )

    async def afind_all(
        self,
        *,
        law_type: str | None = None,
        status: str | None = None,
        has_raw: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[LawIndexDict]:
        async with self.__db.asession() as session:
            stmt = select(LawIndex).order_by(col(LawIndex.law_name))
            if law_type is not None:
                stmt = stmt.where(col(LawIndex.law_type) == law_type)
            if status is not None:
                stmt = stmt.where(col(LawIndex.status) == status)
            if has_raw is True:
                stmt = stmt.where(col(LawIndex.raw).isnot(None))
            elif has_raw is False:
                stmt = stmt.where(col(LawIndex.raw).is_(None))
            if limit is not None:
                stmt = stmt.limit(limit)
            if offset is not None:
                stmt = stmt.offset(offset)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                LawIndexDict(
                    id=r.id,
                    law_id=r.law_id,
                    law_name=r.law_name,
                    office=r.office,
                    publish_date=r.publish_date,
                    expiry_date=r.expiry_date,
                    law_type=r.law_type,
                    status=r.status,
                    detail_url=r.detail_url,
                    index_number=r.index_number,
                    raw=r.raw,
                    structured=r.structured,
                )
                for r in rows
            ]

    async def acount(self, **filters: str | None) -> int:
        async with self.__db.asession() as session:
            stmt = select(count(col(LawIndex.law_id)))
            if "law_type" in filters and filters["law_type"] is not None:
                stmt = stmt.where(col(LawIndex.law_type) == filters["law_type"])
            if "status" in filters and filters["status"] is not None:
                stmt = stmt.where(col(LawIndex.status) == filters["status"])
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def adelete(self, law_id: str) -> None:
        async with self.__db.asession() as session:
            await session.execute(delete(LawIndex).where(col(LawIndex.law_id) == law_id))
            await session.commit()

    async def aclear_content(self, id: UUID) -> str:
        """Clear downloaded raw/structured columns; the law must not be imported into law_nodes."""
        async with self.__db.asession() as session:
            result = await session.execute(select(LawIndex).where(col(LawIndex.id) == id))
            row = result.scalars().first()
            if row is None:
                raise ValueError("法律索引不存在")
            node_result = await session.execute(select(count(col(LawNode.id))).where(col(LawNode.law_index_id) == id))
            if (node_result.scalar() or 0) > 0:
                raise ValueError(f"法律 {row.law_name} 已导入节点, 请先删除节点后再清除下载文档")
            law_name = row.law_name
            await session.execute(update(LawIndex).where(col(LawIndex.id) == id).values(raw=None, structured=None))
            await session.commit()
            return law_name

    async def afind_download_candidates(
        self,
        law_types: frozenset[str] | None = frozenset({"宪法", "法律"}),
        status: str | None = "有效",
        regex: str | None = "(?<!办)法$",
        skip_downloaded: bool = True,
        ids: list[UUID] | None = None,
    ) -> list[LawIndexDict]:
        async with self.__db.asession() as session:
            stmt = select(LawIndex)
            if law_types is not None:
                stmt = stmt.where(col(LawIndex.law_type).in_(law_types))
            if status is not None:
                stmt = stmt.where(col(LawIndex.status) == status)
            if ids is not None:
                stmt = stmt.where(col(LawIndex.id).in_(ids))
            if skip_downloaded:
                stmt = stmt.where(col(LawIndex.raw).is_(None))
            if regex is not None:
                stmt = stmt.where(col(LawIndex.law_name).regexp_match(regex))
            stmt = stmt.order_by(col(LawIndex.law_name))

            result = await session.execute(stmt)
            rows = result.scalars().all()
            logger.info("Find download candidates %s", str([r.law_name for r in rows]))
            return [
                LawIndexDict(
                    id=r.id,
                    law_id=r.law_id,
                    law_name=r.law_name,
                    office=r.office,
                    publish_date=r.publish_date,
                    expiry_date=r.expiry_date,
                    law_type=r.law_type,
                    status=r.status,
                    detail_url=r.detail_url,
                    index_number=r.index_number,
                    raw=r.raw,
                    structured=r.structured,
                )
                for r in rows
            ]

    async def _build_index_items(
        self,
        index_rows: Sequence,
    ) -> list[KbOverviewItem]:
        """Enrich LawIndex rows with LawNode + DocumentTable stats."""
        if not index_rows:
            return []

        law_index_ids = [r.id for r in index_rows]

        async with self.__db.asession() as session:
            node_stats_stmt = (
                select(
                    col(LawNode.law_index_id),
                    count(col(LawNode.id)),
                    count(col(LawNode.id)).filter(col(LawNode.node_type) == "article"),
                )
                .where(col(LawNode.law_index_id).in_(law_index_ids))
                .group_by(col(LawNode.law_index_id))
            )
            node_result = await session.execute(node_stats_stmt)
            node_stats: dict[UUID, tuple[int, int]] = {r[0]: (r[1] or 0, r[2] or 0) for r in node_result.fetchall()}

            chunk_stats_stmt = (
                select(
                    col(LawNode.law_index_id),
                    count(col(DocumentTable.id)),
                )
                .join(DocumentTable, col(DocumentTable.node_id) == col(LawNode.id))
                .where(col(LawNode.law_index_id).in_(law_index_ids))
                .group_by(col(LawNode.law_index_id))
            )
            chunk_result = await session.execute(chunk_stats_stmt)
            chunk_stats: dict[UUID, int] = {r[0]: r[1] or 0 for r in chunk_result.fetchall()}

        return [
            KbOverviewItem(
                id=r.id,
                law_name=r.law_name,
                law_type=r.law_type,
                status=r.status,
                publish_date=r.publish_date,
                has_raw=r.has_raw,
                has_structured=r.has_structured,
                in_nodes=node_stats.get(r.id, (0, 0))[0] > 0,
                article_count=node_stats.get(r.id, (0, 0))[1],
                chunk_count=chunk_stats.get(r.id, 0),
            )
            for r in index_rows
        ]

    async def afind_all_with_status(
        self,
        *,
        law_type: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> KbOverviewResult:
        """Combined overview: law_index entries with law_nodes + documents status."""
        async with self.__db.asession() as session:
            base_stmt = select(
                col(LawIndex.id),
                col(LawIndex.law_name),
                col(LawIndex.law_type),
                col(LawIndex.status),
                col(LawIndex.publish_date),
                col(LawIndex.raw).isnot(None).label("has_raw"),
                col(LawIndex.structured).isnot(None).label("has_structured"),
            ).order_by(col(LawIndex.law_type), col(LawIndex.law_name))
            if law_type is not None:
                base_stmt = base_stmt.where(col(LawIndex.law_type) == law_type)
            if status is not None:
                base_stmt = base_stmt.where(col(LawIndex.status) == status)
            if query is not None:
                base_stmt = base_stmt.where(col(LawIndex.law_name).ilike(f"%{query}%"))

            count_stmt = select(count()).select_from(base_stmt.subquery())
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0
            if total == 0:
                return KbOverviewResult(items=[], total=0)

            paged_stmt = base_stmt.limit(limit).offset(offset)
            result = await session.execute(paged_stmt)
            index_rows = result.all()

            if not index_rows:
                return KbOverviewResult(items=[], total=total)

            items = await self._build_index_items(index_rows)
            return KbOverviewResult(items=items, total=total)
