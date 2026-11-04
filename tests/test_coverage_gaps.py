"""Tests to close remaining coverage gaps."""

import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from avd_client.security import install_token_redaction, _JWT_REDACTION_PATTERN


class TestInstallTokenRedaction:
    def test_redacting_excepthook(self):
        install_token_redaction()
        token = "eyJhbGciOiJkaXIi.test.payload.cipher.tag"
        try:
            raise ValueError(f"Error with token: {token}")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            sys.excepthook(exc_type, exc_value, exc_tb)
            assert "eyJ" not in str(exc_value.args[0])
            assert "[REDACTED]" in str(exc_value.args[0])

    def test_excepthook_no_args(self):
        install_token_redaction()
        try:
            raise RuntimeError()
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            sys.excepthook(exc_type, exc_value, exc_tb)

    def test_filter_on_root_logger(self):
        install_token_redaction()
        root = logging.getLogger()
        has_filter = any(isinstance(f, type) or "TokenRedaction" in type(f).__name__
                         for f in root.filters)
        assert has_filter or len(root.filters) > 0


class TestFavoritesSaveEdgeCases:
    def test_save_handles_write_error(self, xdg_config):
        from avd_client.favorites import save_favorites
        fav_dir = xdg_config / "avd-client"
        fav_dir.mkdir(mode=0o700)
        # Make directory read-only to trigger error
        fav_dir.chmod(0o555)
        try:
            with pytest.raises(OSError):
                save_favorites({"d0e3096f-08bb-4959-a85a-08de6c261b58"})
        finally:
            fav_dir.chmod(0o755)

    def test_save_caps_at_max(self, xdg_config):
        from avd_client.favorites import save_favorites, load_favorites, _MAX_FAVORITES
        uuids = {f"{i:08x}-0000-0000-0000-000000000000" for i in range(1500)}
        save_favorites(uuids)
        loaded = load_favorites()
        assert len(loaded) == _MAX_FAVORITES


class TestMainConnectFlow:
    @patch("avd_client.__main__.resolve_binary", return_value="/usr/local/bin/xfreerdp")
    @patch("avd_client.__main__.check_version", return_value=(3, 10, 2))
    @patch("avd_client.__main__.BrokerClient")
    @patch("avd_client.__main__.discover_workspaces")
    @patch("avd_client.__main__.fetch_resources")
    @patch("avd_client.__main__.download_rdp_file")
    @patch("avd_client.__main__.build_argv")
    @patch("avd_client.__main__.launch")
    def test_full_connect_flow(self, mock_launch, mock_build, mock_download,
                                mock_fetch, mock_discover, mock_broker_cls,
                                mock_ver, mock_res):
        from avd_client.feed import Workspace, Resource
        mock_broker = MagicMock()
        mock_broker.connect.return_value = None
        mock_broker.get_version.return_value = "3.0.2"
        mock_broker.get_accounts.return_value = [{"username": "test@test.com"}]
        mock_broker.acquire_token.return_value = "eyJ.test.tok"
        mock_broker_cls.return_value = mock_broker

        ws = Workspace(name="EU", tenant_id="t1", feed_url="u", geo="EU", resources=[])
        mock_discover.return_value = [ws]
        mock_fetch.return_value = [
            Resource(id="r1", title="Desktop", type="Desktop", rdp_url="u", show_by_default=True)
        ]
        mock_download.return_value = "gatewayhostname:s:gw.wvd.microsoft.com\n"
        mock_build.return_value = (["/usr/local/bin/xfreerdp"], "/tmp/test.rdp")
        mock_launch.return_value = 0

        from avd_client.__main__ import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--workspace", "EU"])
        assert exc_info.value.code == 0
        mock_launch.assert_called_once()

    @patch("avd_client.__main__.resolve_binary", return_value="/usr/local/bin/xfreerdp")
    @patch("avd_client.__main__.check_version", return_value=(3, 10, 2))
    @patch("avd_client.__main__.BrokerClient")
    @patch("avd_client.__main__.discover_workspaces")
    @patch("avd_client.__main__.fetch_resources")
    def test_no_resources_exits_3(self, mock_fetch, mock_discover, mock_broker_cls,
                                   mock_ver, mock_res):
        from avd_client.feed import Workspace
        mock_broker = MagicMock()
        mock_broker.connect.return_value = None
        mock_broker.get_version.return_value = "3.0.2"
        mock_broker.get_accounts.return_value = [{"username": "test@test.com"}]
        mock_broker.acquire_token.return_value = "eyJ.test.tok"
        mock_broker_cls.return_value = mock_broker

        mock_discover.return_value = [
            Workspace(name="EU", tenant_id="t1", feed_url="u", geo="EU", resources=[])
        ]
        mock_fetch.return_value = []

        from avd_client.__main__ import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--workspace", "EU"])
        assert exc_info.value.code == 3


