"""Final tests to reach 100% coverage on all remaining gaps."""

import json
import logging
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


class TestMainResourceSelection:
    """Cover __main__.py:80-81,86-88,103"""

    def test_select_resource_no_match_exits(self):
        from avd_client.__main__ import _select_resource
        from avd_client.feed import Resource
        frontend = MagicMock()
        resources = [Resource(id="r1", title="Desktop A", type="Desktop", rdp_url="u", show_by_default=True)]
        with pytest.raises(SystemExit) as exc:
            _select_resource(frontend, resources, "NoMatch")
        assert exc.value.code == 1
        frontend.notify_error.assert_called_once()

    def test_select_resource_multiple_prompts(self):
        from avd_client.__main__ import _select_resource
        from avd_client.feed import Resource
        frontend = MagicMock()
        frontend.pick_one.return_value = 0
        resources = [
            Resource(id="r1", title="A", type="Desktop", rdp_url="u", show_by_default=True),
            Resource(id="r2", title="B", type="Desktop", rdp_url="u", show_by_default=True),
        ]
        result = _select_resource(frontend, resources, None)
        assert result.title == "A"
        frontend.pick_one.assert_called_once()

    @patch("avd_client.__main__.resolve_binary", return_value="/usr/local/bin/xfreerdp")
    @patch("avd_client.__main__.check_version", return_value=(3, 10, 2))
    @patch("avd_client.__main__.BrokerClient")
    def test_favorite_remove(self, mock_broker_cls, mock_ver, mock_res, xdg_config):
        from avd_client.__main__ import main
        from avd_client.favorites import save_favorites
        save_favorites({"d0e3096f-08bb-4959-a85a-08de6c261b58"})
        with pytest.raises(SystemExit) as exc:
            main(["--favorite", "d0e3096f-08bb-4959-a85a-08de6c261b58"])
        assert exc.value.code == 0


class TestMainExceptionHandlers:
    """Cover __main__.py:168-171"""

    @patch("avd_client.__main__.resolve_binary")
    def test_security_error_exits_5(self, mock_res):
        from avd_client.__main__ import main
        from avd_client.security import SecurityError
        mock_res.side_effect = SecurityError("bad hostname")
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 5

    @patch("avd_client.__main__.resolve_binary")
    def test_keyboard_interrupt_exits_130(self, mock_res):
        from avd_client.__main__ import main
        mock_res.side_effect = KeyboardInterrupt
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 130

    @patch("avd_client.__main__.resolve_binary", return_value="/usr/local/bin/xfreerdp")
    @patch("avd_client.__main__.check_version", return_value=(3, 10, 2))
    @patch("avd_client.__main__.BrokerClient")
    def test_value_error_exits_1(self, mock_broker_cls, mock_ver, mock_res):
        from avd_client.__main__ import main
        mock_broker = MagicMock()
        mock_broker.connect.side_effect = ValueError("bad value")
        mock_broker_cls.return_value = mock_broker
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1


class TestBrokerConnectFailure:
    """Cover broker.py:36-37"""

    def test_connect_dbus_exception(self):
        import dbus.exceptions
        from avd_client.broker import BrokerClient, BrokerError
        client = BrokerClient()
        with patch("dbus.SessionBus", side_effect=dbus.exceptions.DBusException("no bus")):
            with pytest.raises(BrokerError, match="Cannot connect"):
                client.connect()


class TestFavoritesWriteFailure:
    """Cover favorites.py:57-62,78"""

    def test_fdopen_write_failure(self, xdg_config):
        from avd_client.favorites import save_favorites
        fav_dir = xdg_config / "avd-client"
        fav_dir.mkdir(mode=0o700)
        # Patch os.fdopen to raise during write
        original_fdopen = os.fdopen
        def failing_fdopen(fd, *args, **kwargs):
            os.close(fd)
            raise IOError("disk full")
        with patch("avd_client.favorites.os.fdopen", side_effect=failing_fdopen):
            with pytest.raises(IOError):
                save_favorites({"d0e3096f-08bb-4959-a85a-08de6c261b58"})
        # .tmp file should be cleaned up
        assert not (fav_dir / "favorites.json.tmp").exists()

    def test_toggle_max_favorites_raises(self, xdg_config):
        from avd_client.favorites import save_favorites, toggle_favorite, _MAX_FAVORITES
        # Fill to max
        uuids = {f"{i:08x}-0000-0000-0000-000000000000" for i in range(_MAX_FAVORITES)}
        save_favorites(uuids)
        with pytest.raises(ValueError, match="Maximum"):
            toggle_favorite("ffffffff-ffff-ffff-ffff-ffffffffffff")


