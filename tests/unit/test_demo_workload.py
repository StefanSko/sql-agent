from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sql_agent.benchmark.demo import _main, _parser, freeze_gold, select_cases
from sql_agent.benchmark.demo_workload import Ordering, Split, load_cases, rows_match
from sql_agent.settings import Dsn
from sql_agent.types import QueryOk, QueryRejected, QueryRow, QueryTruncated

ROOT = Path(__file__).parents[2]
DATASET = ROOT / "data" / "demo" / "v1"


def test_reference_suite_is_versioned_split_and_has_full_answer_keys() -> None:
    assert (DATASET / "questions.json").is_file(), "Reference questions must be checked in"
    questions = json.loads((DATASET / "questions.json").read_text())
    assert len(questions) == 16
    assert len({question["case_id"] for question in questions}) == len(questions)
    for split in ("development", "heldout"):
        selected = [question for question in questions if question["split"] == split]
        assert len(selected) == 8
        assert {question["difficulty"] for question in selected} == {
            "easy",
            "medium",
            "hard",
            "expert",
        }
    for question in questions:
        assert (DATASET / "reference" / f"{question['case_id']}.sql").is_file()
    assert (DATASET / "golden.json").is_file(), "Expected results must be frozen, not regenerated"


def test_result_oracle_checks_whole_rows_order_duplicates_and_numeric_values() -> None:
    expected = QueryOk((QueryRow({"id": 1, "value": 2.0}), QueryRow({"id": 2, "value": 3.5})))
    same = QueryOk((QueryRow({"value": 2, "id": 1}), QueryRow({"value": 3.5, "id": 2})))
    assert rows_match(same, expected, Ordering.ORDERED)
    reversed_rows = QueryOk(tuple(reversed(same.rows)))
    assert not rows_match(reversed_rows, expected, Ordering.ORDERED)
    assert rows_match(reversed_rows, expected, Ordering.UNORDERED)
    assert not rows_match(QueryOk(same.rows[:1]), expected, Ordering.UNORDERED)
    assert not rows_match(QueryOk((same.rows[0], same.rows[0])), expected, Ordering.UNORDERED)
    assert not rows_match(
        QueryOk((QueryRow({"id": True, "value": 2}), same.rows[1])), expected, Ordering.ORDERED
    )
    assert not rows_match(QueryTruncated(same.rows, 2), expected, Ordering.ORDERED)
    assert not rows_match(QueryRejected("timeout"), expected, Ordering.ORDERED)


def test_heldout_is_opt_in_and_changed_seed_invalidates_gold(tmp_path: Path) -> None:
    cases = load_cases()
    assert len(cases) == 8
    assert all(case.question.split is Split.DEVELOPMENT for case in cases)
    heldout = load_cases(Split.HELDOUT)
    assert len(heldout) == 8
    assert not {case.question.case_id for case in cases} & {
        case.question.case_id for case in heldout
    }
    with pytest.raises(ValueError, match="not in development split"):
        select_cases(Split.DEVELOPMENT, [heldout[0].question.case_id])
    snapshot = tmp_path / "snapshot"
    shutil.copytree(DATASET, snapshot)
    with (snapshot / "seed.sql").open("a") as stream:
        stream.write("\n-- changed generator\n")
    with pytest.raises(ValueError, match=r"seed\.sql checksum mismatch"):
        load_cases(directory=snapshot)


async def test_questions_cli_prints_only_selected_prompts_without_model_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert "questions" in _parser().format_help()
    await _main(_parser().parse_args(["questions"]))
    output = capsys.readouterr().out
    assert "d07-cohort-retention" in output
    assert "h01-inactive" not in output
    assert "SELECT" not in output
    assert "100000" not in output


async def test_freeze_refuses_to_overwrite_before_connecting(tmp_path: Path) -> None:
    output = tmp_path / "golden.json"
    output.write_text("do not overwrite")
    with pytest.raises(FileExistsError):
        await freeze_gold(Dsn("postgresql://unused:unused@127.0.0.1:1/unused"), output)
    assert output.read_text() == "do not overwrite"
