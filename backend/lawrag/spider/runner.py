"""Async law spider runner using Scrapy's native asyncio support (AsyncCrawlerRunner).

Uses TWISTED_REACTOR_ENABLED=False for pure asyncio mode without a Twisted reactor.
"""

import logging
from pathlib import Path
from typing import Any

from scrapy.crawler import AsyncCrawlerRunner

from lawrag.spider.law_spider import LawIndexSpider

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "BOT_NAME": "lawrag_spider",
    "ROBOTSTXT_OBEY": False,
    "DOWNLOAD_DELAY": 1.0,
    "RANDOMIZE_DOWNLOAD_DELAY": True,
    "CONCURRENT_REQUESTS": 8,
    "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    "LOG_LEVEL": "INFO",
    "COOKIES_ENABLED": False,
    "TELNETCONSOLE_ENABLED": False,
    "RETRY_ENABLED": True,
    "RETRY_TIMES": 3,
    "DOWNLOAD_TIMEOUT": 30,
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
}

DEFAULT_OUTPUT = Path("data/law_index/law_index.json")


async def run_law_index_spider(
    *,
    category: str = "all",
    output: Path | None = None,
    extra_settings: dict[str, Any] | None = None,
) -> None:
    settings = DEFAULT_SETTINGS.copy()
    if extra_settings:
        settings.update(extra_settings)

    output_path = output or DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)
    settings["LAW_INDEX_PATH"] = str(output_path)

    runner = AsyncCrawlerRunner(settings)
    await runner.crawl(LawIndexSpider, category=category)
