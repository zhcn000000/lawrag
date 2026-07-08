from typing import Annotated, Any
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

VECTOR_DIM = EMBEDDING_DIMS


class User(SQLModel, table=True):
    __tablename__ = "users"  # pyright: ignore

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

    @declared_attr  # type: ignore
    @classmethod
    def __table_args__(cls) -> tuple:
        return (CheckConstraint(func.length(col(cls.username)) > 0, name="chk_user_name_not_empty"),)


class SessionTable(SQLModel, table=True):
    __tablename__ = "session"  # pyright: ignore
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
    __tablename__ = "history"  # pyright: ignore
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


class LawNode(SQLModel, table=True):
    __tablename__ = "law_nodes"  # pyright: ignore

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
    parent_id: Annotated[
        UUID | None,
        Field(
            sa_column=Column(
                Uuid[UUID](native_uuid=True, as_uuid=True),
                ForeignKey("law_nodes.id", onupdate="CASCADE", ondelete="CASCADE"),
                nullable=True,
                index=True,
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
    node_type: Annotated[str, Field(sa_column=Column(String(16), nullable=False, index=True))]
    number: Annotated[int | None, Field(sa_column=Column(Integer, nullable=True))]
    content: Annotated[str | None, Field(sa_column=Column(Text, nullable=True))]
    path: Annotated[str, Field(sa_column=Column(String(256), nullable=False, server_default=""))]
    full_path: Annotated[str, Field(sa_column=Column(Text, nullable=False, server_default=""))]

    @declared_attr  # type: ignore
    @classmethod
    def __table_args__(cls) -> tuple:
        return (
            Index(
                "uq_law_nodes_law_name_path",
                col(cls.law_name),
                col(cls.path),
                unique=True,
            ),
        )


class DocumentTable(SQLModel, table=True):
    __tablename__ = "documents"  # pyright: ignore
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
    node_id: Annotated[
        UUID | None,
        Field(
            sa_column=Column(
                Uuid[UUID](native_uuid=True, as_uuid=True),
                ForeignKey(col(LawNode.id), onupdate="CASCADE", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
        ),
    ]
    content: Annotated[str, Field(sa_column=Column(Text, nullable=True))]
    vector: Annotated[
        list[float],
        Field(sa_column=Column(Vector(VECTOR_DIM), nullable=True)),
    ]
    bmvector: Annotated[dict[int, int], Field(sa_column=Column(BM25Vector, nullable=True))]

    @declared_attr  # type: ignore
    @classmethod
    def __table_args__(cls) -> tuple:
        return (
            Index(
                "ix_documents_vector",
                col(cls.vector),
                postgresql_using="vchordg",
                postgresql_ops={"vector": "vector_l2_ops"},
            ),
            Index(
                "ix_documents_bmvector",
                col(cls.bmvector),
                postgresql_using="bm25",
                postgresql_ops={"bmvector": "bm25_ops"},
            ),
        )