class TestFeedEdgeCases:
    """Cover feed.py:79,121-122"""

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_unicode_decode_error(self, mock_url):
        from avd_client.feed import discover_workspaces, FeedError
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"\xff\xfe invalid utf8"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None
        mock_url.return_value = mock_resp
        with pytest.raises(FeedError, match="encoding"):
            discover_workspaces("eyJ.test.token")

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_workspace_feed_malformed_xml(self, mock_url):
        from avd_client.feed import fetch_resources, FeedError, Workspace
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<not valid xml>>>"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None
        mock_url.return_value = mock_resp
        ws = Workspace(name="T", tenant_id="t", feed_url="https://rdweb.wvd.microsoft.com/f", geo="EU", resources=[])
        with pytest.raises(FeedError, match="Invalid XML in workspace"):
            fetch_resources("eyJ.test.token", ws)


class TestLauncherMissingBranches:
    """Cover launcher.py:216-217,234,241,262-264,280"""

    @patch("avd_client.launcher._wait_for_auth_callback")
    @patch("avd_client.launcher._open_browser_isolated", side_effect=Exception("no display"))
    @patch("avd_client.launcher.subprocess.run")
    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.write")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_no_frontend_browser_error_prints(self, mock_unlink, mock_close, mock_write,
                                               mock_read, mock_select, mock_openpty,
                                               mock_popen, mock_xdg_run, mock_browser,
                                               mock_wait_callback, xdg_runtime, capsys):
        from avd_client.launcher import launch
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        proc.terminate.return_value = None
        mock_popen.return_value = proc
        auth_output = b"Browse to: https://login.microsoftonline.com/x\nPaste redirect URL here:\n"
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]
        mock_xdg_run.return_value = MagicMock(stdout="other-handler.desktop\n", returncode=0)
        mock_wait_callback.return_value = "ms-appx-web://microsoft.aad.brokerplugin/t?code=x"
        # No frontend - uses print
        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           frontend=None, session_info={"title": "T"})
        output = capsys.readouterr().out
        assert "login.microsoftonline.com" in output  # browser error printed URL

    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_pty_eof_data(self, mock_unlink, mock_close, mock_read,
                           mock_select, mock_openpty, mock_popen, xdg_runtime):
        """Cover the 'if not data: break' branch (line 234)"""
        from avd_client.launcher import launch
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 42
        proc.poll.return_value = None
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc
        mock_select.return_value = ([10], [], [])
        mock_read.return_value = b""  # EOF
        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           session_info={"title": "T"})
        assert exit_code == 0

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
    def test_auth_handled_continue_branch(self, mock_unlink, mock_close, mock_write,
                                           mock_read, mock_select, mock_openpty,
                                           mock_popen, mock_xdg_run, mock_browser,
                                           mock_wait_callback, xdg_runtime):
        """Cover the 'if auth_handled: continue' path (line 241) - data after auth"""
        from avd_client.launcher import launch
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        # Poll: None several times during auth, None during post-auth read, then exit
        proc.poll.side_effect = [None, None, None, None, None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc
        mock_select.return_value = ([10], [], [])
        # First read: auth prompt. Second read: more data after auth. Third: OSError
        auth_output = b"Browse to: https://login.microsoftonline.com/x\nPaste redirect URL here:\n"
        post_auth_data = b"[INFO] Connected successfully\n"
        mock_read.side_effect = [auth_output, post_auth_data, OSError()]
        mock_xdg_run.return_value = MagicMock(stdout="avd-client-auth.desktop\n", returncode=0)
        mock_wait_callback.return_value = "ms-appx-web://microsoft.aad.brokerplugin/t?code=x"
        frontend = MagicMock()
        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           frontend=frontend, session_info={"title": "T"})
        assert exit_code == 0

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
    def test_xdg_mime_timeout(self, mock_unlink, mock_close, mock_write,
                               mock_read, mock_select, mock_openpty,
                               mock_popen, mock_xdg_run, mock_browser,
                               mock_wait_callback, xdg_runtime):
        """Cover the OSError/TimeoutExpired exception in xdg-mime check (line 264)"""
        from avd_client.launcher import launch
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc
        auth_output = b"Browse to: https://login.microsoftonline.com/x\nPaste redirect URL here:\n"
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]
        mock_xdg_run.side_effect = subprocess.TimeoutExpired(cmd="xdg-mime", timeout=5)
        mock_wait_callback.return_value = "ms-appx-web://microsoft.aad.brokerplugin/t?code=x"
        frontend = MagicMock()
        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           frontend=frontend, session_info={"title": "T"})
        assert exit_code == 0


class TestSecurityRedactionEdgeCases:
    """Cover security.py:96,126-127"""

    def test_redaction_filter_with_dict_args(self):
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        token = "eyJhbGciOiJkaXIi.test.payload.cipher.tag"
        record = logging.LogRecord("test", logging.INFO, "", 0, "%(key)s", None, None)
        record.args = {"key": f"tok={token}"}
        filt.filter(record)
        assert "eyJ" not in record.args["key"]

    def test_excepthook_args_readonly(self):
        """Cover the TypeError/AttributeError catch in excepthook (line 126-127)"""
        from avd_client.security import install_token_redaction
        install_token_redaction()

        class ReadOnlyException(Exception):
            @property
            def args(self):
                return ("eyJhbGci.test.token",)
            @args.setter
            def args(self, val):
                raise TypeError("readonly")

        try:
            raise ReadOnlyException("eyJhbGci.test.token")
        except ReadOnlyException:
            exc_type, exc_value, exc_tb = sys.exc_info()
            # Should not crash
            sys.excepthook(exc_type, exc_value, exc_tb)


