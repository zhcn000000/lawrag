from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from warnings import warn

from psycopg import AsyncConnection, AsyncCursor, Connection, Cursor, IsolationLevel
from sqlalchemy import Engine, MetaData, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, CreateTable, DropSchema, DropTable
from sqlalchemy_utils.functions.database import create_database, database_exists, drop_database
from sqlmodel import SQLModel

from lawrag.utils.environments import settings

from .pool import pool_manager


class DatabaseManager:
    def __init__(self, dbname: str | None = None) -> None:
        if dbname is None:
            dbname = settings.POSTGRES_DB
        assert isinstance(dbname, str), "Database name must be a string."
        self.dbname = dbname
        self._engine: Engine | None = None
        self._async_engine: AsyncEngine | None = None

    @staticmethod
    def create_db(dbname: str | None = None) -> bool:
        if dbname is None:
            dbname = settings.POSTGRES_DB
        url = pool_manager.url
        url = url.set(database=dbname)
        if not database_exists(url):
            create_database(url)
            if not database_exists(url):
                raise RuntimeError(f"Failed to create database '{dbname}'.")
            return True
        return False

    @staticmethod
    def drop_db(dbname: str | None = None, force: bool = False) -> bool:
        if dbname is None:
            dbname = settings.POSTGRES_DB
        url = pool_manager.url
        url = url.set(database=dbname)
        if database_exists(url) and (
            force
            or input(
                f"Are you sure you want to drop the database '{dbname}'? This action cannot be undone. (y/n): ",
            ).lower()
            == "y"
        ):
            drop_database(url)
            if database_exists(url):
                raise RuntimeError(f"Failed to drop database '{dbname}'.")
            return True
        return False

    def engine(self) -> Engine:
        return pool_manager.engine(self.dbname)

    async def aengine(self) -> AsyncEngine:
        return await pool_manager.aengine(self.dbname)

    def pool(self):
        return pool_manager.pool(self.dbname)

    async def apool(self):
        return await pool_manager.apool(self.dbname)

    @contextmanager
    def session(self, schema: str = "public") -> Generator[Session]:
        engine = self.engine()
        with Session(engine) as session:
            try:
                if schema == "public":
                    session.execute(text("SET search_path TO public,bm25_catalog,tokenizer_catalog;"))
                else:
                    session.execute(
                        text("SET search_path TO :schema,public,bm25_catalog,tokenizer_catalog;"),
                        {"schema": schema},
                    )
                yield session
                if session.in_transaction():
                    session.commit()
            except Exception:
                if session.in_transaction():
                    session.rollback()
                raise

    @asynccontextmanager
    async def asession(self, schema: str = "public") -> AsyncGenerator[AsyncSession]:
        engine = await self.aengine()
        async with AsyncSession(engine) as session:
            try:
                if schema == "public":
                    await session.execute(text("SET search_path TO public,bm25_catalog,tokenizer_catalog;"))
                else:
                    await session.execute(
                        text("SET search_path TO :schema,public,bm25_catalog,tokenizer_catalog;"),
                        {"schema": schema},
                    )
                yield session
                if session.in_transaction():
                    await session.commit()
            except Exception:
                if session.in_transaction():
                    await session.rollback()
                raise

    @contextmanager
    def connection(
        self,
        schema: str = "public",
        read_only: bool = False,
        autocommit: bool = True,
        deferrable: bool = False,
        isolation: IsolationLevel = IsolationLevel.READ_COMMITTED,
    ) -> Generator[Connection]:
        pool = self.pool()
        with pool.connection() as conn:
            conn.set_read_only(read_only)
            conn.set_isolation_level(isolation)
            conn.set_autocommit(autocommit if not read_only else False)
            conn.set_deferrable(deferrable if read_only and isolation == IsolationLevel.SERIALIZABLE else False)
            try:
                with conn.cursor() as cursor:
                    if schema == "public":
                        cursor.execute(
                            "SET search_path TO public,bm25_catalog,tokenizer_catalog;",
                        )
                    else:
                        cursor.execute(
                            t"SET search_path TO '{schema:i}',public,bm25_catalog,tokenizer_catalog;",
                        )
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @asynccontextmanager
    async def aconnection(
        self,
        schema: str = "public",
        read_only: bool = False,
        autocommit: bool = True,
        deferrable: bool = False,
        isolation: IsolationLevel = IsolationLevel.READ_COMMITTED,
    ) -> AsyncGenerator[AsyncConnection]:
        pool = await self.apool()
        async with pool.connection() as conn:
            try:
                await conn.set_read_only(read_only)
                await conn.set_isolation_level(isolation)
                await conn.set_autocommit(autocommit if not read_only else False)
                await conn.set_deferrable(
                    deferrable if read_only and isolation == IsolationLevel.SERIALIZABLE else False,
                )
                async with conn.cursor() as cursor:
                    if schema == "public":
                        await cursor.execute(
                            "SET search_path TO public,bm25_catalog,tokenizer_catalog;",
                        )
                    else:
                        await cursor.execute(
                            t"SET search_path TO '{schema:i}',public,bm25_catalog,tokenizer_catalog;",
                        )
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    @contextmanager
    def cursor(
        self,
        schema: str = "public",
        read_only: bool = False,
        autocommit: bool = True,
        deferrable: bool = False,
        isolation: IsolationLevel = IsolationLevel.READ_COMMITTED,
    ) -> Generator[Cursor]:
        with self.connection(schema, read_only, autocommit, deferrable, isolation) as conn, conn.cursor() as cursor:
            yield cursor

    @asynccontextmanager
    async def acursor(
        self,
        schema: str = "public",
        read_only: bool = False,
        autocommit: bool = True,
        deferrable: bool = False,
        isolation: IsolationLevel = IsolationLevel.READ_COMMITTED,
    ) -> AsyncGenerator[AsyncCursor]:
        async with (
            self.aconnection(schema, read_only, autocommit, deferrable, isolation) as conn,
            conn.cursor() as cursor,
        ):
            yield cursor

    async def acreate_all(self, metadata: MetaData | None = None) -> None:
        if metadata is None:
            metadata = SQLModel.metadata
        async with (await self.aengine()).begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def adrop_all(self, metadata: MetaData | None = None) -> None:
        if metadata is None:
            metadata = SQLModel.metadata
        async with (await self.aengine()).begin() as conn:
            await conn.run_sync(metadata.drop_all)

    async def acreate_schema(self, schema: str) -> None:
        async with self.asession() as session:
            stmt = CreateSchema(schema, if_not_exists=True)
            await session.execute(stmt)
            await session.commit()

    async def adrop_schema(self, schema: str) -> None:
        async with self.asession() as session:
            stmt = DropSchema(schema, cascade=True, if_exists=True)
            await session.execute(stmt)
            await session.commit()

    async def acreate_table(self, table: type[SQLModel], schema: str = "public") -> None:
        table_name: str = table.__tablename__  # type: ignore
        old_table = table.metadata.tables[table_name]
        new_metadata = MetaData()

        new_table = old_table.to_metadata(new_metadata, schema=schema)
        async with self.asession() as session:
            stmt = CreateTable(new_table, if_not_exists=True)
            try:
                await session.execute(stmt)
                await session.commit()
                return
            except Exception as e:
                warn(
                    f"Failed to create table {new_table.name} in schema {schema}: {e} fallback to sync create_all.",
                    stacklevel=2,
                )
        async with (await self.aengine()).begin() as conn:
            await conn.run_sync(new_metadata.create_all, tables=[new_table])

    async def adrop_table(self, table: type[SQLModel], schema: str = "public") -> None:
        table_name: str = table.__tablename__  # type: ignore
        old_table = table.metadata.tables[table_name]
        new_metadata = MetaData()

        new_table = old_table.to_metadata(new_metadata, schema=schema)
        async with self.asession() as session:
            stmt = DropTable(new_table, if_exists=True)
            try:
                await session.execute(stmt)
                await session.commit()
                return
            except Exception as e:
                warn(
                    f"Failed to drop table {new_table.name} in schema {schema}: {e} fallback to sync drop_all.",
                    stacklevel=2,
                )

        async with (await self.aengine()).begin() as conn:
            await conn.run_sync(new_metadata.drop_all, tables=[new_table])
