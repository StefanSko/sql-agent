from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class MultiTurnMeasurement:
    turn: int
    request_bytes: int
    input_tokens: int
    latency_seconds: float
    correct: bool
    context_limit: int


class ResendAssessment(StrEnum):
    ACCEPTABLE = "acceptable"
    UNACCEPTABLE = "unacceptable"
    INCOMPLETE = "incomplete"


def assess_full_resend(
    measurements: tuple[MultiTurnMeasurement, ...],
) -> ResendAssessment:
    by_turn = {measurement.turn: measurement for measurement in measurements}
    if set(by_turn) != {1, 5, 10}:
        return ResendAssessment.INCOMPLETE
    first = by_turn[1]
    tenth = by_turn[10]
    acceptable = (
        tenth.correct
        and tenth.input_tokens < tenth.context_limit * 0.25
        and tenth.latency_seconds <= first.latency_seconds * 2
    )
    return ResendAssessment.ACCEPTABLE if acceptable else ResendAssessment.UNACCEPTABLE