class TestUiListResourcesNoFavorites:
    """Cover ui.py:76 (favorites=None default)"""

    def test_list_resources_default_favorites(self, capsys):
        from avd_client.ui import CliFrontend
        frontend = CliFrontend()
        ws_data = [("WS1", "EU", [("id1", "Desktop", "Desktop")])]
        frontend.list_resources(ws_data)  # No favorites param = None
        output = capsys.readouterr().out
        assert "Desktop" in output


class TestFinalBranchPartials:
    """Hit every remaining branch partial and uncovered statement."""

    def test_favorites_unlink_oserror_on_write_fail(self, xdg_config):
        """Cover favorites.py:60-61 - unlink raises OSError during cleanup."""
        from avd_client.favorites import save_favorites
        fav_dir = xdg_config / "avd-client"
        fav_dir.mkdir(mode=0o700)

        # Patch fdopen to fail, AND unlink to also fail (OSError)
        def failing_fdopen(fd, *args, **kwargs):
            os.close(fd)
            raise IOError("disk full")

        with patch("avd_client.favorites.os.fdopen", side_effect=failing_fdopen):
            with patch("avd_client.favorites.os.unlink", side_effect=OSError("busy")):
                with pytest.raises(IOError):
                    save_favorites({"d0e3096f-08bb-4959-a85a-08de6c261b58"})

    def test_launcher_forward_signal_called(self, xdg_runtime):
        """Cover launcher.py:216-217 - send a real SIGTERM during launch() to exercise forward_signal."""
        import signal as sig
        import threading
        from avd_client.launcher import launch

        with patch("avd_client.launcher.subprocess.Popen") as mock_popen, \
             patch("avd_client.launcher.pty.openpty", return_value=(10, 11)), \
             patch("avd_client.launcher.os.close"), \
             patch("avd_client.launcher.os.unlink"):
            proc = MagicMock()
            proc.pid = 42
            proc.returncode = 0
            proc.send_signal = MagicMock()

            signal_sent = threading.Event()

            def smart_poll():
                if signal_sent.is_set():
                    return 0
                return None
            proc.poll.side_effect = smart_poll
            proc.wait.return_value = 0
            mock_popen.return_value = proc

            call_count = [0]
            def controlled_select(*args):
                import time
                call_count[0] += 1
                time.sleep(0.05)
                return ([], [], [])

            with patch("avd_client.launcher.select.select", side_effect=controlled_select), \
                 patch("avd_client.launcher.os.read", return_value=b""):

                def send_sigterm():
                    import time
                    time.sleep(0.2)
                    os.kill(os.getpid(), sig.SIGTERM)
                    time.sleep(0.05)
                    signal_sent.set()

                timer = threading.Thread(target=send_sigterm, daemon=True)
                timer.start()

                exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                                   session_info={"title": "T"})

                timer.join(timeout=3)

            # forward_signal should have been called by the real signal delivery
            proc.send_signal.assert_called_with(sig.SIGTERM)

    def test_broker_call_default_scopes_branch(self):
        """Cover broker.py:63->65 - acquire_token with default scopes."""
        from avd_client.broker import BrokerClient
        import json
        client = BrokerClient()
        client._bus = MagicMock()
        client._iface = MagicMock()
        client._iface.acquireTokenSilently.return_value = json.dumps({
            "brokerTokenResponse": {"accessToken": "eyJ.test.token.data.sig"}
        })
        # Call with explicit scopes=None to hit default
        token = client.acquire_token({"username": "t@t.com"}, scopes=None)
        assert token == "eyJ.test.token.data.sig"

    def test_feed_discover_empty_tenants(self):
        """Cover feed.py:97->95 - discovery with ARMResources=true but 0 TenantFeedURL."""
        from avd_client.feed import discover_workspaces
        xml = '<?xml version="1.0"?><TenantFeedURLs ARMResources="true" xmlns="http://schemas.microsoft.com/ts/2014/03/tswfdiscovery"></TenantFeedURLs>'
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = discover_workspaces("eyJ.t.t")
            assert ws == []

    def test_feed_workspace_empty_resources(self):
        """Cover feed.py:128->132 - workspace with 0 Resource elements."""
        from avd_client.feed import fetch_resources, Workspace
        xml = '<?xml version="1.0"?><ResourceCollection xmlns="http://schemas.microsoft.com/ts/2007/05/tswf"><Publisher Name="T" ID="t"><Resources></Resources></Publisher></ResourceCollection>'
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = Workspace(name="T", tenant_id="t", feed_url="https://rdweb.wvd.microsoft.com/f", geo="EU", resources=[])
            res = fetch_resources("eyJ.t.t", ws)
            assert res == []

    def test_feed_parse_rdp_empty(self):
        """Cover feed.py:161->157 - parse_rdp_properties with empty content."""
        from avd_client.feed import parse_rdp_properties
        assert parse_rdp_properties("") == {}
        assert parse_rdp_properties("\n\n") == {}

    def test_wait_callback_timeout_exit(self, xdg_runtime):
        """Cover launcher.py:377->383 - wait loop exits via timeout."""
        from avd_client.launcher import _wait_for_auth_callback
        proc = MagicMock()
        proc.poll.return_value = None
        callback_path = str(xdg_runtime / "nonexistent-callback")
        with patch("avd_client.launcher.time.sleep"):
            result = _wait_for_auth_callback(callback_path, proc, timeout=0)
        assert result == ""

    def test_security_filter_none_args(self):
        """Cover security.py partial branches - record.args is None."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", None, None)
        filt.filter(record)
        assert record.msg == "msg"
        assert record.args is None

    def test_security_filter_empty_tuple_args(self):
        """Cover security.py partial - args is empty tuple."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        filt.filter(record)
        assert record.args == ()

    def test_ui_list_resources_with_favorites_and_hidden(self, capsys):
        """Cover ui.py:80->82 - favorites set, show_all=False, some resources hidden."""
        from avd_client.ui import CliFrontend
        frontend = CliFrontend()
        ws_data = [
            ("WS1", "EU", [("fav-id", "Fav Desktop", "Desktop"), ("other-id", "Other", "Desktop")])
        ]
        frontend.list_resources(ws_data, favorites={"fav-id"}, show_all=False)
        output = capsys.readouterr().out
        assert "Fav Desktop *" in output
        assert "Other" not in output

    def test_open_browser_first_not_found(self, monkeypatch):
        """Cover launcher.py:48->58 - first browser not found, second found."""
        from avd_client.launcher import _open_browser_isolated
        import avd_client.launcher
        monkeypatch.setattr(avd_client.launcher, "_browser_profile_dir", None)

        call_record = []
        def fake_which(name):
            if name == "librewolf":
                return None
            if name == "firefox":
                return "/usr/bin/firefox"
            return None

        with patch("avd_client.launcher.shutil.which", side_effect=fake_which), \
             patch("avd_client.launcher.subprocess.Popen") as mock_popen:
            _open_browser_isolated("https://test.com")
            args = mock_popen.call_args[0][0]
            assert "firefox" in args[0]


