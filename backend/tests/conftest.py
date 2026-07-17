import logging

import pytest

from lawrag.database.document import DocumentStore
from lawrag.database.initdb import init_db
from lawrag.database.pageindex import LawPageIndex
from lawrag.database.ragsearch import RAGSearch
from lawrag.environments import settings


@pytest.fixture(scope="session", autouse=True)
async def configure_test_database():
    settings.POSTGRES_DB = "lawrag_test"  # 测试数据库名, 避免污染生产数据库
    await init_db()  # 初始化测试数据库


logger = logging.getLogger(__name__)


@pytest.fixture
async def setup_real_db():
    docstore = DocumentStore()
    test_laws = ["反分裂国家法"]
    for law in test_laws:
        await docstore.aimport_laws(law)

    yield
    for law in test_laws:
        await docstore.adelete_law(law)


@pytest.fixture
async def pageindex() -> LawPageIndex:
    return LawPageIndex()


@pytest.fixture
async def ragsearch() -> RAGSearch:
    return RAGSearch()


@pytest.fixture
async def docstore() -> DocumentStore:
    return DocumentStore()
