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

        self._total_items = 0
        self._seen_bbbs: set[str] = set()
        self._stale_pages = 0

    async def start(self) -> AsyncIterator[Request]:
        logger.info("Starting law index crawl for category: %s", self._category)
        code_ids = CATEGORY_CODE_MAP[self._category]
        body = _build_search_body(page=1, flfg_code_ids=code_ids)
        yield Request(
            url=SEARCH_API_URL,
            method="POST",
            body=json.dumps(body),
            headers=JSON_HEADERS,
            callback=self.parse_first_page,
            meta={"category": self._category, "code_ids": code_ids},
            dont_filter=True,
        )

    def parse_first_page(self, response: Response) -> Generator[Request | LawIndexItem | None]:
        cat = response.meta["category"]
        code_ids: list[int] = response.meta["code_ids"]
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.exception("Failed to parse JSON for %s page 1", cat)
            return

        total_count = int(data.get("total", 0))
        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE

        self._total_items = total_count
        logger.info("Category '%s': %d total items, %d pages", cat, total_count, total_pages)

        self._seen_bbbs = set()
        self._stale_pages = 0

        yield from self._parse_page_items(response, cat, 1)

        if total_pages > 1:
            yield self._build_page_request(cat, page=2, code_ids=code_ids, total_pages=total_pages)

    def _build_page_request(
        self,
        cat: str,
        *,
        page: int,
        code_ids: list[int],
        total_pages: int = 0,
    ) -> Request:
        body = _build_search_body(page=page, flfg_code_ids=code_ids)
        return Request(
            url=SEARCH_API_URL,
            method="POST",
            body=json.dumps(body),
            headers=JSON_HEADERS,
            callback=self._parse_page_items,
            meta={"category": cat, "code_ids": code_ids, "page": page, "total_pages": total_pages},
            dont_filter=True,
        )

    def _parse_page_items(
        self,
        response: Response,
        cat: str | None = None,
        page: int = 0,
    ) -> Generator[Request | LawIndexItem]:
        cat = cat or response.meta["category"]
        page = page or response.meta.get("page", 0)
        code_ids: list[int] = response.meta.get("code_ids") or []
        total_pages: int = response.meta.get("total_pages", 0)

        assert isinstance(cat, str), "Category must be a string"

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.exception("JSON decode error for %s page %d", cat, page)
            return

        law_list = data.get("rows", [])
        if not law_list:
            logger.warning("Empty data for %s page %d", cat, page)
            return

        new_items = 0
        for idx, entry in enumerate(law_list):
            index_num = (page - 1) * PAGE_SIZE + idx + 1
            sxx = entry.get("sxx")
            status = STATUS_MAP.get(sxx, str(sxx) if sxx is not None else "")
            bbbs = entry.get("bbbs", "")

            if bbbs and bbbs in self._seen_bbbs:
                continue

            if bbbs:
                self._seen_bbbs.add(bbbs)
            new_items += 1

            yield LawIndexItem(
                law_id=bbbs,
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

        if new_items == 0:
            self._stale_pages += 1
            logger.warning(
                "Page %d of '%s' returned no new items (%d/%d consecutive stale pages)",
                page,
                cat,
                self._stale_pages,
                MAX_STALE_PAGES,
            )
        else:
            self._stale_pages = 0

        logger.debug("Parsed page %d of %s: %d items (%d new)", page, cat, len(law_list), new_items)

        if self._stale_pages >= MAX_STALE_PAGES:
            logger.info("Stopping pagination for '%s' after %d stale pages", cat, self._stale_pages)
            return

        next_page = page + 1
        if total_pages and next_page > total_pages:
            return

        if not code_ids:
            logger.warning("Missing code_ids in meta for '%s' page %d, cannot continue pagination", cat, page)
            return

        yield self._build_page_request(cat, page=next_page, code_ids=code_ids, total_pages=total_pages)