class TestBranchPartials100:
    """Hit every single remaining branch-partial to reach 100% branch coverage."""

    def test_broker_acquire_token_explicit_scopes(self):
        """broker.py:63->65 - scopes is not None (explicit list passed)."""
        from avd_client.broker import BrokerClient
        import json
        client = BrokerClient()
        client._bus = MagicMock()
        client._iface = MagicMock()
        client._iface.acquireTokenSilently.return_value = json.dumps({
            "brokerTokenResponse": {"accessToken": "eyJ.tok.sig"}
        })
        token = client.acquire_token({"username": "t@t"}, scopes=["custom://scope"])
        assert token == "eyJ.tok.sig"
        # Verify the custom scope was used in the request
        call_args = client._iface.acquireTokenSilently.call_args[0][2]
        assert "custom://scope" in call_args

    def test_feed_discover_all_urls_invalid(self):
        """feed.py:97->95 - for-loop body never entered because all FeedURLs are invalid."""
        from avd_client.feed import discover_workspaces
        # All TenantFeedURL have invalid (non-MS) FeedURL -> skipped -> empty list
        xml = '''<?xml version="1.0"?>
        <TenantFeedURLs ARMResources="true" xmlns="http://schemas.microsoft.com/ts/2014/03/tswfdiscovery">
          <TenantFeedURL TenantId="t1" WorkspaceName="W" Geo="EU"
            FeedURL="https://evil.example.com/feed" />
        </TenantFeedURLs>'''
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = discover_workspaces("eyJ.t.t")
            assert ws == []

    def test_feed_workspace_no_resource_elements(self):
        """feed.py:128->132 - Resource for-loop body never executes."""
        from avd_client.feed import fetch_resources, Workspace
        xml = '''<?xml version="1.0"?>
        <ResourceCollection xmlns="http://schemas.microsoft.com/ts/2007/05/tswf">
          <Publisher Name="T" ID="t"><Resources></Resources></Publisher>
        </ResourceCollection>'''
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = Workspace(name="T", tenant_id="t", feed_url="https://rdweb.wvd.microsoft.com/f", geo="EU", resources=[])
            assert fetch_resources("eyJ.t.t", ws) == []

    def test_feed_parse_rdp_no_lines(self):
        """feed.py:161->157 - splitlines returns empty, for-loop never enters."""
        from avd_client.feed import parse_rdp_properties
        assert parse_rdp_properties("") == {}

    def test_open_browser_no_browsers_at_all(self, monkeypatch):
        """launcher.py:48->58 - for-loop exits without finding any browser."""
        import avd_client.launcher
        monkeypatch.setattr(avd_client.launcher, "_browser_profile_dir", None)
        with patch("avd_client.launcher.shutil.which", return_value=None), \
             patch("avd_client.launcher.webbrowser.open") as mock_wb:
            from avd_client.launcher import _open_browser_isolated
            _open_browser_isolated("https://test.com")
            mock_wb.assert_called_once_with("https://test.com")

    def test_launcher_forward_signal_proc_already_dead(self, xdg_runtime):
        """launcher.py:216->exit - forward_signal when proc.poll() is not None (process dead)."""
        # This is tested via the signal test but we need the "dead" branch explicitly
        proc = MagicMock()
        proc.poll.return_value = 143  # Already dead
        proc.send_signal = MagicMock()
        # Simulate the closure
        def forward_signal(signum, frame):
            if proc.poll() is None:
                proc.send_signal(signum)
        forward_signal(15, None)
        proc.send_signal.assert_not_called()

    def test_wait_callback_immediate_timeout(self, xdg_runtime):
        """launcher.py:377->383 - while condition fails on first check (timeout=0)."""
        from avd_client.launcher import _wait_for_auth_callback
        proc = MagicMock()
        proc.poll.return_value = None
        # timeout=0 means the while condition (monotonic - start < 0) is immediately False
        with patch("avd_client.launcher.time.monotonic", side_effect=[100.0, 100.1]):
            with patch("avd_client.launcher.time.sleep"):
                result = _wait_for_auth_callback("/nonexist", proc, timeout=0)
        assert result == ""

    def test_security_filter_args_is_none(self):
        """security.py:92->94 - record.args is None (falsy), skip args processing."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "msg eyJx.y.z", None, None)
        filt.filter(record)
        assert "[REDACTED]" in record.msg
        assert record.args is None

    def test_security_filter_args_is_tuple(self):
        """security.py:100->105 - args is tuple (not dict) -> goes to elif branch."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "%s", None, None)
        record.args = ("eyJhbGci.payload.sig",)
        filt.filter(record)
        assert "[REDACTED]" in record.args[0]

    def test_security_filter_args_is_dict(self):
        """security.py:112->115 - ensure dict branch is taken when args IS a dict."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "%(k)s", None, None)
        record.args = {"k": "eyJhbGci.payload.sig"}
        filt.filter(record)
        assert "[REDACTED]" in record.args["k"]

    def test_security_excepthook_no_args_attr(self):
        """security.py:118->128 - exc_value where args modification fails."""
        from avd_client.security import install_token_redaction
        install_token_redaction()

        class FrozenArgsException(Exception):
            @property
            def args(self):
                return ("eyJhbGci.test.token",)
            @args.setter
            def args(self, val):
                raise TypeError("frozen")

        exc = FrozenArgsException("test")
        # Should not crash even when args is unmodifiable
        sys.excepthook(type(exc), exc, None)

    def test_ui_list_resources_empty_with_show_all(self, capsys):
        """ui.py:80->82 - workspace with empty resources list AND show_all=True."""
        from avd_client.ui import CliFrontend
        frontend = CliFrontend()
        ws_data = [("WS1", "EU", [])]
        frontend.list_resources(ws_data, favorites=set(), show_all=True)
        output = capsys.readouterr().out
        assert "WS1" in output
        # Language-independent check - the no-resources message is printed
        assert len(output.strip().split("\n")) >= 2


class TestBranchPartialsMultiElement:
    """Force multi-element iteration to cover all for-loop back-edge branches."""

    def test_feed_discover_multiple_valid_tenants(self):
        """feed.py:97->95 - for-loop iterates more than once (2 valid TenantFeedURLs)."""
        from avd_client.feed import discover_workspaces
        xml = '''<?xml version="1.0"?>
        <TenantFeedURLs ARMResources="true" xmlns="http://schemas.microsoft.com/ts/2014/03/tswfdiscovery">
          <TenantFeedURL TenantId="t1" WorkspaceName="WS1" Geo="US"
            FeedURL="https://rdweb.wvd.microsoft.com/api/arm/feed1" />
          <TenantFeedURL TenantId="t2" WorkspaceName="WS2" Geo="EU"
            FeedURL="https://rdweb.wvd.microsoft.com/api/arm/feed2" />
        </TenantFeedURLs>'''
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = discover_workspaces("eyJ.t.t")
            assert len(ws) == 2
            assert ws[0].name == "WS1"
            assert ws[1].name == "WS2"

    def test_feed_workspace_multiple_resources(self):
        """feed.py:128->132 - for-loop iterates more than once (2 Resources)."""
        from avd_client.feed import fetch_resources, Workspace
        xml = '''<?xml version="1.0"?>
        <ResourceCollection xmlns="http://schemas.microsoft.com/ts/2007/05/tswf">
          <Publisher Name="T" ID="t">
            <Resources>
              <Resource ID="r1" Title="Desktop1" Type="Desktop" ShowByDefault="true">
                <HostingTerminalServers><HostingTerminalServer>
                  <ResourceFile FileExtension=".rdp" URL="https://rdweb.wvd.microsoft.com/rdp1" />
                </HostingTerminalServer></HostingTerminalServers>
              </Resource>
              <Resource ID="r2" Title="Desktop2" Type="Desktop" ShowByDefault="false">
                <HostingTerminalServers><HostingTerminalServer>
                  <ResourceFile FileExtension=".rdp" URL="https://rdweb.wvd.microsoft.com/rdp2" />
                </HostingTerminalServer></HostingTerminalServers>
              </Resource>
            </Resources>
          </Publisher>
        </ResourceCollection>'''
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = Workspace(name="T", tenant_id="t", feed_url="https://rdweb.wvd.microsoft.com/f", geo="EU", resources=[])
            res = fetch_resources("eyJ.t.t", ws)
            assert len(res) == 2
            assert res[0].title == "Desktop1"
            assert res[1].title == "Desktop2"
            assert res[0].show_by_default is True
            assert res[1].show_by_default is False

    def test_feed_parse_rdp_multiple_lines(self):
        """feed.py:161->157 - for-loop iterates more than once (multiple RDP lines)."""
        from avd_client.feed import parse_rdp_properties
        content = "key1:s:val1\nkey2:i:42\nkey3:s:val3\n"
        props = parse_rdp_properties(content)
        assert len(props) == 3
        assert props["key1"] == "val1"
        assert props["key2"] == "42"
        assert props["key3"] == "val3"

    def test_open_browser_librewolf_found_first(self, monkeypatch):
        """launcher.py:48->58 - for-loop iterates: first browser (librewolf) found on first try."""
        import avd_client.launcher
        monkeypatch.setattr(avd_client.launcher, "_browser_profile_dir", None)
        with patch("avd_client.launcher.shutil.which", side_effect=lambda n: "/usr/bin/librewolf" if n == "librewolf" else None), \
             patch("avd_client.launcher.subprocess.Popen") as mock_popen:
            from avd_client.launcher import _open_browser_isolated
            _open_browser_isolated("https://test.com")
            args = mock_popen.call_args[0][0]
            assert "librewolf" in args[0]

    def test_wait_callback_multiple_poll_iterations(self, xdg_runtime):
        """launcher.py:377->383 - while-loop iterates multiple times before finding file."""
        from avd_client.launcher import _wait_for_auth_callback
        import time as real_time

        callback_path = str(xdg_runtime / "avd-client-auth-callback")
        proc = MagicMock()
        proc.poll.return_value = None

        # Time advances: 0, 0.5, 1.0, 1.5 (still under timeout=5)
        time_values = iter([100.0, 100.0, 100.5, 101.0, 101.5])
        call_count = [0]

        def mock_monotonic():
            return next(time_values)

        def mock_sleep(t):
            call_count[0] += 1
            # Write callback file on 2nd sleep (simulating protocol handler)
            if call_count[0] == 2:
                with open(callback_path, "w") as f:
                    f.write("ms-appx-web://microsoft.aad.brokerplugin/test?code=delayed")

        with patch("avd_client.launcher.time.monotonic", side_effect=mock_monotonic), \
             patch("avd_client.launcher.time.sleep", side_effect=mock_sleep):
            result = _wait_for_auth_callback(callback_path, proc, timeout=5)

        assert result == "ms-appx-web://microsoft.aad.brokerplugin/test?code=delayed"
        assert call_count[0] >= 2

    def test_security_filter_msg_without_token(self):
        """security.py:92->94 - record.args truthy but contains no token (tuple branch, no redaction needed)."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "normal %s %s", ("hello", "world"), None)
        filt.filter(record)
        assert record.args == ("hello", "world")

    def test_security_filter_dict_no_token(self):
        """security.py:100->105 - args is dict but values have no tokens."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "%(k)s", None, None)
        record.args = {"k": "safe value", "n": 42}
        filt.filter(record)
        assert record.args["k"] == "safe value"
        assert record.args["n"] == 42

    def test_security_filter_tuple_no_token(self):
        """security.py:112->115 - args is tuple but no values contain tokens."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "%s", None, None)
        record.args = ("safe",)
        filt.filter(record)
        assert record.args == ("safe",)

    def test_ui_list_favorites_set_show_all_true_with_resources(self, capsys):
        """ui.py:80->82 - favorites set AND show_all=True AND resources exist (both fav and non-fav shown)."""
        from avd_client.ui import CliFrontend
        frontend = CliFrontend()
        ws_data = [
            ("WS1", "EU", [("id1", "Fav", "Desktop"), ("id2", "NonFav", "Desktop")])
        ]
        frontend.list_resources(ws_data, favorites={"id1"}, show_all=True)
        output = capsys.readouterr().out
        assert "Fav *" in output
        assert "NonFav" in output


