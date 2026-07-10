import json
import logging
from collections.abc import AsyncIterator, Generator
from typing import Any

from scrapy import Request, Spider
from scrapy.http.response import Response

from lawrag.spider.items import LawIndexItem

logger = logging.getLogger(__name__)

"""Law spider - crawl national laws from 国家法律法规数据库 (flk.npc.gov.cn).

Categories (available individually or via -a category=all):
  - xf:    宪法 (constitution)
  - flfg:  法律 (laws by NPC and its Standing Committee)
  - xzfg:  行政法规 (administrative regulations by State Council)
  - jcfg:  监察法规 (supervision regulations)
  - sfjs:  司法解释 (judicial interpretations by Supreme Court)

Available individually only (excluded from "all"):
  - dfxfg: 地方性法规 (local regulations)
"""
SEARCH_API_URL = "https://flk.npc.gov.cn/law-search/search/list"
DETAIL_BASE_URL = "https://flk.npc.gov.cn"

CATEGORY_CODE_MAP: dict[str, list[int]] = {
    "xf": [100],
    "flfg": [101, 102, 110, 120, 130, 140, 150, 155, 160, 170, 180, 190, 195, 200],
    "xzfg": [201, 210, 215],
    "jcfg": [220],
    "sfjs": [311],
    "dfxfg": [221, 222, 230, 260, 270, 290, 295, 300, 305, 310],
}
CATEGORY_CODE_MAP["all"] = (
    CATEGORY_CODE_MAP["xf"]
    + CATEGORY_CODE_MAP["flfg"]
    + CATEGORY_CODE_MAP["xzfg"]
    + CATEGORY_CODE_MAP["jcfg"]
    + CATEGORY_CODE_MAP["sfjs"]
)

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

PAGE_SIZE = 100
MAX_STALE_PAGES = 3


def _build_search_body(page: int, flfg_code_ids: list[int]) -> dict[str, Any]:
    return {
        "searchRange": 1,
        "sxrq": [],
        "gbrq": [],
        "searchType": 2,
        "sxx": [],
        "gbrqYear": [],
        "flfgCodeId": flfg_code_ids,
        "zdjgCodeId": [],
        "searchContent": "",
        "orderByParam": {"order": "-1", "sort": ""},
        "pageNum": page,
        "pageSize": PAGE_SIZE,
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
        if category in CATEGORY_CODE_MAP:
            self._category = category
        else:
            known = ", ".join(CATEGORY_CODE_MAP)
            logger.warning("Unknown category '%s', known: %s. Defaulting to all.", category, known)
            self._category = "all"

        self._code_ids = CATEGORY_CODE_MAP[self._category]
        self._total_items = 0
        self._total_pages = 0
        self._seen_bbbs: set[str] = set()
        self._stale_pages = 0

    async def start(self) -> AsyncIterator[Request]:
        logger.info("Starting law index crawl for category: %s", self._category)
        body = _build_search_body(page=1, flfg_code_ids=self._code_ids)
        yield Request(
            url=SEARCH_API_URL,
            method="POST",
            body=json.dumps(body),
            headers=JSON_HEADERS,
            callback=self.parse_page,
            dont_filter=True,
            meta={"page": 1},
        )

    def parse_page(self, response: Response) -> Generator[Request | LawIndexItem]:
        page: int = response.meta["page"]
        is_first = page == 1
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.exception("JSON decode error for page %d", page)
            return

        if is_first:
            total_count = int(data.get("total", 0))
            self._total_items = total_count
            self._total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
            self._seen_bbbs = set()
            self._stale_pages = 0
            logger.info("Category '%s': %d total items, %d pages", self._category, total_count, self._total_pages)
        logger.info("Parsing page %d/%d: %d items", page, self._total_pages, len(data.get("rows", [])))

        law_list = data.get("rows", [])
        item_count = 0
        for idx, entry in enumerate(law_list):
            sxx = entry.get("sxx")
            status = STATUS_MAP.get(sxx, str(sxx) if sxx is not None else "")
            bbbs = entry.get("bbbs", "")

            if bbbs:
                if bbbs in self._seen_bbbs:
                    continue
                self._seen_bbbs.add(bbbs)
            item_count += 1
            yield LawIndexItem(
                law_id=bbbs,
                law_name=entry.get("title", ""),
                office=entry.get("zdjgName", ""),
                publish_date=entry.get("gbrq", ""),
                expiry_date=entry.get("sxrq", ""),
                law_type=entry.get("flxz", ""),
                status=status,
                detail_url=f"{DETAIL_BASE_URL}/detail2.html?{bbbs}" if bbbs else "",
                category=self._category,
                index_number=str((page - 1) * PAGE_SIZE + idx + 1),
            )

        if item_count > 0:
            self._stale_pages = 0
        else:
            self._stale_pages += 1
            logger.warning(
                "Page %d returned no new items (%d/%d consecutive stale pages)",
                page,
                self._stale_pages,
                MAX_STALE_PAGES,
            )

        logger.debug("Parsed page %d: %d items (%d new)", page, len(data.get("rows", [])), item_count)

        if self._stale_pages >= MAX_STALE_PAGES:
            logger.info("Stopping pagination after %d stale pages", self._stale_pages)
            return

        next_page = page + 1
        if self._total_pages and next_page > self._total_pages:
            return

        body = _build_search_body(page=next_page, flfg_code_ids=self._code_ids)
        yield Request(
            url=SEARCH_API_URL,
            method="POST",
            body=json.dumps(body),
            headers=JSON_HEADERS,
            callback=self.parse_page,
            meta={"page": next_page},
            dont_filter=True,
        )
