import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_email_server.http_auth import BearerAuthMiddleware

TOKEN = "test-token-123"  # noqa: S105 - not a real credential


def _make_client() -> TestClient:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/mcp", ok), Route("/healthz", ok)])
    return TestClient(BearerAuthMiddleware(app, TOKEN), raise_server_exceptions=False)


class TestBearerAuthMiddleware:
    def test_missing_header_is_rejected(self):
        response = _make_client().get("/mcp")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_wrong_token_is_rejected(self):
        response = _make_client().get("/mcp", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401

    def test_wrong_scheme_is_rejected(self):
        response = _make_client().get("/mcp", headers={"Authorization": f"Basic {TOKEN}"})
        assert response.status_code == 401

    def test_valid_token_passes(self):
        response = _make_client().get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert response.text == "ok"

    def test_healthz_is_protected_too(self):
        client = _make_client()
        assert client.get("/healthz").status_code == 401
        assert client.get("/healthz", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200

    def test_empty_token_is_a_configuration_error(self):
        with pytest.raises(ValueError, match="non-empty"):
            BearerAuthMiddleware(lambda scope, receive, send: None, "")
