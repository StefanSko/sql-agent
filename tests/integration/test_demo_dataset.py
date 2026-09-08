from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest
from pydantic import TypeAdapter

from sql_agent.benchmark.demo import verify_references
from sql_agent.benchmark.demo_workload import Ordering, Split, load_cases, rows_match
from sql_agent.benchmark.seed import reset_database
from sql_agent.settings import Dsn
from tests.support.demo_oracle import Observation, Rider, Station, independent_answers

ROOT = Path(__file__).parents[2]
DATASET = ROOT / "data" / "demo" / "v1"


async def test_large_demo_is_reproducible_and_has_meaningful_edge_cases(pglite_dsn: Dsn) -> None:
    seed = DATASET / "seed.sql"
    assert seed.is_file(), "The large demo must have a checked-in deterministic seed"
    fingerprints: list[str] = []
    for _ in range(2):
        await reset_database(pglite_dsn, DATASET / "schema.sql", None)
        connection = await asyncpg.connect(str(pglite_dsn), ssl=False)
        try:
            await connection.execute(seed.read_text())
            counts = await connection.fetchrow(
                "SELECT (SELECT COUNT(*) FROM stations) AS stations, "
                "(SELECT COUNT(*) FROM riders) AS riders, "
                "(SELECT COUNT(*) FROM trips) AS trips"
            )
            assert counts is not None
            assert dict(counts) == {"stations": 100, "riders": 2000, "trips": 100000}
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM trips JOIN riders USING (rider_id) "
                    "WHERE started_at::date < signup_date OR ended_at <= started_at "
                    "OR started_at < '2025-01-01' OR ended_at >= '2026-01-01'"
                )
                == 0
            )
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM riders r WHERE NOT EXISTS "
                    "(SELECT 1 FROM trips t WHERE t.rider_id = r.rider_id)"
                )
                == 100
            )
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM stations s WHERE NOT EXISTS "
                    "(SELECT 1 FROM trips t WHERE t.start_station_id = s.station_id "
                    "OR t.end_station_id = s.station_id)"
                )
                == 2
            )
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM trips WHERE "
                    "distance_km * 3600 / EXTRACT(EPOCH FROM ended_at - started_at) > 80"
                )
                == 10
            )
            assert (
                await connection.fetchval(
                    "SELECT COUNT(DISTINCT DATE_TRUNC('month', started_at)) FROM trips"
                )
                == 12
            )
            assert await connection.fetchval("SELECT COUNT(*) FROM trips WHERE distance_km = 0") > 0
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM trips t JOIN stations s "
                    "ON t.end_station_id = s.station_id "
                    "WHERE EXTRACT(ISODOW FROM started_at) <= 5 "
                    "AND EXTRACT(HOUR FROM started_at) BETWEEN 7 AND 9 AND s.district <> 'Central'"
                )
                > 0
            ), "Commute patterns need counterflow/noise, not a trivial zero-arrivals shortcut"
            fingerprints.append(
                await connection.fetchval(
                    "SELECT md5(string_agg(t::text, ',' ORDER BY trip_id)) FROM trips t"
                )
            )
        finally:
            connection.terminate()
    assert fingerprints[0] == fingerprints[1]


async def test_all_frozen_answers_match_reference_sql_and_independent_python(
    pglite_dsn: Dsn,
) -> None:
    await reset_database(pglite_dsn, DATASET / "schema.sql", None)
    connection = await asyncpg.connect(str(pglite_dsn), ssl=False)
    try:
        await connection.execute((DATASET / "seed.sql").read_text())
        trips = TypeAdapter(tuple[Observation, ...]).validate_python(
            [dict(row) for row in await connection.fetch("SELECT * FROM trips ORDER BY trip_id")]
        )
        riders = TypeAdapter(tuple[Rider, ...]).validate_python(
            [
                dict(row)
                for row in await connection.fetch(
                    "SELECT rider_id, signup_date, plan FROM riders ORDER BY rider_id"
                )
            ]
        )
        stations = TypeAdapter(tuple[Station, ...]).validate_python(
            [
                dict(row)
                for row in await connection.fetch(
                    "SELECT station_id, name, district FROM stations ORDER BY station_id"
                )
            ]
        )
    finally:
        connection.terminate()
    answers = independent_answers(trips, riders, stations)
    cases = load_cases(Split.DEVELOPMENT) + load_cases(Split.HELDOUT)
    assert len(answers) == len(cases) == 16
    for case in cases:
        assert rows_match(answers[case.question.case_id], case.gold.result, Ordering.ORDERED), (
            case.question.case_id,
            answers[case.question.case_id],
            case.gold.result,
        )
    await verify_references(pglite_dsn, cases)
    connection = await asyncpg.connect(str(pglite_dsn), ssl=False, statement_cache_size=0)
    try:
        prepared = await connection.fetch("SELECT statement FROM pg_prepared_statements")
        assert not any(
            case.reference_sql.strip() in row["statement"] for case in cases for row in prepared
        ), "Reference SQL must not remain discoverable in PGlite's shared prepared-statement cache"
    finally:
        connection.terminate()


async def test_reference_verification_rejects_wrong_database(seeded_dsn: Dsn) -> None:
    # The tiny fixture is intentionally not the frozen large dataset.
    with pytest.raises(ValueError, match="reference result mismatch"):
        await verify_references(seeded_dsn, load_cases()[:1])
