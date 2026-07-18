import logging
from itertools import starmap
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import count
from sqlmodel import col

from .database import DatabaseManager
from .tables import LawNode

logger = logging.getLogger(__name__)


class ArticleDict(TypedDict):
    """aget_by_law_article / aget_law_articles 返回的单条法条结构。"""

    id: str
    law_name: str
    article_number: int
    content: str
    chapter_title: str | None
    chapter_number: int | None
    section_number: int | None
    section_title: str | None


class NodeByPathDict(TypedDict):
    """aget_node_by_path 返回的节点信息。"""

    law_name: str
    path: str
    node_type: str
    number: int | None
    full_path: str
    content: str


class BrowseChildDict(TypedDict):
    """abrowse_law 返回的 children 列表中的子节点。"""

    path: str
    node_type: str
    number: int | None
    title: str | None
    content: str | None
    is_leaf: bool


class BrowseResultDict(TypedDict):
    """abrowse_law 返回值。error 仅在查找失败时存在。"""

    law_name: str
    path: str
    node_type: str
    title: str | None
    children: list[BrowseChildDict]


class TocEntryDict(TypedDict):
    """aget_law_toc 返回的目录节点，children 为嵌套子节点。"""

    node_type: str
    number: int | None
    title: str | None
    path: str
    children: list[TocEntryDict]


class LawInfoDict(TypedDict):
    """afind_laws 返回的法律概要条目。"""

    law_name: str
    article_count: int


def _ancestor_titles(p1: LawNode | None, p2: LawNode | None) -> tuple[LawNode | None, LawNode | None]:
    """由一级/二级父节点还原最近的 (章, 节)。用于 article 的章/节定位。"""
    chapter: LawNode | None = None
    section: LawNode | None = None
    for anc in (p1, p2):
        if anc is None:
            continue
        if anc.node_type == "section" and section is None:
            section = anc
        elif anc.node_type == "chapter" and chapter is None:
            chapter = anc
    return chapter, section


def _article_dict(article: LawNode, p1: LawNode | None, p2: LawNode | None) -> ArticleDict:
    chapter, section = _ancestor_titles(p1, p2)
    assert article.number is not None, f"Article {article.id} has null number"
    return ArticleDict(
        id=str(article.id),
        law_name=article.law_name,
        article_number=article.number,
        content=article.content or "",
        chapter_title=chapter.content if chapter else None,
        chapter_number=chapter.number if chapter else None,
        section_number=section.number if section else None,
        section_title=section.content if section else None,
    )


