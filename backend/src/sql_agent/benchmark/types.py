from __future__ import annotations

from enum import StrEnum


class ExposureMode(StrEnum):
    """Tool surfaces retained only for comparative benchmark runs."""

    GRANULAR = "granular"
    CATALOG = "catalog"
    PREFETCHED = "prefetched"
