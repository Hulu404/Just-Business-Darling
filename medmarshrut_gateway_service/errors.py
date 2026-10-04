"""Gateway error with a human message in Russian and an optional upstream original."""
from __future__ import annotations


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail

    def payload(self, show_detail: bool = False) -> dict:
        error = {"code": self.code, "message": self.message}
        if show_detail and self.detail:
            error["detail"] = self.detail
        return {"error": error}
