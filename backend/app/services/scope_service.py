"""California scope rules shared by every route (docs/api.md, "Coordinates and bbox")."""

from __future__ import annotations

from app.core.errors import ApiError
from app.core.scope import (
    CALIFORNIA_BBOX,
    clip_to_california,
    is_california_zip,
    point_in_california,
)
from app.schemas.query import Bbox, PointQuery

OUT_OF_SCOPE = "SmokeSense only forecasts for California."


def resolve_bbox(bbox: Bbox | None) -> Bbox:
    """All of California when bbox is omitted; otherwise bbox clipped to California.

    Raises 404 out_of_scope when bbox lies entirely outside California.
    """
    if bbox is None:
        return CALIFORNIA_BBOX
    clipped = clip_to_california(bbox)
    if clipped is None:
        raise ApiError(404, "out_of_scope", f"bbox {bbox} is outside California; {OUT_OF_SCOPE}")
    return clipped


def check_point(point: PointQuery) -> None:
    """Raises 404 out_of_scope for a location or ZIP outside California."""
    if point.zip is not None:
        if not is_california_zip(point.zip):
            raise ApiError(404, "out_of_scope", f"ZIP {point.zip} is outside California; {OUT_OF_SCOPE}")
        return
    if not point_in_california(point.lat, point.lon):
        raise ApiError(
            404, "out_of_scope", f"Point ({point.lat}, {point.lon}) is outside California; {OUT_OF_SCOPE}"
        )
