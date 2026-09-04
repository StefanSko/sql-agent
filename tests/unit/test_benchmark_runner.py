from __future__ import annotations

from sql_agent.benchmark.runner import rotation_order
from sql_agent.benchmark.types import ExposureMode


def test_variant_order_rotates_by_repetition() -> None:
    assert rotation_order(0) == (
        ExposureMode.GRANULAR,
        ExposureMode.CATALOG,
        ExposureMode.PREFETCHED,
    )
    assert rotation_order(1) == (
        ExposureMode.CATALOG,
        ExposureMode.PREFETCHED,
        ExposureMode.GRANULAR,
    )
    assert rotation_order(2) == (
        ExposureMode.PREFETCHED,
        ExposureMode.GRANULAR,
        ExposureMode.CATALOG,
    )
    assert rotation_order(3) == rotation_order(0)
