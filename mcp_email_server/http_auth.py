import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerAuthMiddleware:
    """Require `Authorization: Bearer <token>` on every HTTP request.

    Applies to all routes, including /healthz: the health payload exposes
    account names, and the whole server holds mailbox credentials, so no
    endpoint is left unauthenticated.
    """

    def __init__(self, app: ASGIApp, token: str):
        if not token:
            raise ValueError("Bearer token must be non-empty")
        self.app = app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization = ""
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                authorization = value.decode("latin-1")
                break

        if not hmac.compare_digest(authorization, self._expected):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
