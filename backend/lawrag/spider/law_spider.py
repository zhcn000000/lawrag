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
    from collections.abc import AsyncIterator, Generator

    from scrapy.http.response import Response

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://flk.npc.gov.cn/law-search/search/list"
DETAIL_BASE_URL = "https://flk.npc.gov.cn"

CATEGORY_CODE_MAP = {
    "flfg": [101],  # 法律
    "xzfg": [201],  # 行政法规
    "sfjs": [311],  # 司法解释
}

NATIONAL_CATEGORIES = ("flfg", "xzfg", "sfjs")

STATUS_MAP = {
    1: "已废止",
    2: "已修改",
    3: "有效",
    4: "尚未生效",
}

JSON_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


def _build_search_body(page_no: int, page_size: int, flfg_code_ids: list[int]) -> dict[str, Any]:
    return {
        "pageNo": page_no,
        "pageSize": page_size,
        "searchRange": 1,
        "searchType": 2,
        "searchContent": "",
        "sxrq": [],
        "gbrq": [],
        "sxx": [],
        "flfgCodeId": flfg_code_ids,
        "zdjgCodeId": [],
        "xgzlSearch": False,
    }


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

    async def start(self) -> "AsyncIterator[Request]":
        logger.info("Starting law index crawl for categories: %s", self._categories)
        for cat in self._categories:
            code_ids = CATEGORY_CODE_MAP[cat]
            body = _build_search_body(page_no=1, page_size=10, flfg_code_ids=code_ids)
            yield Request(
                url=SEARCH_API_URL,
                method="POST",
                body=json.dumps(body),
                headers=JSON_HEADERS,
                callback=self.parse_api_first_page,
                meta={"category": cat, "code_ids": code_ids},
                dont_filter=True,
            )

    def parse_api_first_page(self, response: Response) -> Generator[Request | LawIndexItem | None]:
        cat = response.meta["category"]
        code_ids = response.meta["code_ids"]
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.exception("Failed to parse JSON for %s page 1", cat)
            return

        total_count = int(data.get("total", 0))
        total_pages = total_count // 10 + (1 if total_count % 10 else 0)

        self._total_items[cat] = total_count
        logger.info("Category '%s': %d total items, %d pages", cat, total_count, total_pages)

        yield from self._parse_page_items(response, cat, 1)

        for page in range(2, min(total_pages + 1, 101)):  # max 100 pages = 1000 items
            body = _build_search_body(page_no=page, page_size=10, flfg_code_ids=code_ids)
            yield Request(
                url=SEARCH_API_URL,
                method="POST",
                body=json.dumps(body),
                headers=JSON_HEADERS,
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

        law_list = data.get("rows", [])
        if not law_list:
            logger.warning("Empty data for %s page %d", cat, page)
            return

        for idx, entry in enumerate(law_list):
            index_num = (page - 1) * 10 + idx + 1
            sxx = entry.get("sxx")
            status = STATUS_MAP.get(sxx, str(sxx) if sxx is not None else "")
            bbbs = entry.get("bbbs", "")

            yield LawIndexItem(
                law_name=entry.get("title", ""),
                office=entry.get("zdjgName", ""),
                publish_date=entry.get("gbrq", ""),
                expiry_date=entry.get("sxrq", ""),
                law_type=entry.get("flxz", ""),
                status=status,
                detail_url=f"{DETAIL_BASE_URL}/detail2.html?{bbbs}" if bbbs else "",
                category=cat,
                index_number=str(index_num),
            )

        logger.debug("Parsed page %d of %s: %d items", page, cat, len(law_list))
