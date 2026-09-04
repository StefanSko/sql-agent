from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

type JsonScalar = str | int | float | bool | None
type DatabaseScalar = JsonScalar | date | datetime | Decimal


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[ColumnSchema, ...]


@dataclass(frozen=True)
class TableNames:
    names: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    tables: tuple[TableSchema, ...]


@dataclass(frozen=True)
class QueryRow:
    values: dict[str, JsonScalar]

    @classmethod
    def from_mapping(cls, values: dict[str, DatabaseScalar]) -> QueryRow:
        return cls(values={name: _json_scalar(value) for name, value in values.items()})


@dataclass(frozen=True)
class QueryOk:
    rows: tuple[QueryRow, ...]
    kind: Literal["ok"] = field(default="ok", init=False)


@dataclass(frozen=True)
class QueryTruncated:
    rows: tuple[QueryRow, ...]
    row_cap: int
    kind: Literal["truncated"] = field(default="truncated", init=False)


@dataclass(frozen=True)
class QueryRejected:
    reason: str
    kind: Literal["rejected"] = field(default="rejected", init=False)


type QueryResult = QueryOk | QueryTruncated | QueryRejected


@dataclass(frozen=True)
class AgentAnswer:
    answer: str
    evidence: tuple[str, ...]


def _json_scalar(value: DatabaseScalar) -> JsonScalar:
    match value:
        case datetime() | date():
            return value.isoformat()
        case Decimal():
            return float(value)
        case str() | int() | float() | bool() | None:
            return value
