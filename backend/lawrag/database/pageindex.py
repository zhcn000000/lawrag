import json
import logging
from itertools import starmap
from os import PathLike
from typing import TypedDict
from uuid import UUID, uuid7

from anyio import Path as AsyncPath
from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased
from sqlalchemy.sql.functions import count
from sqlmodel import col

from lawrag.database.document import DocumentStore
from lawrag.documents.lawparser import flatten_hierarchy

from .database import DatabaseManager
from .tables import DocumentTable, LawNode

logger = logging.getLogger(__name__)

# 参与向量/BM25 召回的节点类型: 条为初筛主体, 编/分编/章/节标题用于索引到上层, 序言作为整体
EMBEDDABLE_NODE_TYPES = ("article", "part", "subpart", "chapter", "section", "preamble")


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
    """alist_laws 返回的法律概要条目。"""

    law_name: str
    article_count: int


class ImportResultDict(TypedDict):
    """aimport_file / aimport_from_dir 返回的导入结果。"""

    file: str
    status: str
    count: int


class EmbedResultDict(TypedDict):
    """aembed_law_articles 返回的嵌入统计。"""

    law_name: str | None
    articles_embedded: int
    chunks_created: int


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


def _build_embed_text(node: LawNode) -> str:
    """利用导入时预计算的完整层级路径构造嵌入/检索上下文文本。"""
    fp = node.full_path or ""
    if node.node_type == "article":
        return f"{fp}规定，{node.content or ''}。"
    if node.node_type == "preamble":
        return f"{fp} {node.content or ''}"
    return fp


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

    async def aimport_file(
        self,
        file_path: str | PathLike,
    ) -> ImportResultDict:
        path = AsyncPath(file_path)
        law_name = path.stem
        parsed: dict = json.loads(await path.read_text(encoding="utf-8"))

        nodes = flatten_hierarchy(parsed, law_name)
        articles = sum(1 for n in nodes if n["node_type"] == "article")
        if articles == 0:
            return ImportResultDict(file=law_name, status="empty", count=0)

        ids = [uuid7() for _ in nodes]

        _type_unit = {"part": "编", "subpart": "分编", "chapter": "章", "section": "节", "article": "条"}

        def _node_seg(node_type: str, number: int | None, title: str | None) -> str:
            if node_type == "law":
                return f"《{law_name}》"
            if node_type == "preamble":
                return "序言"
            unit = _type_unit.get(node_type, "")
            if number is not None and unit:
                return f"第{number}{unit} {title or ''}".strip()
            return title or ""

        full_paths: list[str] = [""] * len(nodes)
        for i, n in enumerate(nodes):
            seg = _node_seg(n["node_type"], n["number"], n["title"])
            parent_idx = n["parent"]
            if parent_idx is not None and parent_idx < i:
                full_paths[i] = f"{full_paths[parent_idx]} {seg}".strip()
            else:
                full_paths[i] = seg

        values = [
            {
                "id": ids[i],
                "law_name": law_name,
                "parent_id": ids[n["parent"]] if n["parent"] is not None else None,
                "node_type": n["node_type"],
                "number": n["number"],
                "content": n["title"] or n["content"],
                "path": n["path"],
                "full_path": full_paths[i],
            }
            for i, n in enumerate(nodes)
        ]

        async with self.__db.asession() as session:
            # 重新导入前先清空该法律的所有节点, 保证幂等
            await session.execute(delete(LawNode).where(col(LawNode.law_name) == law_name))
            stmt = (
                insert(LawNode)
                .values(values)
                .on_conflict_do_nothing(index_elements=[col(LawNode.law_name), col(LawNode.path)])
            )
            await session.execute(stmt)
            await session.commit()

        logger.info("Imported %s: %d nodes (%d articles)", law_name, len(nodes), articles)
        return ImportResultDict(file=law_name, status="ok", count=articles)

    async def aimport_from_dir(
        self,
        dir_path: str | PathLike,
    ) -> list[ImportResultDict]:
        path = AsyncPath(dir_path)
        if not await path.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        results: list[ImportResultDict] = []
        paths = sorted([file_path async for file_path in path.rglob("*.json")])

        for file_path in paths:
            if await file_path.is_file() and not file_path.name.startswith("."):
                try:
                    logger.info("Importing %s...", file_path)
                    result = await self.aimport_file(file_path=file_path)
                    results.append(result)
                except Exception:
                    logger.exception("Failed to import %s", file_path)
                    results.append(ImportResultDict(file=file_path.stem, status="error", count=0))
        return results

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
        """按层级路径 path 精确获取单个节点信息 (法条或章节标题)。

        path 与 abrowse_law 相同, 会自动补全 ``law0/`` 前缀。返回值字段对齐检索结果单条: 面包屑/路径/内容。
        """
        if not path.startswith("law0/"):
            path = f"law0/{path.removeprefix('/')}"
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
        path: str | None = None,
        limit: int = 200,
    ) -> BrowseResultDict:
        if path is not None and not path.startswith("law0/"):
            path = path.removeprefix("/")
            path = f"law0/{path}"
        async with self.__db.asession() as session:
            if path:
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
            else:
                root = (
                    (
                        await session.execute(
                            select(LawNode).where(
                                col(LawNode.law_name) == law_name,
                                col(LawNode.node_type) == "law",
                            ),
                        )
                    )
                    .scalars()
                    .first()
                )
                if root is None:
                    raise ValueError(f"Law {law_name} not found")
                parent_id = root.id
                cur_type = "law"
                cur_title = law_name
                cur_path = ""

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

    async def alist_laws(
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

    async def adelete_law(self, law_name: str) -> int:
        async with self.__db.asession() as session:
            count_stmt = select(count(col(LawNode.id))).where(
                col(LawNode.law_name) == law_name,
                col(LawNode.node_type) == "article",
            )
            result = await session.execute(count_stmt)
            article_count = result.scalar() or 0
            await session.execute(delete(LawNode).where(col(LawNode.law_name) == law_name))
            await session.commit()

            logger.info("Deleted law %s (%d articles)", law_name, article_count)
            return article_count

    async def aembed_law_articles(
        self,
        law_name: str | None = None,
        chunk_size: int = 4096,
        chunk_overlap: int = 128,
        batch_size: int = 64,
    ) -> EmbedResultDict:
        doc_store = DocumentStore()

        offset = 0
        total_nodes = 0
        total_chunks = 0

        while True:
            async with self.__db.asession() as session:
                stmt = (
                    select(LawNode)
                    .where(col(LawNode.node_type).in_(EMBEDDABLE_NODE_TYPES))
                    .where(~exists(select(1).where(col(DocumentTable.node_id) == col(LawNode.id))))
                )
                if law_name is not None:
                    stmt = stmt.where(col(LawNode.law_name) == law_name)
                stmt = stmt.order_by(col(LawNode.law_name), col(LawNode.id)).offset(offset).limit(batch_size)

                result = await session.execute(stmt)
                rows = result.scalars().all()

                if not rows:
                    break

                texts = [(_build_embed_text(node), node.id, node.law_name) for node in rows]

            try:
                chunk_count = await doc_store.abatch_load_from_texts(
                    texts=texts,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                total_chunks += chunk_count
                total_nodes += len(rows)
            except Exception:
                logger.exception("Failed to embed batch of %d nodes for %s", len(rows), law_name)
                continue

            offset += batch_size
            logger.info("Embedded %s: %d nodes so far...", law_name, total_nodes)

        logger.info("Embedded %s: %d nodes, %d chunks total", law_name, total_nodes, total_chunks)
        return EmbedResultDict(
            law_name=law_name,
            articles_embedded=total_nodes,
            chunks_created=total_chunks,
        )