class TestLauncherNoFrontendBranches:
    """Cover the 'no frontend' print branches in launcher.py."""

    @patch("avd_client.launcher._wait_for_auth_callback")
    @patch("avd_client.launcher._open_browser_isolated")
    @patch("avd_client.launcher.subprocess.run")
    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.write")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_no_frontend_manual_fallback_eof(self, mock_unlink, mock_close, mock_write,
                                              mock_read, mock_select, mock_openpty,
                                              mock_popen, mock_xdg_run, mock_browser,
                                              mock_wait_callback, xdg_runtime):
        from avd_client.launcher import launch
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None, None]
        proc.returncode = 0
        proc.terminate.return_value = None
        mock_popen.return_value = proc

        auth_output = b"Browse to: https://login.microsoftonline.com/x\nPaste redirect URL here:\n"
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]
        mock_xdg_run.return_value = MagicMock(stdout="", returncode=0)
        mock_wait_callback.return_value = ""

        with patch("builtins.input", side_effect=EOFError):
            exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                               frontend=None, session_info={"title": "T"})
        assert exit_code == 130

    @patch("avd_client.launcher._wait_for_auth_callback")
    @patch("avd_client.launcher._open_browser_isolated")
    @patch("avd_client.launcher.subprocess.run")
    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.write")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_no_frontend_manual_invalid_url(self, mock_unlink, mock_close, mock_write,
                                             mock_read, mock_select, mock_openpty,
                                             mock_popen, mock_xdg_run, mock_browser,
                                             mock_wait_callback, xdg_runtime):
        from avd_client.launcher import launch
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None, None]
        proc.returncode = 0
        proc.terminate.return_value = None
        mock_popen.return_value = proc

        auth_output = b"Browse to: https://login.microsoftonline.com/x\nPaste redirect URL here:\n"
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]
        mock_xdg_run.return_value = MagicMock(stdout="", returncode=0)
        mock_wait_callback.return_value = ""

        with patch("builtins.input", return_value="https://evil.com"):
            exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                               frontend=None, session_info={"title": "T"})
        # Invalid URL from manual input should fail via validate
        # This tests the SecurityError path in the no-frontend branch
        assert exit_code == 1


class TestLauncherManualWithFrontendSecurityError:
    @patch("avd_client.launcher._wait_for_auth_callback")
    @patch("avd_client.launcher._open_browser_isolated")
    @patch("avd_client.launcher.subprocess.run")
    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.write")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_frontend_manual_invalid_url(self, mock_unlink, mock_close, mock_write,
                                          mock_read, mock_select, mock_openpty,
                                          mock_popen, mock_xdg_run, mock_browser,
                                          mock_wait_callback, xdg_runtime):
        from avd_client.launcher import launch
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None, None]
        proc.returncode = 0
        proc.terminate.return_value = None
        mock_popen.return_value = proc

        auth_output = b"Browse to: https://login.microsoftonline.com/x\nPaste redirect URL here:\n"
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]
        mock_xdg_run.return_value = MagicMock(stdout="", returncode=0)
        mock_wait_callback.return_value = ""

        frontend = MagicMock()
        frontend.prompt_url.return_value = "https://evil.com/not-valid"

        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           frontend=frontend, session_info={"title": "T"})
        assert exit_code == 1
        proc.terminate.assert_called()


