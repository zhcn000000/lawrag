from psycopg.sql import SQL

from .database import DatabaseManager
from .user import UserManager


async def init_db(alter_system: bool = False, dbname: str | None = None) -> bool:
    status = DatabaseManager.create_db(dbname)
    db = DatabaseManager(dbname=dbname)
    async with db.acursor(autocommit=True) as cur:
        await cur.execute(
            SQL("""
            CREATE EXTENSION IF NOT EXISTS pgcrypto CASCADE;
            CREATE EXTENSION IF NOT EXISTS vchord CASCADE;
            CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE;
            """),
        )
    await db.acreate_all()
    await UserManager().ainsert("admin", "admin", is_admin=True)
    if alter_system:
        async with db.aconnection(autocommit=True) as conn:
            await conn.execute(
                SQL("""
                ALTER SYSTEM SET shared_preload_libraries = vchord,vchord_bm25;
                ALTER SYSTEM SET search_path = "$user",public,bm25_catalog;
                ALTER SYSTEM SET io_method = io_uring;
                """),
            )

    return status


async def clean_db(dbname: str | None = None, force: bool = False) -> bool:
    return DatabaseManager.drop_db(dbname, force)


async def reset_db(dbname: str | None = None, force: bool = False) -> bool:
    status = await clean_db(dbname=dbname, force=force)
    if status:
        return await init_db(dbname=dbname, alter_system=False)
    return False
