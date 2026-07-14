import logging

import pytest
from anyio import Path as AsyncPath

from lawrag.database.document import DocumentStore
from lawrag.database.pageindex import LawPageIndex
from lawrag.database.ragsearch import RAGSearch
from lawrag.environments import settings

logger = logging.getLogger(__name__)

STRUCTURED_LAWS_DIR = settings.DATA_ROOT / "structured_laws"


@pytest.fixture(scope="session")
async def setup_real_db():
    """Session 级: 从 data/structured_laws/ 导入测试用法律, 结束后清理。

    使用真实数据库 settings.POSTGRES_DB (默认 "data")。若法律已存在则跳过导入,
    测试结束后删除本次会话新导入的法律 (通过 ON DELETE CASCADE 自动清理关联文档)。
    """
    pageindex = LawPageIndex()
    docstore = DocumentStore()
    existing = {e["law_name"] for e in await pageindex.afind_laws()}

    test_laws = ["反分裂国家法"]
    for law_name in test_laws:
        if law_name not in existing:
            fpath = STRUCTURED_LAWS_DIR / f"{law_name}.json"
            if await AsyncPath(fpath).exists():
                result = await docstore.aimport_file(str(fpath))
                if result["status"] == "ok":
                    logger.info("Imported %s: %d articles", law_name, result["count"])

    yield

    for law_name in test_laws:
        if law_name not in existing:
            try:
                await docstore.adelete_law(law_name)
                logger.info("Cleaned up %s", law_name)
            except Exception as e:
                logger.warning("Cleanup failed for %s: %s", law_name, e)


@pytest.fixture
async def pageindex() -> LawPageIndex:
    return LawPageIndex()


@pytest.fixture
async def ragsearch() -> RAGSearch:
    return RAGSearch()


@pytest.fixture
async def docstore() -> DocumentStore:
    return DocumentStore()
