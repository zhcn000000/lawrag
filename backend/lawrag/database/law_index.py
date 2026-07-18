import logging
import operator
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
    law_id: str
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
            from sqlalchemy.sql.functions import count

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

    async def afind_download_candidates(
        self,
        law_types: frozenset[str] | None = frozenset({"宪法", "法律"}),
        status: str | None = "有效",
        regex: str | None = "(?<!办)法$",
        skip_downloaded: bool = True,
        law_ids: list[str] | None = None,
    ) -> list[LawIndexDict]:
        async with self.__db.asession() as session:
            stmt = select(LawIndex)
            if law_types is not None:
                stmt = stmt.where(col(LawIndex.law_type).in_(law_types))
            if status is not None:
                stmt = stmt.where(col(LawIndex.status) == status)
            if law_ids is not None:
                stmt = stmt.where(col(LawIndex.law_id).in_(law_ids))
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

    async def _afind_orphan_nodes(
        self,
        *,
        query: str | None = None,
    ) -> list[KbOverviewItem]:
        """Find law_names that exist in law_nodes but not in law_index."""
        async with self.__db.asession() as session:
            orphan_stmt = (
                select(
                    col(LawNode.law_name),
                    count(col(LawNode.id)),
                    count(col(LawNode.id)).filter(col(LawNode.node_type) == "article"),
                )
                .where(~col(LawNode.law_name).in_(select(col(LawIndex.law_name))))
                .group_by(col(LawNode.law_name))
                .order_by(col(LawNode.law_name))
            )
            if query is not None:
                orphan_stmt = orphan_stmt.where(col(LawNode.law_name).ilike(f"%{query}%"))

            result = await session.execute(orphan_stmt)
            orphan_rows = result.fetchall()
            if not orphan_rows:
                return []

            orphan_names = [r[0] for r in orphan_rows]

            chunk_stmt = (
                select(
                    col(LawNode.law_name),
                    count(col(DocumentTable.id)),
                )
                .join(DocumentTable, col(DocumentTable.node_id) == col(LawNode.id))
                .where(col(LawNode.law_name).in_(orphan_names))
                .group_by(col(LawNode.law_name))
            )
            chunk_result = await session.execute(chunk_stmt)
            chunk_rows = chunk_result.fetchall()

            def _chunk_count(name: str) -> int:
                for r in chunk_rows:
                    if r[0] == name:
                        return r[1] or 0
                return 0

            return [
                KbOverviewItem(
                    law_id="",
                    law_name=row[0],
                    law_type="未知",
                    status="未知",
                    publish_date=None,
                    has_raw=False,
                    has_structured=False,
                    in_nodes=True,
                    article_count=row[2] or 0,
                    chunk_count=_chunk_count(row[0]),
                )
                for row in orphan_rows
            ]

    async def _build_index_items(
        self,
        index_rows: Sequence,
    ) -> list[KbOverviewItem]:
        """Enrich LawIndex rows with LawNode + DocumentTable stats."""
        if not index_rows:
            return []

        async with self.__db.asession() as session:
            law_names = [r.law_name for r in index_rows]

            node_stats_stmt = (
                select(
                    col(LawNode.law_index_id),
                    col(LawNode.law_name),
                    count(col(LawNode.id)),
                    count(col(LawNode.id)).filter(col(LawNode.node_type) == "article"),
                )
                .where(col(LawNode.law_name).in_(law_names))
                .group_by(col(LawNode.law_index_id), col(LawNode.law_name))
            )
            node_result = await session.execute(node_stats_stmt)
            node_rows: Sequence = node_result.fetchall()

            chunk_stats_stmt = (
                select(
                    col(LawNode.law_index_id),
                    col(LawNode.law_name),
                    count(col(DocumentTable.id)),
                )
                .join(DocumentTable, col(DocumentTable.node_id) == col(LawNode.id))
                .where(col(LawNode.law_name).in_(law_names))
                .group_by(col(LawNode.law_index_id), col(LawNode.law_name))
            )
            chunk_result = await session.execute(chunk_stats_stmt)
            chunk_rows: Sequence = chunk_result.fetchall()

        def _match(row_id: UUID, row_name: str, stats: Sequence, key_idx: int) -> int:
            for s in stats:
                sid = s[0]
                if sid is not None and sid == row_id:
                    return s[key_idx] or 0
            for s in stats:
                sname = s[1]
                if sname is not None and sname == row_name:
                    return s[key_idx] or 0
            return 0

        return [
            KbOverviewItem(
                law_id=r.law_id,
                law_name=r.law_name,
                law_type=r.law_type,
                status=r.status,
                publish_date=r.publish_date,
                has_raw=r.raw is not None,
                has_structured=r.structured is not None,
                in_nodes=_match(r.id, r.law_name, node_rows, 2) > 0,
                article_count=_match(r.id, r.law_name, node_rows, 3),
                chunk_count=_match(r.id, r.law_name, chunk_rows, 2),
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
        only_unknown = (status == "未知") or (law_type == "未知")
        show_both = status is None and law_type is None

        if only_unknown:
            orphans = await self._afind_orphan_nodes(query=query)
            total = len(orphans)
            items = orphans[offset : offset + limit]
            return KbOverviewResult(items=items, total=total)

        async with self.__db.asession() as session:
            base_stmt = select(LawIndex).order_by(col(LawIndex.law_type), col(LawIndex.law_name))
            if law_type is not None:
                base_stmt = base_stmt.where(col(LawIndex.law_type) == law_type)
            if status is not None:
                base_stmt = base_stmt.where(col(LawIndex.status) == status)
            if query is not None:
                base_stmt = base_stmt.where(col(LawIndex.law_name).ilike(f"%{query}%"))

            count_stmt = select(count(col(LawIndex.id))).select_from(base_stmt.subquery())
            count_result = await session.execute(count_stmt)
            index_total = count_result.scalar() or 0

            if show_both:
                orphans = await self._afind_orphan_nodes() if query is None else []
                total = index_total + len(orphans)
                if total == 0:
                    return KbOverviewResult(items=[], total=0)

                result = await session.execute(base_stmt)
                index_rows = result.scalars().all()
                index_items = await self._build_index_items(index_rows)

                all_items = index_items + orphans
                all_items.sort(key=operator.itemgetter("law_type", "law_name"))
                items = all_items[offset : offset + limit]
                return KbOverviewResult(items=items, total=total)

            # Regular path: only law_index entries
            if index_total == 0:
                return KbOverviewResult(items=[], total=0)

            paged_stmt = base_stmt.limit(limit).offset(offset)
            result = await session.execute(paged_stmt)
            index_rows = result.scalars().all()

            if not index_rows:
                return KbOverviewResult(items=[], total=index_total)

            items = await self._build_index_items(index_rows)
            return KbOverviewResult(items=items, total=index_total)
