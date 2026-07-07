from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_email_server import app as app_module
from mcp_email_server.app import healthz
from mcp_email_server.config import EmailServer, EmailSettings


@pytest.fixture(autouse=True)
def reset_healthz_cache():
    app_module._healthz_cache.update({"expires": 0.0, "payload": None, "status_code": 200})
    yield


def _make_settings(account_names: list[str]) -> MagicMock:
    accounts = [
        EmailSettings(
            account_name=name,
            full_name="Test User",
            email_address=f"{name}@example.com",
            incoming=EmailServer(
                user_name=f"{name}@example.com",
                password="test_password",
                host="imap.example.com",
                port=993,
                use_ssl=True,
            ),
        )
        for name in account_names
    ]
    mock_settings = MagicMock()
    mock_settings.read_only = True
    mock_settings.get_accounts.return_value = accounts
    return mock_settings


class TestHealthz:
    @pytest.mark.asyncio
    async def test_healthy_when_all_logins_succeed(self):
        mock_client = MagicMock()
        mock_client.check_login = AsyncMock()
        with (
            patch("mcp_email_server.app.get_settings", return_value=_make_settings(["a", "b"])),
            patch("mcp_email_server.app.EmailClient", return_value=mock_client),
        ):
            response = await healthz(MagicMock())

        assert response.status_code == 200
        body = response.body.decode()
        assert '"status":"ok"' in body
        assert '"a":"ok"' in body
        assert '"b":"ok"' in body

    @pytest.mark.asyncio
    async def test_unhealthy_when_login_fails(self):
        mock_client = MagicMock()
        mock_client.check_login = AsyncMock(side_effect=RuntimeError("LOGIN failed"))
        with (
            patch("mcp_email_server.app.get_settings", return_value=_make_settings(["a"])),
            patch("mcp_email_server.app.EmailClient", return_value=mock_client),
        ):
            response = await healthz(MagicMock())

        assert response.status_code == 503
        body = response.body.decode()
        assert '"status":"unhealthy"' in body
        assert "LOGIN failed" in body

    @pytest.mark.asyncio
    async def test_result_is_cached(self):
        mock_client = MagicMock()
        mock_client.check_login = AsyncMock()
        with (
            patch("mcp_email_server.app.get_settings", return_value=_make_settings(["a"])),
            patch("mcp_email_server.app.EmailClient", return_value=mock_client) as client_cls,
        ):
            first = await healthz(MagicMock())
            second = await healthz(MagicMock())

        assert first.status_code == 200
        assert second.status_code == 200
        assert '"cached":true' in second.body.decode()
        client_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_accounts_is_healthy(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings([])):
            response = await healthz(MagicMock())

        assert response.status_code == 200
        assert '"accounts":{}' in response.body.decode()