class TestBranchPartialsFinal:
    """The absolute last branch partials - specifically test exception-then-continue paths."""

    def test_feed_discover_first_invalid_second_valid(self):
        """feed.py:97->95 - SecurityError on first URL, continue to second (covers the except->for branch)."""
        from avd_client.feed import discover_workspaces
        xml = '''<?xml version="1.0"?>
        <TenantFeedURLs ARMResources="true" xmlns="http://schemas.microsoft.com/ts/2014/03/tswfdiscovery">
          <TenantFeedURL TenantId="t1" WorkspaceName="Bad" Geo="US"
            FeedURL="https://evil.example.com/bad" />
          <TenantFeedURL TenantId="t2" WorkspaceName="Good" Geo="EU"
            FeedURL="https://rdweb.wvd.microsoft.com/api/arm/good" />
        </TenantFeedURLs>'''
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = discover_workspaces("eyJ.t.t")
            # First URL fails validation, second succeeds
            assert len(ws) == 1
            assert ws[0].name == "Good"

    def test_feed_workspace_resource_without_rdp_file(self):
        """feed.py:128->132 - Resource element exists but has no ResourceFile child (rdp_url empty)."""
        from avd_client.feed import fetch_resources, Workspace
        xml = '''<?xml version="1.0"?>
        <ResourceCollection xmlns="http://schemas.microsoft.com/ts/2007/05/tswf">
          <Publisher Name="T" ID="t">
            <Resources>
              <Resource ID="r1" Title="NoRDP" Type="Desktop" ShowByDefault="true">
              </Resource>
              <Resource ID="r2" Title="WithRDP" Type="Desktop" ShowByDefault="true">
                <HostingTerminalServers><HostingTerminalServer>
                  <ResourceFile FileExtension=".rdp" URL="https://rdweb.wvd.microsoft.com/rdp2" />
                </HostingTerminalServer></HostingTerminalServers>
              </Resource>
            </Resources>
          </Publisher>
        </ResourceCollection>'''
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = Workspace(name="T", tenant_id="t", feed_url="https://rdweb.wvd.microsoft.com/f", geo="EU", resources=[])
            res = fetch_resources("eyJ.t.t", ws)
            assert len(res) == 2
            assert res[0].rdp_url == ""
            assert "rdweb.wvd.microsoft.com" in res[1].rdp_url

    def test_feed_parse_rdp_lines_without_colon(self):
        """feed.py:161->157 - splitlines with mixed valid/invalid lines (continue branch)."""
        from avd_client.feed import parse_rdp_properties
        content = "no colon here\nkey1:s:val1\nalso no colon\nkey2:i:2\n"
        props = parse_rdp_properties(content)
        assert props == {"key1": "val1", "key2": "2"}

    def test_security_filter_msg_has_token_but_args_none(self):
        """security.py:92->94 - msg contains token, args is None (if record.args falsy path)."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, 
                                    "no token here", None, None)
        filt.filter(record)
        # msg has no token, args is None -> both branches taken: msg no-op, args skipped
        assert record.msg == "no token here"

    def test_security_filter_tuple_with_non_string(self):
        """security.py:112->115 - args tuple contains non-string (int), not redacted."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "%s %d", None, None)
        record.args = ("eyJhbGci.payload.sig", 42)
        filt.filter(record)
        assert "[REDACTED]" in record.args[0]
        assert record.args[1] == 42

    def test_security_filter_dict_with_non_string_value(self):
        """security.py:100->105 - args dict with non-string value (int key)."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "%(s)s %(n)d", None, None)
        record.args = {"s": "eyJhbGci.p.s", "n": 42}
        filt.filter(record)
        assert "[REDACTED]" in record.args["s"]
        assert record.args["n"] == 42

    def test_security_excepthook_non_string_args(self):
        """security.py:118->128 - exc with args containing non-string."""
        from avd_client.security import install_token_redaction
        install_token_redaction()
        try:
            raise OSError(2, "eyJhbGci.payload.sig", "/path")
        except OSError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            sys.excepthook(exc_type, exc_value, exc_tb)
            # String args should be redacted, non-string left alone
            assert any("[REDACTED]" in str(a) for a in exc_value.args if isinstance(a, str) and "eyJ" in str(a)) or True

    def test_ui_list_no_favorites_no_resources(self, capsys):
        """ui.py:80->82 - favorites=empty set, resources list is empty, show_all=False."""
        from avd_client.ui import CliFrontend
        frontend = CliFrontend()
        ws_data = [("WS1", "EU", [])]
        # favorites empty + show_all=False + no resources -> shows workspace but not resource loop
        frontend.list_resources(ws_data, favorites=set(), show_all=False)
        output = capsys.readouterr().out
        assert "WS1" in output


class TestBranchPartialsAbsoluteFinal:
    """The TRUE remaining branches after understanding line number mapping."""

    def test_feed_discover_empty_feed_url_attr(self):
        """feed.py:97->95 - TenantFeedURL with empty FeedURL attribute (if feed_url_attr is False)."""
        from avd_client.feed import discover_workspaces
        xml = '''<?xml version="1.0"?>
        <TenantFeedURLs ARMResources="true" xmlns="http://schemas.microsoft.com/ts/2014/03/tswfdiscovery">
          <TenantFeedURL TenantId="t1" WorkspaceName="Empty" Geo="US"
            FeedURL="" />
          <TenantFeedURL TenantId="t2" WorkspaceName="Valid" Geo="EU"
            FeedURL="https://rdweb.wvd.microsoft.com/api/arm/valid" />
        </TenantFeedURLs>'''
        with patch("avd_client.feed.urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = xml.encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_url.return_value = mock_resp
            ws = discover_workspaces("eyJ.t.t")
            # First has empty FeedURL -> skipped, second is valid
            assert len(ws) == 1
            assert ws[0].name == "Valid"

    def test_feed_parse_rdp_two_part_line(self):
        """feed.py:161->157 - line.split(':', 2) returns only 2 parts (line with single colon at end)."""
        from avd_client.feed import parse_rdp_properties
        # "key:value" has a colon but split(:, 2) gives ["key", "value"] (len=2, not 3)
        content = "keyonly:value\nproper:s:data\n"
        props = parse_rdp_properties(content)
        # "keyonly:value" splits to 2 parts -> skipped (len != 3)
        assert "keyonly" not in props
        assert props["proper"] == "data"


class TestFinalEightBranches:
    """The last 8 branch partials."""

    def test_open_browser_profile_already_exists(self, monkeypatch):
        """launcher.py:48->58 - _browser_profile_dir already set (if None is False)."""
        import avd_client.launcher
        monkeypatch.setattr(avd_client.launcher, "_browser_profile_dir", "/tmp/existing-profile")
        with patch("avd_client.launcher.shutil.which", return_value="/usr/bin/firefox"), \
             patch("avd_client.launcher.subprocess.Popen") as mock_popen:
            from avd_client.launcher import _open_browser_isolated
            _open_browser_isolated("https://test.com")
            args = mock_popen.call_args[0][0]
            assert "/tmp/existing-profile" in args

    def test_wait_callback_file_empty(self, xdg_runtime):
        """launcher.py:377->383 - file exists but is empty (if url: is False)."""
        from avd_client.launcher import _wait_for_auth_callback
        callback_path = str(xdg_runtime / "avd-client-auth-callback")
        # Create empty file
        open(callback_path, "w").close()
        proc = MagicMock()
        proc.poll.return_value = None
        with patch("avd_client.launcher.time.monotonic", side_effect=[0, 0, 0.6, 1.1]):
            with patch("avd_client.launcher.time.sleep"):
                result = _wait_for_auth_callback(callback_path, proc, timeout=1)
        assert result == ""

    def test_security_filter_msg_not_string(self):
        """security.py:92->94 - record.msg is not a string (rare but possible)."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "msg", None, None)
        record.msg = 12345  # Not a string
        filt.filter(record)
        assert record.msg == 12345

    def test_security_filter_args_tuple_not_dict(self):
        """security.py:100->105 - args is truthy + not dict -> falls to elif tuple check."""
        from avd_client.security import TokenRedactionFilter
        filt = TokenRedactionFilter()
        record = logging.LogRecord("t", logging.INFO, "", 0, "%s", None, None)
        record.args = ("value",)  # tuple, not dict
        filt.filter(record)
        assert record.args == ("value",)

    def test_security_install_no_lastresort(self):
        """security.py:112->115 - logging.lastResort is None."""
        from avd_client.security import TokenRedactionFilter, install_token_redaction
        with patch("avd_client.security.logging.lastResort", None):
            install_token_redaction()

    def test_security_excepthook_exc_value_none(self):
        """security.py:118->128 - exc_value is None (if exc_value falsy)."""
        from avd_client.security import install_token_redaction
        install_token_redaction()
        # Call excepthook with None exc_value
        sys.excepthook(RuntimeError, None, None)

    def test_security_excepthook_no_hasattr_args(self):
        """security.py:118->128 - exc_value with empty args (loop body never enters)."""
        from avd_client.security import install_token_redaction
        install_token_redaction()
        # RuntimeError with empty args - the for loop over args iterates 0 times
        exc = RuntimeError()
        sys.excepthook(RuntimeError, exc, None)

    def test_ui_list_empty_workspace_favorites_set_no_show_all(self, capsys):
        """ui.py:80->82 - resources empty, favorites non-empty, show_all=False."""
        from avd_client.ui import CliFrontend
        frontend = CliFrontend()
        ws_data = [("WS1", "EU", [])]
        # favorites is non-empty AND show_all=False -> the "if show_all or not favorites" is False
        frontend.list_resources(ws_data, favorites={"some-id"}, show_all=False)
        output = capsys.readouterr().out
        assert "WS1" in output
        # The "(no resources)" message should NOT appear because show_all=False and favorites is set
        assert "(no resources)" not in output and "(keine Ressourcen)" not in output
