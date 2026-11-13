"""Shared California grid configuration and stable identifiers."""

TIGER_VINTAGE = 2025
PROJECTED_EPSG = 3310
DEFAULT_CELL_SIZE_M = 12_500
# Serving contract, Stage B: a cell uses monitors within the radius, and shows lower
# confidence past the other distance.
MAX_INTERPOLATION_DIST_KM = 50
LOW_CONFIDENCE_DIST_KM = 25


def california_grid_key(cell_size_m: int = DEFAULT_CELL_SIZE_M) -> str:
    """Return a stable key for this grid definition and Census boundary vintage."""
    if cell_size_m <= 0:
        raise ValueError("Cell size must be a positive number of meters")
    return (
        f"grid-ca-epsg{PROJECTED_EPSG}-{cell_size_m}m"
        f"-tiger{TIGER_VINTAGE}"
    )
