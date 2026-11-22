"""/alerts/*: email alert subscriptions (docs/alerts.md section 2). POST only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.deps import get_alert_repository
from app.repositories.alerts import AlertRepository
from app.repositories.base import Body
from app.schemas.alerts import AlertSubscribeRequest, AlertTokenRequest
from app.services import alert_service

router = APIRouter(prefix="/alerts", tags=["alerts"])

AlertRepo = Annotated[AlertRepository, Depends(get_alert_repository)]


async def unsubscribe_token(
    request: Request, token: Annotated[str | None, Query(min_length=1, max_length=128)] = None
) -> str:
    """The token from the JSON body, or from the query string of an RFC 8058 one-click POST.

    The one-click form body (`List-Unsubscribe=One-Click`) carries nothing else, so it is
    not read. Bad bodies are 400 invalid_query, like every other validation error.
    """
    if token is not None:
        return token
    try:
        payload = await request.json()
    except ValueError:
        raise RequestValidationError(
            [{"loc": ("body",), "msg": "Expected a JSON body with a token", "type": "json_invalid"}]
        ) from None
    try:
        return AlertTokenRequest.model_validate(payload).token
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_input=False)) from None


@router.post("/subscriptions", status_code=202)
def post_subscription(body: AlertSubscribeRequest, repo: AlertRepo) -> Body:
    return alert_service.subscribe(repo, body)


@router.post("/confirm")
def post_confirm(body: AlertTokenRequest, repo: AlertRepo) -> Body:
    return alert_service.confirm(repo, body.token)


@router.post("/unsubscribe")
def post_unsubscribe(token: Annotated[str, Depends(unsubscribe_token)], repo: AlertRepo) -> Body:
    return alert_service.unsubscribe(repo, token)
