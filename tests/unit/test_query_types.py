from __future__ import annotations

from sql_agent.types import (
    ColumnSchema,
    QueryOk,
    QueryRejected,
    QueryRow,
    QueryTruncated,
    TableSchema,
)


def test_query_variants_make_outcomes_explicit() -> None:
    row = QueryRow.from_mapping({"count": 3})

    assert QueryOk(rows=(row,)).rows[0].values == {"count": 3}
    assert QueryTruncated(rows=(row,), row_cap=1).row_cap == 1
    assert QueryRejected(reason="one statement required").reason == "one statement required"


def test_table_schema_is_immutable_and_typed() -> None:
    schema = TableSchema(
        name="things",
        columns=(ColumnSchema(name="thing_id", data_type="integer", nullable=False),),
    )

    assert schema.columns[0].name == "thing_id"
