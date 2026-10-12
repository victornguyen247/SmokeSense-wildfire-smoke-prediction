"""California scope for forecast points (docs/data-decisions.md #17)."""

import pytest

from app.core.scope import CA_TRIBAL_SITES, in_california_scope


@pytest.mark.parametrize("aqs, expected", [
    ("06-021-0003", True),       # Willows-Colusa
    ("060072003", True),         # Paradise, no dashes
    ("TT-582-1016", True),       # Morongo School, listed tribal site
    ("TT5821016", True),
    ("41-029-0203", False),      # Ashland Fire Dept, Oregon
    ("32-005-TRP1", False),      # TRPA, Nevada
    ("TT-598-0500", False),      # tribal site not (yet) checked and listed
])
def test_in_california_scope(aqs, expected):
    assert in_california_scope(aqs) is expected


def test_tribal_sites_are_tt_codes():
    assert CA_TRIBAL_SITES
    assert all(code.startswith("TT") and len(code) == 9 for code in CA_TRIBAL_SITES)
