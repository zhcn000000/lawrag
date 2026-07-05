from collections.abc import Sequence
from typing import TypedDict
from uuid import UUID

import orjson
from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy import delete, func, insert, select, update
from sqlmodel import col

from .database import DatabaseManager
from .tables import HistoryTable, SessionTable


class SessionDict(TypedDict):
    session_id: UUID
    name: str


class HistoryStore:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    async def aadd_messages(self, messages: Sequence[ModelMessage], session_id: UUID) -> None:
        messages_data = ModelMessagesTypeAdapter.dump_json(list(messages))
        messages_data = orjson.loads(messages_data)
        async with self.__db.asession() as session:
            stmt = insert(HistoryTable).values(
                session_id=session_id,
                messages=messages_data,
            )
            await session.execute(stmt)
            await session.commit()

    async def aget_messages(self, session_id: UUID) -> Sequence[ModelMessage]:
        async with self.__db.asession() as session:
            result = await session.execute(
                select(HistoryTable)
                .where(col(HistoryTable.session_id) == session_id)
                .order_by(func.uuid_extract_timestamp(col(HistoryTable.id))),
            )
            rows = result.scalars().all()
            if not rows:
                return []
            all_messages = []
            for row in rows:
                all_messages.extend(row.messages)
            all_messages = orjson.dumps(all_messages)
            return ModelMessagesTypeAdapter.validate_json(all_messages)

    async def aclear_messages(self, session_id: UUID) -> None:
        async with self.__db.asession() as session:
            stmt = delete(HistoryTable).where(col(HistoryTable.session_id) == session_id)
            await session.execute(stmt)
            await session.commit()

    async def acreate_session(self, session: str) -> UUID:
        async with self.__db.asession() as sql_session:
            stmt = insert(SessionTable).values(name=session).returning(col(SessionTable.id))
            result = await sql_session.execute(stmt)
            await sql_session.commit()
            return result.scalar_one()

    async def adelete_session(self, session_id: UUID) -> None:
        async with self.__db.asession() as sql_session:
            await sql_session.execute(delete(SessionTable).where(col(SessionTable.id) == session_id))
            await sql_session.commit()

    async def arename_session(self, session_id: UUID, name: str) -> None:
        async with self.__db.asession() as sql_session:
            stmt = update(SessionTable).where(col(SessionTable.id) == session_id).values(name=name)
            await sql_session.execute(stmt)
            await sql_session.commit()

    async def alist_sessions(self) -> list[SessionDict]:
        async with self.__db.asession() as sql_session:
            stmt = select(col(SessionTable.id), col(SessionTable.name)).order_by(col(SessionTable.id).desc())
            result = await sql_session.execute(stmt)
            rows = result.all()
            return [SessionDict(session_id=row[0], name=row[1]) for row in rows]

    async def aget_session(self, session_id: UUID) -> SessionDict | None:
        async with self.__db.asession() as sql_session:
            stmt = select(SessionTable).where(col(SessionTable.id) == session_id)
            result = await sql_session.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                return SessionDict(
                    session_id=row.id,
                    name=row.name,
                )
            return None

    async def aget_session_by_name(self, name: str) -> UUID | None:
        async with self.__db.asession() as sql_session:
            stmt = select(SessionTable).where(col(SessionTable.name) == name)
            result = await sql_session.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                return row.id

    async def acheck_session_exists(self, session_id: UUID) -> bool:
        async with self.__db.asession() as sql_session:
            stmt = select(func.count()).select_from(SessionTable).where(col(SessionTable.id) == session_id)
            result = await sql_session.execute(stmt)
            count = result.scalar_one()
            return count > 0