class LawPageIndex:
    def __init__(self, dbname: str | None = None) -> None:
        self.__db = DatabaseManager(dbname)

    def _article_query(self, law_name: str | None = None):  # type: ignore[reportUnknownParameterType]
        """构造 article 节点及其一级/二级父节点的联表查询。返回 (stmt, p1, p2) 供调用方追加条件。"""
        p1 = aliased(LawNode)
        p2 = aliased(LawNode)
        stmt = (
            select(LawNode, p1, p2)
            .join(p1, col(LawNode.parent_id) == col(p1.id), isouter=True)
            .join(p2, col(p1.parent_id) == col(p2.id), isouter=True)
            .where(col(LawNode.node_type) == "article")
        )
        if law_name is not None:
            stmt = stmt.where(col(LawNode.law_name) == law_name)
        return stmt, p1, p2

    async def aget_by_law_article(
        self,
        law_name: str,
        article_number: int,
    ) -> ArticleDict | None:
        async with self.__db.asession() as session:
            stmt, _, _ = self._article_query(law_name)
            stmt = stmt.where(col(LawNode.number) == article_number)
            result = await session.execute(stmt)
            row = result.first()
            if row is None:
                return None
            return _article_dict(*row)

    async def aget_law_articles(
        self,
        law_name: str,
        start: int | None = None,
        end: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ArticleDict]:
        async with self.__db.asession() as session:
            stmt, _, _ = self._article_query(law_name)
            if start is not None:
                stmt = stmt.where(col(LawNode.number) >= start)
            if end is not None:
                stmt = stmt.where(col(LawNode.number) <= end)
            stmt = stmt.order_by(col(LawNode.id)).offset(offset).limit(limit)
            result = await session.execute(stmt)
            return list(starmap(_article_dict, result.all()))

    async def aget_node_by_path(self, law_name: str, path: str) -> NodeByPathDict:
        """按层级路径 path 精确获取单个节点信息 (法条或章节标题)。"""
        async with self.__db.asession() as session:
            node = (
                (
                    await session.execute(
                        select(LawNode).where(
                            col(LawNode.law_name) == law_name,
                            col(LawNode.path) == path,
                        ),
                    )
                )
                .scalars()
                .first()
            )
            if node is None:
                raise ValueError(f"Node not found for law {law_name} and path {path}")

            return NodeByPathDict(
                law_name=node.law_name,
                path=node.path,
                node_type=node.node_type,
                number=node.number,
                full_path=node.full_path or node.law_name,
                content=node.content or "",
            )

    async def abrowse_law(
        self,
        law_name: str,
        path: str,
        limit: int = 200,
    ) -> BrowseResultDict:
        async with self.__db.asession() as session:
            current = (
                (
                    await session.execute(
                        select(LawNode).where(
                            col(LawNode.law_name) == law_name,
                            col(LawNode.path) == path,
                        ),
                    )
                )
                .scalars()
                .first()
            )
            if current is None:
                raise ValueError(f"Node not found for law {law_name} and path {path}")
            parent_id = current.id
            cur_type = current.node_type
            cur_title = current.content
            cur_path = current.path

            rows = (
                (
                    await session.execute(
                        select(LawNode)
                        .where(col(LawNode.parent_id) == parent_id)
                        .order_by(col(LawNode.id))
                        .limit(limit),
                    )
                )
                .scalars()
                .all()
            )

            children: list[BrowseChildDict] = [
                BrowseChildDict(
                    path=r.path,
                    node_type=r.node_type,
                    number=r.number,
                    title=r.content if r.node_type != "article" else None,
                    content=r.content if r.node_type == "article" else None,
                    is_leaf=r.node_type == "article",
                )
                for r in rows
            ]
            return BrowseResultDict(
                law_name=law_name,
                path=cur_path,
                node_type=cur_type,
                title=cur_title,
                children=children,
            )

    async def aget_law_toc(self, law_name: str) -> list[TocEntryDict]:
        """返回一部法律的多级目录 (编/分编/章/节 标题), 供 LLM 索引上层结构。

        以 parent_id 还原树状层级, 每个节点含 ``node_type``/``number``/``title``/``children``。
        """
        async with self.__db.asession() as session:
            stmt = (
                select(LawNode)
                .where(
                    col(LawNode.law_name) == law_name,
                    col(LawNode.node_type).in_(("part", "subpart", "chapter", "section")),
                )
                .order_by(col(LawNode.id))
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            entries: dict[UUID, dict] = {
                row.id: {
                    "node_type": row.node_type,
                    "number": row.number,
                    "title": row.content,
                    "path": row.path,
                    "children": [],
                    "_parent": row.parent_id,
                }
                for row in rows
            }
            toc: list[dict] = []
            for row in rows:
                entry = entries[row.id]
                parent = entries.get(row.parent_id) if row.parent_id is not None else None
                (parent["children"] if parent is not None else toc).append(entry)

            def _to_toc_entry(e: dict) -> TocEntryDict:
                return TocEntryDict(
                    node_type=e["node_type"],
                    number=e["number"],
                    title=e["title"],
                    path=e["path"],
                    children=[_to_toc_entry(c) for c in e["children"]],
                )

            return [_to_toc_entry(e) for e in toc]

    async def afind_laws(
        self,
        regex: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[LawInfoDict]:
        async with self.__db.asession() as session:
            stmt = (
                select(
                    col(LawNode.law_name),
                    count(col(LawNode.id)).label("count"),
                )
                .where(col(LawNode.node_type) == "article")
                .group_by(col(LawNode.law_name))
                .order_by(col(LawNode.law_name))
            )
            if regex is not None:
                stmt = stmt.having(col(LawNode.law_name).regexp_match(regex))
            if limit is not None:
                stmt = stmt.limit(limit)
            if offset is not None:
                stmt = stmt.offset(offset)
            result = await session.execute(stmt)
            return [LawInfoDict(law_name=row[0], article_count=row[1]) for row in result.fetchall()]
