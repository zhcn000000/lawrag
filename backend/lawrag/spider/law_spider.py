"""Law spider - crawl national laws from 国家法律法规数据库 (flk.npc.gov.cn).

Target categories:
  - flfg: 法律 (laws by NPC and its Standing Committee)
  - xzfg: 行政法规 (administrative regulations by State Council)
  - sfjs: 司法解释 (judicial interpretations by Supreme Court)
Excluded: dfxfg (地方性法规 - local regulations)
"""

import json
import logging
from typing import TYPE_CHECKING, Any

from scrapy import Request, Spider

from lawrag.spider.items import LawIndexItem

if TYPE_CHECKING:
    from collections.abc import Generator

    from scrapy.http.response import Response

logger = logging.getLogger(__name__)

NPC_API_URL = "https://flk.npc.gov.cn/api/"
DETAIL_BASE_URL = "https://flk.npc.gov.cn"

NATIONAL_CATEGORIES = ("flfg", "xzfg", "sfjs")

STATUS_MAP = {
    "1": "有效",
    "3": "尚未生效",
    "5": "已修改",
    "7": "有效",
    "9": "已废止",
}


def _build_api_url(page: int, category: str) -> str:
    return (
        f"{NPC_API_URL}?page={page}"
        f"&type={category}"
        f"&searchType=title%3Bvague"
        f"&sortTr=f_bbrq_s%3Bdesc"
        f"&gbrqStart=&gbrqEnd=&sxrqStart=&sxrqEnd="
        f"&sort=true&size=10"
    )


class LawIndexSpider(Spider):
    """Spider that crawls the NPC law database API to build a law index.

    Usage:
        scrapy crawl law_index -a category=flfg -o laws.json
        scrapy crawl law_index -a category=all  # all national categories
    """

    name = "law_index"

    def __init__(self, category: str = "all", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if category == "all":
            self._categories: list[str] = list(NATIONAL_CATEGORIES)
        elif category in NATIONAL_CATEGORIES:
            self._categories = [category]
        else:
            logger.warning("Unknown category '%s', defaulting to all national categories.", category)
            self._categories = list(NATIONAL_CATEGORIES)

        self._index_counter: dict[str, int] = {}
        self._total_items: dict[str, int] = {}

    def start_requests(self) -> Generator[Request]:
        logger.info("Starting law index crawl for categories: %s", self._categories)
        for cat in self._categories:
            yield Request(
                url=_build_api_url(page=1, category=cat),
                callback=self.parse_api_first_page,
                meta={"category": cat},
                dont_filter=True,
            )

    def parse_api_first_page(self, response: Response) -> Generator[Request | LawIndexItem | None]:
        cat = response.meta["category"]
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.exception("Failed to parse JSON for %s page 1", cat)
            return

        result = data.get("result", {})
        total_count = int(result.get("totalSizes", 0))
        total_pages = int(result.get("totalPage", 0))
        total_pages = total_pages if total_pages > 0 else (total_count // 10 + (1 if total_count % 10 else 0))

        self._total_items[cat] = total_count
        logger.info("Category '%s': %d total items, %d pages", cat, total_count, total_pages)

        yield from self._parse_page_items(response, cat, 1)

        for page in range(2, total_pages + 1):
            yield Request(
                url=_build_api_url(page=page, category=cat),
                callback=self._parse_page_items,
                meta={"category": cat, "page": page},
                dont_filter=True,
            )

    def _parse_page_items(
        self,
        response: Response,
        cat: str | None = None,
        page: int = 0,
    ) -> Generator[LawIndexItem]:
        cat = cat or response.meta["category"]
        page = page or response.meta.get("page", 0)

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.exception("JSON decode error for %s page %d", cat, page)
            return

        law_list = data.get("result", {}).get("data", [])
        if not law_list:
            logger.warning("Empty data for %s page %d", cat, page)
            return

        for idx, entry in enumerate(law_list):
            index_num = (page - 1) * 10 + idx + 1
            status_raw = str(entry.get("status", ""))

            raw_url = entry.get("url", "")
            detail_url = raw_url
            if raw_url and not raw_url.startswith("http"):
                detail_url = DETAIL_BASE_URL + raw_url if raw_url.startswith("/") else f"{DETAIL_BASE_URL}/{raw_url}"

            yield LawIndexItem(
                law_name=entry.get("title", ""),
                office=entry.get("office", ""),
                publish_date=entry.get("publish", ""),
                expiry_date=entry.get("expiry", ""),
                law_type=entry.get("type", ""),
                status=STATUS_MAP.get(status_raw, status_raw),
                detail_url=detail_url,
                category=cat,
                index_number=str(index_num),
            )

        logger.debug("Parsed page %d of %s: %d items", page, cat, len(law_list))
