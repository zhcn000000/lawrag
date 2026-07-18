import logging
from typing import Any
from uuid import UUID

from scrapy.crawler import AsyncCrawlerRunner

from lawrag.spider.content_spider import ContentDownloadSpider
from lawrag.spider.law_spider import LawIndexSpider

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "BOT_NAME": "lawrag_spider",
    "ROBOTSTXT_OBEY": False,
    "RANDOMIZE_DOWNLOAD_DELAY": True,
    "LOG_LEVEL": "INFO",
    "COOKIES_ENABLED": True,
    "REDIRECT_ENABLED": True,
    "RETRY_ENABLED": True,
    "RETRY_TIMES": 3,
    "DOWNLOAD_TIMEOUT": 30,
    "USER_AGENT": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0",
    "DEFAULT_REQUEST_HEADERS": {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    },
    "ITEM_PIPELINES": {
        "lawrag.spider.pipelines.LawIndexPipeline": 300,
    },
    "TWISTED_REACTOR_ENABLED": False,
    "TELNETCONSOLE_ENABLED": False,
}

LAW_INDEX_SETTINGS: dict[str, Any] = DEFAULT_SETTINGS.copy()
LAW_INDEX_SETTINGS.update({
    "DOWNLOAD_DELAY": 1.0,
    "CONCURRENT_REQUESTS": 8,
    "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    "ITEM_PIPELINES": {
        "lawrag.spider.pipelines.LawIndexPipeline": 300,
    },
})

LAW_INDEX_SETTINGS["DEFAULT_REQUEST_HEADERS"].update({
    "Content-Type": "application/json;charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
})

CONTENT_DOWNLOAD_SETTINGS: dict[str, Any] = DEFAULT_SETTINGS.copy()
CONTENT_DOWNLOAD_SETTINGS.update({
    "DOWNLOAD_DELAY": 0.5,
    "CONCURRENT_REQUESTS": 4,
    "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    "ITEM_PIPELINES": {
        "lawrag.spider.pipelines.ContentDownloadPipeline": 300,
    },
})


async def run_law_index_spider(
    *,
    category: str = "all",
    extra_settings: dict[str, Any] | None = None,
) -> None:
    settings = LAW_INDEX_SETTINGS.copy()
    if extra_settings:
        settings.update(extra_settings)

    runner = AsyncCrawlerRunner(settings)
    await runner.crawl(LawIndexSpider, category=category)


async def run_content_download(
    law_ids: list[UUID] | None = None,
    extra_settings: dict[str, Any] | None = None,
) -> None:
    """Run the Scrapy content download spider that downloads, converts, and stores laws in the database.

    If law_ids is provided, only download those specific law IDs (NPC API bbbs values).
    """
    settings = CONTENT_DOWNLOAD_SETTINGS.copy()
    if extra_settings:
        settings.update(extra_settings)

    runner = AsyncCrawlerRunner(settings)
    await runner.crawl(ContentDownloadSpider, law_ids=law_ids)
