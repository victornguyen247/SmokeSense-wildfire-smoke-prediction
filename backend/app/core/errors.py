"""The API's one error type (docs/api.md, "Errors").

Services raise ApiError; app/api/errors.py turns it into the shared error body
{"code": ..., "message": ...}. `code` is stable and checked by clients; `message` is
shown to people and must never contain internals such as a stack trace.
"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
