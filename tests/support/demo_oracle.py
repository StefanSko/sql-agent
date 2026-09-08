"""Independent standard-library calculations: no reference SQL or frozen answers are read here."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise

from sql_agent.types import JsonScalar, QueryOk, QueryRow


@dataclass(frozen=True)
class Observation:
    trip_id: int
    rider_id: int
    start_station_id: int
    end_station_id: int
    started_at: datetime
    ended_at: datetime
    distance_km: Decimal

    @property
    def minutes(self) -> Decimal:
        return Decimal(int((self.ended_at - self.started_at).total_seconds())) / 60


@dataclass(frozen=True)
class Rider:
    rider_id: int
    signup_date: date
    plan: str


@dataclass(frozen=True)
class Station:
    station_id: int
    name: str
    district: str


def rounded(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def result(rows: list[dict[str, JsonScalar]]) -> QueryOk:
    return QueryOk(tuple(QueryRow(row) for row in rows))


def independent_answers(
    trips: tuple[Observation, ...],
    riders: tuple[Rider, ...],
    stations: tuple[Station, ...],
) -> dict[str, QueryOk]:
    rider_map = {rider.rider_id: rider for rider in riders}
    station_map = {station.station_id: station for station in stations}
    by_rider: dict[int, list[Observation]] = defaultdict(list)
    by_plan: dict[str, list[Observation]] = defaultdict(list)
    for trip in trips:
        by_rider[trip.rider_id].append(trip)
        by_plan[rider_map[trip.rider_id].plan].append(trip)
    departures = Counter(trip.start_station_id for trip in trips)
    arrivals = Counter(trip.end_station_id for trip in trips)
    months = Counter(trip.started_at.strftime("%Y-%m") for trip in trips)
    morning = [
        trip for trip in trips if trip.started_at.weekday() < 5 and 7 <= trip.started_at.hour < 10
    ]
    morning_departures = Counter(trip.start_station_id for trip in morning)
    morning_arrivals = Counter(trip.end_station_id for trip in morning)
    top_origins = sorted(departures, key=lambda station: (-departures[station], station))[:5]
    imbalance = sorted(
        station_map,
        key=lambda station: (
            -(morning_departures[station] - morning_arrivals[station]),
            station,
        ),
    )[:5]
    changes: list[dict[str, JsonScalar]] = []
    streaks: dict[int, int] = {}
    for rider_id, journeys in by_rider.items():
        latest = sorted(journeys, key=lambda trip: (trip.started_at, trip.trip_id), reverse=True)
        if len(latest) >= 2 and latest[0].distance_km > latest[1].distance_km:
            changes.append(
                {
                    "rider_id": rider_id,
                    "latest_trip_id": latest[0].trip_id,
                    "previous_trip_id": latest[1].trip_id,
                    "increase_km": rounded(latest[0].distance_km - latest[1].distance_km),
                }
            )
        days = sorted({trip.started_at.date() for trip in journeys})
        longest = current = 1
        for before, after in pairwise(days):
            current = current + 1 if after - before == timedelta(days=1) else 1
            longest = max(longest, current)
        streaks[rider_id] = longest
    # Sort the typed observations, not serialized result dictionaries.
    changed_riders = sorted(
        (
            sorted(group, key=lambda trip: (trip.started_at, trip.trip_id), reverse=True)[:2]
            for group in by_rider.values()
            if len(group) >= 2
        ),
        key=lambda pair: (-(pair[0].distance_km - pair[1].distance_km), pair[0].rider_id),
    )
    top_changed = [
        pair[0].rider_id for pair in changed_riders if pair[0].distance_km > pair[1].distance_km
    ][:5]
    cohorts: list[dict[str, JsonScalar]] = []
    for month in range(1, 12):
        members = [rider for rider in riders if rider.signup_date.month == month]
        retained = sum(
            any(trip.started_at.month == month + 1 for trip in by_rider[rider.rider_id])
            for rider in members
        )
        cohorts.append(
            {
                "cohort_month": f"2025-{month:02d}",
                "cohort_size": len(members),
                "retained_riders": retained,
                "retention_pct": rounded(Decimal(100 * retained) / len(members)),
            }
        )
    district_months = Counter(
        (station_map[trip.start_station_id].district, trip.started_at.month) for trip in trips
    )
    districts = sorted({station.district for station in stations})
    growth_winner = sorted(
        (district for district in districts if district_months[district, 11]),
        key=lambda district: (
            -Decimal(district_months[district, 12] - district_months[district, 11])
            / district_months[district, 11],
            district,
        ),
    )[0]
    november = district_months[growth_winner, 11]
    december = district_months[growth_winner, 12]
    daily = Counter(trip.started_at.date() for trip in trips)
    dates = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(365)]
    rolling = {
        day: sum(daily[day - timedelta(days=offset)] for offset in range(7)) for day in dates
    }
    busiest = min(dates, key=lambda day: (-rolling[day], day))
    percentiles: list[dict[str, JsonScalar]] = []
    for district in districts:
        durations = sorted(
            trip.minutes
            for trip in trips
            if trip.started_at.month == 7
            and station_map[trip.start_station_id].district == district
        )
        position = Decimal(len(durations) - 1) * Decimal("0.9")
        lower = int(position)
        fraction = position - lower
        percentile = durations[lower] + fraction * (durations[lower + 1] - durations[lower])
        percentiles.append({"district": district, "p90_minutes": rounded(percentile)})
    return {
        "d01-total": result([{"total_trips": len(trips)}]),
        "d02-plan-share": result(
            [
                {
                    "plan": plan,
                    "trip_count": len(group),
                    "trip_pct": rounded(Decimal(100 * len(group)) / len(trips)),
                }
                for plan, group in sorted(by_plan.items())
            ]
        ),
        "d03-popular-origins": result(
            [
                {
                    "station_id": station,
                    "name": station_map[station].name,
                    "departures": departures[station],
                }
                for station in top_origins
            ]
        ),
        "d04-monthly-volume": result(
            [
                {"month": f"2025-{month:02d}", "trip_count": months[f"2025-{month:02d}"]}
                for month in range(1, 13)
            ]
        ),
        "d05-morning-imbalance": result(
            [
                {
                    "station_id": station,
                    "departures": morning_departures[station],
                    "arrivals": morning_arrivals[station],
                    "net_departures": morning_departures[station] - morning_arrivals[station],
                }
                for station in imbalance
            ]
        ),
        "d06-latest-distance-change": result(
            [next(row for row in changes if row["rider_id"] == rider) for rider in top_changed]
        ),
        "d07-cohort-retention": result(cohorts),
        "d08-speed-anomalies": result(
            [
                {
                    "anomalous_trips": sum(
                        trip.distance_km * 60 / trip.minutes > 80
                        for trip in trips
                        if trip.minutes > 0
                    )
                }
            ]
        ),
        "h01-inactive": result(
            [{"inactive_riders": sum(not by_rider[rider.rider_id] for rider in riders)}]
        ),
        "h02-unused-stations": result(
            [
                {"station_id": station.station_id, "name": station.name}
                for station in stations
                if not departures[station.station_id] and not arrivals[station.station_id]
            ]
        ),
        "h03-plan-averages": result(
            [
                {
                    "plan": plan,
                    "avg_minutes": rounded(
                        sum((trip.minutes for trip in group), Decimal(0)) / len(group)
                    ),
                    "avg_km": rounded(
                        sum((trip.distance_km for trip in group), Decimal(0)) / len(group)
                    ),
                }
                for plan, group in sorted(by_plan.items())
            ]
        ),
        "h04-cross-district": result(
            [
                {
                    "cross_district_pct": rounded(
                        Decimal(
                            100
                            * sum(
                                station_map[trip.start_station_id].district
                                != station_map[trip.end_station_id].district
                                for trip in trips
                            )
                        )
                        / len(trips)
                    )
                }
            ]
        ),
        "h05-district-growth": result(
            [
                {
                    "district": growth_winner,
                    "november_trips": november,
                    "december_trips": december,
                    "growth_pct": rounded(Decimal(100 * (december - november)) / november),
                }
            ]
        ),
        "h06-consecutive-days": result(
            [
                {"rider_id": rider, "longest_streak": streaks[rider]}
                for rider in sorted(streaks, key=lambda rider: (-streaks[rider], rider))[:5]
            ]
        ),
        "h07-busiest-week": result(
            [{"window_end": busiest.isoformat(), "trip_count": rolling[busiest]}]
        ),
        "h08-duration-percentile": result(percentiles),
    }
