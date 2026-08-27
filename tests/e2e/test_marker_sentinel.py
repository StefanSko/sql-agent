from __future__ import annotations

import os

import pytest


@pytest.mark.e2e
def test_explicit_e2e_selection_runs_import_safe_sentinel() -> None:
    assert os.environ.get("RUN_E2E_SENTINEL") == "1"