class TestMainSelectWithMultipleWorkspaces:
    @patch("avd_client.__main__.resolve_binary", return_value="/usr/local/bin/xfreerdp")
    @patch("avd_client.__main__.check_version", return_value=(3, 10, 2))
    @patch("avd_client.__main__.BrokerClient")
    @patch("avd_client.__main__.discover_workspaces")
    @patch("avd_client.__main__.fetch_resources")
    @patch("avd_client.__main__.download_rdp_file")
    @patch("avd_client.__main__.build_argv")
    @patch("avd_client.__main__.launch")
    def test_interactive_workspace_select(self, mock_launch, mock_build, mock_download,
                                           mock_fetch, mock_discover, mock_broker_cls,
                                           mock_ver, mock_res):
        from avd_client.feed import Workspace, Resource
        from avd_client.__main__ import main
        mock_broker = MagicMock()
        mock_broker.connect.return_value = None
        mock_broker.get_version.return_value = "3.0.2"
        mock_broker.get_accounts.return_value = [{"username": "t@t.com"}]
        mock_broker.acquire_token.return_value = "eyJ.t.t"
        mock_broker_cls.return_value = mock_broker
        mock_discover.return_value = [
            Workspace(name="WS1", tenant_id="t1", feed_url="u1", geo="US", resources=[]),
            Workspace(name="WS2", tenant_id="t2", feed_url="u2", geo="EU", resources=[]),
        ]
        mock_fetch.return_value = [
            Resource(id="r1", title="D", type="Desktop", rdp_url="u", show_by_default=True)
        ]
        mock_download.return_value = "gatewayhostname:s:gw.wvd.microsoft.com\n"
        mock_build.return_value = (["/usr/local/bin/xfreerdp"], "/tmp/t.rdp")
        mock_launch.return_value = 0

        with patch("builtins.input", return_value="1"):
            with pytest.raises(SystemExit) as exc:
                main([])
            assert exc.value.code == 0


class TestMainLoggingLevels:
    def test_verbose_0(self):
        from avd_client.__main__ import setup_logging
        setup_logging(0)
        assert logging.getLogger().level == logging.WARNING

    def test_verbose_1(self):
        from avd_client.__main__ import setup_logging
        setup_logging(1)
        assert logging.getLogger().level == logging.INFO

    def test_verbose_2(self):
        from avd_client.__main__ import setup_logging
        setup_logging(2)
        assert logging.getLogger().level == logging.DEBUG


class TestLauncherFinallyCleanup:
    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_cleanup_handles_missing_rdp_file(self, mock_unlink, mock_close, mock_read,
                                               mock_select, mock_openpty, mock_popen, xdg_runtime):
        from avd_client.launcher import launch
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 1
        proc.poll.side_effect = [None, 0, 0]
        proc.returncode = 0
        mock_popen.return_value = proc
        mock_select.return_value = ([], [], [])
        # os.close raises on second call (master_fd already closed)
        mock_close.side_effect = [None, OSError("Bad fd")]
        # os.unlink raises FileNotFoundError for callback and rdp
        mock_unlink.side_effect = [FileNotFoundError, FileNotFoundError, FileNotFoundError]

        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           rdp_path="/tmp/nonexist.rdp", session_info={"title": "T"})
        assert exit_code == 0


class TestSecurityExcepthookEdgeCases:
    def test_excepthook_with_non_iterable_args(self):
        from avd_client.security import install_token_redaction
        install_token_redaction()
        # Exception with args that can't be iterated shouldn't crash
        exc = OSError(22, "Invalid argument", "/some/path")
        try:
            raise exc
        except OSError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            # Should not raise
            sys.excepthook(exc_type, exc_value, exc_tb)
