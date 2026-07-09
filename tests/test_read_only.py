from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_email_server import app as app_module
from mcp_email_server.app import (
    add_email_account,
    archive_emails,
    delete_emails,
    get_emails_content,
    mark_emails_as_read,
    move_emails,
    save_to_mailbox,
    send_email,
)
from mcp_email_server.config import EmailServer, EmailSettings, Settings
from mcp_email_server.emails.classic import _open_mailbox

WRITE_TOOL_NAMES = {
    "add_email_account",
    "send_email",
    "save_to_mailbox",
    "delete_emails",
    "mark_emails_as_read",
    "move_emails",
    "archive_emails",
}


def _make_settings(read_only: bool) -> MagicMock:
    email_settings = EmailSettings(
        account_name="test_account",
        full_name="Test User",
        email_address="test@example.com",
        incoming=EmailServer(
            user_name="test_user",
            password="test_password",
            host="imap.example.com",
            port=993,
            use_ssl=True,
        ),
        outgoing=EmailServer(
            user_name="test_user",
            password="test_password",
            host="smtp.example.com",
            port=465,
            use_ssl=True,
        ),
    )
    mock_settings = MagicMock()
    mock_settings.read_only = read_only
    mock_settings.allowed_recipients = []
    mock_settings.allowed_senders = []
    mock_settings.get_accounts.return_value = [email_settings]
    return mock_settings


class TestReadOnlyEnforcement:
    """Every mutating tool must reject direct calls in read-only mode -
    hiding a tool from list_tools does not prevent call_tool."""

    @pytest.mark.asyncio
    async def test_send_email_rejected(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            with pytest.raises(PermissionError, match="read-only"):
                await send_email("test_account", ["a@example.com"], "subject", "body")

    @pytest.mark.asyncio
    async def test_save_to_mailbox_rejected(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            with pytest.raises(PermissionError, match="read-only"):
                await save_to_mailbox("test_account", ["a@example.com"], "subject", "body")

    @pytest.mark.asyncio
    async def test_delete_emails_rejected(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            with pytest.raises(PermissionError, match="read-only"):
                await delete_emails("test_account", ["1"])

    @pytest.mark.asyncio
    async def test_mark_emails_as_read_rejected(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            with pytest.raises(PermissionError, match="read-only"):
                await mark_emails_as_read("test_account", ["1"])

    @pytest.mark.asyncio
    async def test_move_emails_rejected(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            with pytest.raises(PermissionError, match="read-only"):
                await move_emails("test_account", ["1"], "Archive")

    @pytest.mark.asyncio
    async def test_archive_emails_rejected(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            with pytest.raises(PermissionError, match="read-only"):
                await archive_emails("test_account", ["1"])

    @pytest.mark.asyncio
    async def test_add_email_account_rejected(self, email_settings):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            with pytest.raises(PermissionError, match="read-only"):
                await add_email_account(email_settings)

    @pytest.mark.asyncio
    async def test_get_emails_content_mark_as_read_rejected(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            with pytest.raises(PermissionError, match="read-only"):
                await get_emails_content("test_account", ["1"], mark_as_read=True)

    @pytest.mark.asyncio
    async def test_get_emails_content_without_mark_as_read_allowed(self):
        mock_handler = MagicMock()
        mock_handler.get_emails_content = AsyncMock(return_value=MagicMock())
        with (
            patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)),
            patch("mcp_email_server.app.dispatch_handler", return_value=mock_handler),
        ):
            await get_emails_content("test_account", ["1"])
            mock_handler.get_emails_content.assert_awaited_once()


class TestReadOnlyVisibility:
    @pytest.mark.asyncio
    async def test_write_tools_hidden_when_read_only(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=True)):
            tools = {tool.name for tool in await app_module.mcp.list_tools()}
        assert not tools & WRITE_TOOL_NAMES
        assert "list_emails_metadata" in tools
        assert "get_emails_content" in tools
        assert "list_mailboxes" in tools

    @pytest.mark.asyncio
    async def test_write_tools_visible_when_writable(self):
        with patch("mcp_email_server.app.get_settings", return_value=_make_settings(read_only=False)):
            tools = {tool.name for tool in await app_module.mcp.list_tools()}
        assert tools >= WRITE_TOOL_NAMES


class TestReadOnlyConfig:
    def test_read_only_defaults_to_false(self):
        assert Settings().read_only is False

    @pytest.mark.parametrize(("env_value", "expected"), [("true", True), ("1", True), ("false", False)])
    def test_read_only_env_override(self, monkeypatch, env_value, expected):
        monkeypatch.setenv("MCP_EMAIL_SERVER_READ_ONLY", env_value)
        assert Settings().read_only is expected


class TestOpenMailbox:
    @pytest.mark.asyncio
    async def test_examine_used_in_read_only_mode(self):
        imap = AsyncMock()
        imap.examine.return_value = MagicMock(result="OK")
        with patch("mcp_email_server.emails.classic.get_settings", return_value=MagicMock(read_only=True)):
            await _open_mailbox(imap, "INBOX")
        imap.examine.assert_awaited_once_with('"INBOX"')
        imap.select.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_examine_transitions_to_selected_state(self):
        # aioimaplib's examine() does not set SELECTED itself; without this
        # transition every subsequent SEARCH/FETCH fails client-side.
        import aioimaplib

        imap = AsyncMock()
        imap.examine.return_value = MagicMock(result="OK")
        with patch("mcp_email_server.emails.classic.get_settings", return_value=MagicMock(read_only=True)):
            await _open_mailbox(imap, "INBOX")
        assert imap.protocol.state == aioimaplib.SELECTED

    @pytest.mark.asyncio
    async def test_examine_failure_does_not_change_state(self):
        imap = AsyncMock()
        imap.protocol.state = "AUTH"
        imap.examine.return_value = MagicMock(result="NO")
        with patch("mcp_email_server.emails.classic.get_settings", return_value=MagicMock(read_only=True)):
            await _open_mailbox(imap, "INBOX")
        assert imap.protocol.state == "AUTH"

    @pytest.mark.asyncio
    async def test_select_used_in_writable_mode(self):
        imap = AsyncMock()
        with patch("mcp_email_server.emails.classic.get_settings", return_value=MagicMock(read_only=False)):
            await _open_mailbox(imap, "INBOX")
        imap.select.assert_awaited_once_with('"INBOX"')
        imap.examine.assert_not_awaited()
