from __future__ import annotations

import pytest

from model.data_pjm import ZONES, load_pjm_series


def test_zones_matches_confirmed_pnode_mapping():
    """Regression guard: these five must match common.normalize_pjm.ZONE_PNODE_IDS exactly
    (confirmed live 2026-10-13) -- a typo here would silently query zero rows rather than
    raise, since the SQL filter would just never match anything."""
    assert ZONES == ("PECO", "PPL", "METED", "PENELEC", "DUQ")


def test_unknown_zone_raises_before_touching_the_database():
    with pytest.raises(ValueError):
        load_pjm_series("postgresql://nonexistent/db", "NOT_A_ZONE", None, None)
