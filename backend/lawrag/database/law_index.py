import logging
from collections.abc import Sequence
from datetime import date
from typing import TypedDict

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from .database import DatabaseManager
from .tables import LawIndex

logger = logging.getLogger(__name__)


def _parse_date(value: object) -> date | None:
    if value is None or not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    return None


class LawIndexDict(TypedDict, total=False):
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
        law_types: frozenset[str] = frozenset({"宪法", "法律"}),
        status: str = "有效",
        regex: str = "法$",
        skip_downloaded: bool = True,
    ) -> list[LawIndexDict]:

        async with self.__db.asession() as session:
            stmt = select(LawIndex).where(
                col(LawIndex.status) == status,
                col(LawIndex.law_type).in_(law_types),
            )
            if skip_downloaded:
                stmt = stmt.where(col(LawIndex.raw).is_(None))
            if regex is not None:
                stmt = stmt.where(col(LawIndex.law_name).regexp_match(regex))
            stmt = stmt.order_by(col(LawIndex.law_name))

            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                LawIndexDict(
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
