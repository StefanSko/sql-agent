from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import TypeAdapter

from sql_agent.types import JsonScalar, QueryOk, QueryResult, QueryRow

DATASET_VERSION = "demo-v1"
DATASET_DIRECTORY = Path(__file__).parents[4] / "data" / "demo" / "v1"


class Split(StrEnum):
    DEVELOPMENT = "development"
    HELDOUT = "heldout"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class Ordering(StrEnum):
    ORDERED = "ordered"
    UNORDERED = "unordered"


@dataclass(frozen=True)
class Question:
    case_id: str
    split: Split
    difficulty: Difficulty
    ordering: Ordering
    prompt: str


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    sql_sha256: str
    result: QueryOk


@dataclass(frozen=True)
class GoldenSuite:
    version: str
    schema_sha256: str
    seed_sha256: str
    questions_sha256: str
    cases: tuple[GoldenCase, ...]


@dataclass(frozen=True)
class EvaluationCase:
    question: Question
    reference_sql: str
    gold: GoldenCase


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_questions(directory: Path = DATASET_DIRECTORY) -> tuple[Question, ...]:
    questions = TypeAdapter(tuple[Question, ...]).validate_json(
        (directory / "questions.json").read_bytes()
    )
    identifiers = [question.case_id for question in questions]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate question IDs")
    if not questions or any(
        not identifier
        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in identifier)
        for identifier in identifiers
    ):
        raise ValueError("question IDs must be nonempty lowercase slugs")
    return questions


def load_cases(
    split: Split = Split.DEVELOPMENT, directory: Path = DATASET_DIRECTORY
) -> tuple[EvaluationCase, ...]:
    questions = load_questions(directory)
    gold = TypeAdapter(GoldenSuite).validate_json((directory / "golden.json").read_bytes())
    if gold.version != DATASET_VERSION:
        raise ValueError("golden dataset version mismatch")
    for name, expected in (
        ("schema.sql", gold.schema_sha256),
        ("seed.sql", gold.seed_sha256),
        ("questions.json", gold.questions_sha256),
    ):
        if file_sha256(directory / name) != expected:
            raise ValueError(f"frozen {name} checksum mismatch; do not silently rebaseline")
    by_id = {case.case_id: case for case in gold.cases}
    if len(by_id) != len(gold.cases) or set(by_id) != {q.case_id for q in questions}:
        raise ValueError("golden IDs must match question IDs exactly")
    cases: list[EvaluationCase] = []
    for question in questions:
        reference = directory / "reference" / f"{question.case_id}.sql"
        if file_sha256(reference) != by_id[question.case_id].sql_sha256:
            raise ValueError(f"reference SQL checksum mismatch: {question.case_id}")
        if question.split is split:
            cases.append(EvaluationCase(question, reference.read_text(), by_id[question.case_id]))
    return tuple(cases)


def rows_match(actual: QueryResult, expected: QueryOk, ordering: Ordering) -> bool:
    """Exact complete-result execution accuracy, not prose grading or scalar containment.

    Column names, nulls, strings, booleans and duplicate multiplicity matter. Numeric
    SQL types are equivalent (1 == 1.0); questions prescribe decimal rounding.
    """
    if not isinstance(actual, QueryOk):
        return False
    actual_rows = [_row_key(row) for row in actual.rows]
    expected_rows = [_row_key(row) for row in expected.rows]
    if ordering is Ordering.ORDERED:
        return actual_rows == expected_rows
    return Counter(actual_rows) == Counter(expected_rows)


def _row_key(row: QueryRow) -> str:
    return json.dumps(
        {key: _scalar_key(value) for key, value in row.values.items()}, sort_keys=True
    )


def _scalar_key(value: JsonScalar) -> str:
    match value:
        case None:
            return "null"
        case bool():
            return f"bool:{value}"
        case int() | float():
            return f"number:{Decimal(str(value)).normalize()}"
        case str():
            return f"string:{value}"
