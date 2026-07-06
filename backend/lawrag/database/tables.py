from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declared_attr
from sqlmodel import Field, SQLModel, col

from lawrag.documents.embedder import EMBEDDING_DIMS

from .types import BM25Vector, Password

if TYPE_CHECKING:
    from collections.abc import Callable

    def declared_attr(fn: Callable):
        return fn


VECTOR_DIM = EMBEDDING_DIMS


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Annotated[
        UUID,
        Field(
            sa_column=Column(
                Uuid[UUID](native_uuid=True, as_uuid=True),
                primary_key=True,
                server_default=func.uuidv7(),
            ),
        ),
    ]
    username: Annotated[
        str,
        Field(
            sa_column=Column(
                String,
                unique=True,
                nullable=False,
                index=True,
            ),
        ),
    ]
    password: Annotated[str, Field(sa_column=Column(Password, nullable=False))]

    @declared_attr
    @classmethod
    def __table_args__(cls) -> tuple:
        return (CheckConstraint(func.length(col(cls.username)) > 0, name="chk_user_name_not_empty"),)


class SessionTable(SQLModel, table=True):
    __tablename__ = "session"
    id: Annotated[
        UUID,
        Field(
            sa_column=Column(
                Uuid[UUID](native_uuid=True, as_uuid=True),
                primary_key=True,
                server_default=func.uuidv7(),
            ),
        ),
    ]
    name: Annotated[str, Field(sa_column=Column(String, nullable=True, index=True))]


class HistoryTable(SQLModel, table=True):
    __tablename__ = "history"
    id: Annotated[
        UUID,
        Field(
            sa_column=Column(
                Uuid[UUID](native_uuid=True, as_uuid=True),
                primary_key=True,
                server_default=func.uuidv7(),
            ),
        ),
    ]
    session_id: Annotated[
        UUID,
        Field(
            sa_column=Column(
                Uuid,
                ForeignKey(col(SessionTable.id), onupdate="CASCADE", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
        ),
    ]
    messages: Annotated[list[Any], Field(sa_column=Column(JSONB, nullable=False, server_default="[]"))]


class LawArticle(SQLModel, table=True):
    __tablename__ = "law_articles"

    id: Annotated[
        UUID,
        Field(
            sa_column=Column(
                Uuid[UUID](native_uuid=True, as_uuid=True),
                primary_key=True,
                server_default=func.uuidv7(),
            ),
        ),
    ]
    law_name: Annotated[
        str,
        Field(
            sa_column=Column(
                String(512),
                nullable=False,
                index=True,
            ),
        ),
    ]
    article_number: Annotated[
        int,
        Field(
            sa_column=Column(Integer, nullable=False),
        ),
    ]
    content: Annotated[str, Field(sa_column=Column(Text, nullable=False))]
    category: Annotated[str | None, Field(sa_column=Column(String(128), nullable=True, index=True))]
    meta: Annotated[
        dict,
        Field(default_factory=dict, sa_column=Column("metadata", JSONB, nullable=False, server_default="{}")),
    ]

    @declared_attr
    @classmethod
    def __table_args__(cls) -> tuple:
        return (
            Index(
                "idx_law_articles_law_name",
                col(cls.law_name),
            ),
            Index(
                "uq_law_article",
                col(cls.law_name),
                col(cls.article_number),
                unique=True,
            ),
        )


class DocumentTable(SQLModel, table=True):
    __tablename__ = "documents"
    id: Annotated[
        UUID,
        Field(
            sa_column=Column(
                Uuid[UUID](native_uuid=True, as_uuid=True),
                primary_key=True,
                server_default=func.uuidv7(),
            ),
        ),
    ]
    law_id: Annotated[
        UUID | None,
        Field(
            sa_column=Column(
                Uuid[UUID](native_uuid=True, as_uuid=True),
                ForeignKey(col(LawArticle.id), onupdate="CASCADE", ondelete="CASCADE"),
                nullable=True,
            ),
        ),
    ]
    content: Annotated[str, Field(sa_column=Column(Text, nullable=True))]
    vector: Annotated[
        list[float],
        Field(sa_column=Column(Vector(VECTOR_DIM), nullable=True)),
    ]
    bmvector: Annotated[dict[int, int], Field(sa_column=Column(BM25Vector, nullable=True))]

    @declared_attr
    @classmethod
    def __table_args__(cls) -> tuple:
        return (
            Index(
                "idx_documents_vector",
                col(cls.vector),
                postgresql_using="vchordg",
                postgresql_ops={"vector": "vector_l2_ops"},
            ),
            Index(
                "idx_documents_bmvector",
                col(cls.bmvector),
                postgresql_using="bm25",
                postgresql_ops={"bmvector": "bm25_ops"},
            ),
        )
