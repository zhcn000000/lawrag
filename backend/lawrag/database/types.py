import ast
from collections import OrderedDict
from typing import Any
from typing import cast as typing_cast

from psycopg.adapt import Dumper, Loader
from sqlalchemy import Float, String, TypeDecorator, cast, func, type_coerce
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.sql.type_api import UserDefinedType


class BM25Loader(Loader):
    def load(self, data: bytes | bytearray | memoryview[int] | str) -> dict:
        if isinstance(data, memoryview):
            value = data.tobytes().decode("utf-8")
        elif isinstance(data, bytearray):
            value = bytes(data).decode("utf-8")
        elif isinstance(data, bytes):
            value = data.decode("utf-8")
        elif isinstance(data, str):
            value = data
        else:
            raise TypeError("Unsupported data type for BM25Loader: " + str(type(data)))
        return ast.literal_eval(value)


class BM25Dumper(Dumper):
    @classmethod
    def build(cls, oid: int) -> type[BM25Dumper]:
        cls_copy: type[BM25Dumper] = typing_cast(
            "type[BM25Dumper]",
            type(cls.__name__, (cls,), {}),  # type: ignore
        )
        cls_copy.oid = oid
        return cls_copy

    def dump(self, obj: dict | str) -> bytes:
        if isinstance(obj, str):
            return obj.encode("utf-8")
        sorted_dict = OrderedDict(sorted(obj.items()))
        return str(dict(sorted_dict)).encode("utf-8")


class BM25Vector(UserDefinedType):
    cache_ok = True
    _string = String()

    def get_col_spec(self, **kw) -> str:
        return "BM25VECTOR"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                sorted_dict = OrderedDict(sorted(value.items()))
                return str(dict(sorted_dict))
            return value

        return process

    def bind_expression(self, bindvalue):
        return cast(bindvalue, BM25Vector)

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                return ast.literal_eval(value)
            return value

        return process

    class comparator_factory(UserDefinedType.Comparator):  # ruff:ignore[invalid-class-name]
        def neg_bm25_rank(self, other):
            return self.op("<&>", return_type=Float)(other)


class Password(TypeDecorator):
    impl = String
    cache_ok = True

    def bind_expression(self, bindparam: Any) -> Any:
        return func.crypt(bindparam, func.gen_salt("bf"))

    class comparator_factory(String.Comparator):  # ruff:ignore[eq-without-hash,invalid-class-name] # pyright: ignore
        def __eq__(self, other: object) -> Any:
            local_pw = type_coerce(self.expr, String)
            return local_pw == func.crypt(other, local_pw)


ischema_names["bm25vector"] = BM25Vector  # type: ignore
