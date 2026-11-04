"""Tests for avd_client.__main__ — orchestration and integration."""

from unittest.mock import MagicMock, patch

import pytest

from avd_client.__main__ import _select_resource, _select_workspace, main
from avd_client.feed import Resource, Workspace


class TestSelectWorkspace:
    def test_preference_match(self):
        frontend = MagicMock()
        workspaces = [
            Workspace(name="US East", tenant_id="t1", feed_url="url1", geo="US", resources=[]),
            Workspace(name="Europe", tenant_id="t2", feed_url="url2", geo="EU", resources=[]),
        ]
        result = _select_workspace(frontend, workspaces, "Europe")
        assert result.name == "Europe"

    def test_preference_no_match_exits(self):
        frontend = MagicMock()
        workspaces = [Workspace(
            name="US East", tenant_id="t1", feed_url="u", geo="US", resources=[]
        )]
        with pytest.raises(SystemExit) as exc_info:
            _select_workspace(frontend, workspaces, "NoMatch")
        assert exc_info.value.code == 1
        frontend.notify_error.assert_called_once()

    def test_single_workspace_auto_selects(self):
        frontend = MagicMock()
        workspaces = [Workspace(
            name="Only One", tenant_id="t1", feed_url="u", geo="EU", resources=[]
        )]
        result = _select_workspace(frontend, workspaces, None)
        assert result.name == "Only One"
        frontend.pick_one.assert_not_called()

    def test_multiple_prompts_user(self):
        frontend = MagicMock()
        frontend.pick_one.return_value = 1
        workspaces = [
            Workspace(name="WS1", tenant_id="t1", feed_url="u1", geo="US", resources=[]),
            Workspace(name="WS2", tenant_id="t2", feed_url="u2", geo="EU", resources=[]),
        ]
        result = _select_workspace(frontend, workspaces, None)
        assert result.name == "WS2"
        frontend.pick_one.assert_called_once()


class TestSelectResource:
    def test_preference_match(self):
        frontend = MagicMock()
        resources = [
            Resource(
                id="r1", title="Desktop A", type="Desktop", rdp_url="u1",
                show_by_default=True
            ),
            Resource(
                id="r2", title="Desktop B", type="Desktop", rdp_url="u2",
                show_by_default=True
            ),
        ]
        result = _select_resource(frontend, resources, "Desktop B")
        assert result.title == "Desktop B"

    def test_single_resource_auto_selects(self):
        frontend = MagicMock()
        resources = [Resource(
            id="r1", title="Only", type="Desktop", rdp_url="u", show_by_default=True
        )]
        result = _select_resource(frontend, resources, None)
        assert result.title == "Only"


class TestMainFavorite:
    def test_toggle_add_exits_zero(self, xdg_config):
        with pytest.raises(SystemExit) as exc_info:
            main(["--favorite", "d0e3096f-08bb-4959-a85a-08de6c261b58"])
        assert exc_info.value.code == 0

    def test_invalid_uuid_exits(self, xdg_config):
        with pytest.raises(SystemExit) as exc_info:
            main(["--favorite", "not-a-uuid"])
        assert exc_info.value.code == 1


class TestMainErrorHandling:
    @patch("avd_client.__main__.resolve_binary")
    def test_launcher_error_exits_4(self, mock_resolve):
        from avd_client.launcher import LauncherError
        mock_resolve.side_effect = LauncherError("xfreerdp not found")
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 4

    @patch("avd_client.__main__.resolve_binary", return_value="/usr/local/bin/xfreerdp")
    @patch("avd_client.__main__.check_version", return_value=(3, 10, 2))
    @patch("avd_client.auth.BrokerClient")
    @patch("avd_client.auth._pkce_auth")
    def test_broker_error_exits_2(self, mock_pkce, mock_broker_cls, mock_ver, mock_res):
        from avd_client.auth import AuthError
        from avd_client.broker import BrokerError
        mock_broker = MagicMock()
        mock_broker.connect.side_effect = BrokerError("not installed")
        mock_broker_cls.return_value = mock_broker
        mock_pkce.side_effect = AuthError("no browser auth")
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2

    @patch("avd_client.__main__.resolve_binary", return_value="/usr/local/bin/xfreerdp")
    @patch("avd_client.__main__.check_version", return_value=(3, 10, 2))
    @patch("avd_client.auth.BrokerClient")
    @patch("avd_client.__main__.discover_workspaces")
    def test_feed_error_exits_3(self, mock_discover, mock_broker_cls, mock_ver, mock_res):
        from avd_client.feed import FeedError
        mock_broker = MagicMock()
        mock_broker.connect.return_value = None
        mock_broker.get_version.return_value = "3.0.2"
        mock_broker.get_accounts.return_value = [{"username": "test@test.com"}]
        mock_broker.acquire_token.return_value = "eyJ.test.token"
        mock_broker_cls.return_value = mock_broker
        mock_discover.side_effect = FeedError("no workspaces")
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 3


class TestMainListFlow:
    @patch("avd_client.__main__.resolve_binary", return_value="/usr/local/bin/xfreerdp")
    @patch("avd_client.__main__.check_version", return_value=(3, 10, 2))
    @patch("avd_client.auth.BrokerClient")
    @patch("avd_client.__main__.discover_workspaces")
    @patch("avd_client.__main__.fetch_resources")
    def test_list_exits_0(self, mock_fetch, mock_discover, mock_broker_cls, mock_ver,
                          mock_res, capsys):
        mock_broker = MagicMock()
        mock_broker.connect.return_value = None
        mock_broker.get_version.return_value = "3.0.2"
        mock_broker.get_accounts.return_value = [{"username": "test@test.com"}]
        mock_broker.acquire_token.return_value = "eyJ.test.token"
        mock_broker_cls.return_value = mock_broker
        mock_discover.return_value = [
            Workspace(name="WS1", tenant_id="t1", feed_url="u1", geo="EU", resources=[])
        ]
        mock_fetch.return_value = [
            Resource(id="r1", title="Desktop EU", type="Desktop", rdp_url="u", show_by_default=True)
        ]
        with pytest.raises(SystemExit) as exc_info:
            main(["--list", "--all"])
        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert "Desktop EU" in output
