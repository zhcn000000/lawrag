from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from lawrag.environments import settings

from .database import DatabaseManager
from .tables import User

ALGORITHM = "HS256"
TOKEN_EXPIRES_IN = settings.TOKEN_EXPIRES_IN

oauth2_schema = OAuth2PasswordBearer(tokenUrl="/api/login", refreshUrl="/api/refresh")


class TokenDataDict(TypedDict):
    username: str
    user_id: UUID


class UserInfoDict(TypedDict):
    id: UUID
    username: str


class UserManager:
    def __init__(self, dbname: str = "data") -> None:
        self.__db = DatabaseManager(dbname)

    @staticmethod
    def _get_secret() -> str:
        return settings.JWT_SECRET.get_secret_value()

    async def acreate_access_token(self, username: str) -> str:
        user_id = (await self.aget_id_by_names([username]))[0]
        expire = datetime.now(UTC) + timedelta(seconds=TOKEN_EXPIRES_IN)
        payload = {"sub": username, "user_id": str(user_id), "exp": expire}
        return jwt.encode(payload, self._get_secret(), algorithm=ALGORITHM)

    @staticmethod
    def verify_access_token(token: str) -> TokenDataDict | None:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET.get_secret_value(), algorithms=[ALGORITHM])
            return TokenDataDict(
                username=str(payload["sub"]),
                user_id=UUID(payload["user_id"]),
            )
        except jwt.PyJWTError:
            return None

    async def aget(self, user_id: UUID) -> UserInfoDict | None:
        async with self.__db.asession() as session:
            stmt = select(User).where(col(User.id) == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                return UserInfoDict(id=user.id, username=user.username)
            return None

    async def ainsert(self, username: str, password: str) -> UUID:
        async with self.__db.asession() as session:
            stmt = insert(User).values(username=username, password=password).returning(col(User.id))
            result = await session.execute(stmt)
            return result.scalar_one()

    async def adelete(self, user_id: UUID) -> None:
        async with self.__db.asession() as session:
            stmt = delete(User).where(col(User.id) == user_id)
            await session.execute(stmt)

    async def aupdate(self, user_id: UUID, username: str | None = None, password: str | None = None) -> None:
        updated_data: dict[str, str] = {}
        if username is not None:
            updated_data["username"] = username
        if password is not None:
            updated_data["password"] = password
        if not updated_data:
            return
        async with self.__db.asession() as session:
            stmt = update(User).where(col(User.id) == user_id).values(**updated_data)
            await session.execute(stmt)

    async def alists(self) -> dict[str, UserInfoDict]:
        async with self.__db.asession() as session:
            stmt = select(User)
            result = await session.execute(stmt)
            users = result.scalars().all()
            return {user.username: UserInfoDict(id=user.id, username=user.username) for user in users}

    async def averify_credentials(self, username: str, password: str) -> str | None:
        async with self.__db.asession() as session:
            stmt = select(User).where(col(User.username) == username, col(User.password) == password)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                return await self.acreate_access_token(username)
        return None

    @classmethod
    def get_current_user(cls, token: str = Depends(oauth2_schema)) -> TokenDataDict:
        credentials_exception = HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        token_data = cls.verify_access_token(token)
        if token_data is None:
            raise credentials_exception
        return token_data

    async def aget_id_by_names(self, names: list[str]) -> list[UUID]:
        if not names:
            return []
        async with self.__db.asession() as session:
            stmt = select(col(User.username), col(User.id)).where(col(User.username).in_(names))
            result = await session.execute(stmt)
            name2id = {row[0]: row[1] for row in result.fetchall()}
            if len(name2id) != len(names):
                msg = "Some user names do not exist in the database."
                raise ValueError(msg)
            return [name2id[name] for name in names if name in name2id]

    async def aget_name_by_ids(self, ids: list[UUID]) -> list[str]:
        if not ids:
            return []
        async with self.__db.asession() as session:
            stmt = select(col(User.id), col(User.username)).where(col(User.id).in_(ids))
            result = await session.execute(stmt)
            id2name = {row[0]: row[1] for row in result.fetchall()}
            if len(id2name) != len(ids):
                msg = "Some user IDs do not exist in the database."
                raise ValueError(msg)
            return [id2name[id] for id in ids if id in id2name]
