"""California scope for forecast points (docs/data-decisions.md #17).

DATA-04 forecast points are AirNow monitors located in California: AQS state
code 06, or a tribal ("TT") site listed in CA_TRIBAL_SITES after its location
has been checked. Tribal AQS codes carry no state, so each one is added by hand.
"""

from __future__ import annotations

CALIFORNIA_STATE_CODE = "06"

# Tribal (TT) AirNow sites confirmed to be in California, by 9-character AQS code.
CA_TRIBAL_SITES: dict[str, str] = {
    # Morongo Band of Mission Indians, Banning, Riverside County (33.9446, -116.8303).
    "TT5821016": "Morongo School",
}


def in_california_scope(aqs: str | None) -> bool:
    """Whether an AirNow site may be a forecast point.

    aqs is the 9-character AQS code, with or without dashes ("060072003",
    "06-007-2003", "TT-582-1016").
    """
    if not aqs:
        return False
    code = aqs.replace("-", "").strip()
    return code.startswith(CALIFORNIA_STATE_CODE) or code in CA_TRIBAL_SITES
