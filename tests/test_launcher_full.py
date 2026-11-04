"""Comprehensive tests for launcher.py — including launch() with full PTY mocking."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from avd_client.launcher import (
    LauncherError,
    _build_exec_env,
    _open_browser_isolated,
    _wait_for_auth_callback,
    build_argv,
    check_version,
    launch,
    resolve_binary,
)
from avd_client.security import SecurityError

SAMPLE_RDP = (
    "gatewayusagemethod:i:1\n"
    "gatewayhostname:s:afdfp-rdgateway.wvd.microsoft.com:443\n"
    "full address:s:rdgateway.wvd.microsoft.com\n"
    "loadbalanceinfo:s:mth://localhost/pool1/host1\n"
)
DUMMY_TOKEN = "eyJhbGciOiJkaXIi..ivdata.ciphertext.authtag"


class TestResolveBinary:
    @patch("avd_client.launcher.shutil.which")
    def test_finds_xfreerdp3(self, mock_which):
        mock_which.return_value = "/usr/local/bin/xfreerdp3"
        with patch("os.path.realpath", return_value="/usr/local/bin/xfreerdp3"):
            with patch("os.path.isfile", return_value=True):
                assert resolve_binary() == "/usr/local/bin/xfreerdp3"

    @patch("avd_client.launcher.shutil.which")
    def test_not_found_raises(self, mock_which):
        mock_which.return_value = None
        with patch("avd_client.launcher.FREERDP_BIN", ""):
            with pytest.raises(LauncherError, match="not found"):
                resolve_binary()

    @patch("avd_client.launcher.shutil.which")
    def test_outside_allowlist_raises(self, mock_which):
        mock_which.return_value = "/tmp/evil/xfreerdp3"
        with patch("os.path.realpath", return_value="/tmp/evil/xfreerdp3"):
            with pytest.raises(LauncherError, match="outside allowed"):
                resolve_binary()

    def test_env_override_not_exist(self, monkeypatch):
        monkeypatch.setattr("avd_client.launcher.FREERDP_BIN", "/nonexistent/xfreerdp3")
        with patch("os.path.realpath", return_value="/nonexistent/xfreerdp3"):
            with patch("os.path.isfile", return_value=False):
                with pytest.raises(LauncherError, match="does not exist"):
                    resolve_binary()


class TestCheckVersion:
    @patch("avd_client.launcher.subprocess.run")
    def test_parses_version(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="This is FreeRDP version 3.10.2\n", stderr="")
        assert check_version("/usr/local/bin/xfreerdp") == (3, 10, 2)

    @patch("avd_client.launcher.subprocess.run")
    def test_old_version_raises(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="FreeRDP version 2.11.7\n", stderr="")
        with pytest.raises(LauncherError, match="too old"):
            check_version("/usr/local/bin/xfreerdp")

    @patch("avd_client.launcher.subprocess.run")
    def test_timeout_returns_zero(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=5)
        assert check_version("/usr/local/bin/xfreerdp") == (0, 0, 0)

    @patch("avd_client.launcher.subprocess.run")
    def test_oserror_returns_zero(self, mock_run):
        mock_run.side_effect = OSError("No such file")
        assert check_version("/usr/local/bin/xfreerdp") == (0, 0, 0)

    @patch("avd_client.launcher.subprocess.run")
    def test_no_version_string(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error: unknown option")
        assert check_version("/usr/local/bin/xfreerdp") == (0, 0, 0)


class TestBuildArgv:
    def test_basic(self):
        cmd, rdp_path = build_argv(
            "/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "user@example.com"
        )
        try:
            assert cmd[0] == "/usr/local/bin/xfreerdp"
            assert any("bearer:" in c for c in cmd)
            assert "/cert:tofu" in cmd
        finally:
            os.unlink(rdp_path)

    def test_all_options(self):
        cmd, rdp_path = build_argv(
            "/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "user@example.com",
            clipboard=True, sound=True, microphone=True, multimon=True
        )
        try:
            assert "+clipboard" in cmd
            assert "/sound:sys:pulse" in cmd
            assert "/microphone:sys:pulse" in cmd
            assert "/multimon" in cmd
        finally:
            os.unlink(rdp_path)

    def test_rdp_file_permissions(self):
        _, rdp_path = build_argv(
            "/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "user@example.com"
        )
        try:
            assert oct(os.stat(rdp_path).st_mode & 0o777) == "0o600"
        finally:
            os.unlink(rdp_path)

    def test_invalid_hostname_raises(self):
        bad_rdp = SAMPLE_RDP.replace("afdfp-rdgateway.wvd.microsoft.com", "evil.com")
        with pytest.raises(SecurityError):
            build_argv("/usr/local/bin/xfreerdp", bad_rdp, DUMMY_TOKEN, "user@example.com")

    def test_invalid_upn_raises(self):
        with pytest.raises(SecurityError):
            build_argv("/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "")

    def test_no_gateway_hostname_ok(self):
        rdp = "full address:s:rdgateway.wvd.microsoft.com\nloadbalanceinfo:s:x\n"
        cmd, rdp_path = build_argv("/usr/local/bin/xfreerdp", rdp, DUMMY_TOKEN, "user@example.com")
        try:
            assert cmd[0] == "/usr/local/bin/xfreerdp"
        finally:
            os.unlink(rdp_path)


class TestBuildExecEnv:
    def test_path_fixed(self):
        env = _build_exec_env()
        assert env["PATH"] == "/usr/bin:/usr/local/bin:/bin"

    def test_strips_ld_preload(self, monkeypatch):
        monkeypatch.setenv("LD_PRELOAD", "/evil.so")
        env = _build_exec_env()
        assert "LD_PRELOAD" not in env

    def test_keeps_display(self, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":99")
        env = _build_exec_env()
        assert env["DISPLAY"] == ":99"


class TestOpenBrowserIsolated:
    @patch("avd_client.launcher.subprocess.Popen")
    @patch(
        "avd_client.launcher.shutil.which",
        side_effect=lambda n: "/usr/bin/firefox" if n == "firefox" else None,
    )
    def test_opens_firefox(self, mock_which, mock_popen, monkeypatch):
        import avd_client.launcher
        monkeypatch.setattr(avd_client.launcher, "_browser_profile_dir", None)
        _open_browser_isolated("https://example.com")
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "firefox" in args[0]
        assert "--no-remote" in args
        assert "https://example.com" in args

    @patch("avd_client.launcher.webbrowser.open")
    @patch("avd_client.launcher.shutil.which", return_value=None)
    def test_fallback_to_webbrowser(self, mock_which, mock_wb):
        _open_browser_isolated("https://example.com")
        mock_wb.assert_called_once_with("https://example.com")

    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.shutil.which", return_value="/usr/bin/librewolf")
    def test_creates_profile_with_user_js(self, mock_which, mock_popen, monkeypatch, tmp_path):
        import avd_client.launcher
        monkeypatch.setattr(avd_client.launcher, "_browser_profile_dir", None)
        monkeypatch.setattr("avd_client.launcher.tempfile.mkdtemp", lambda prefix: str(tmp_path))
        _open_browser_isolated("https://test.com")
        user_js = tmp_path / "user.js"
        assert user_js.exists()
        content = user_js.read_text()
        assert "webrender" in content


class TestWaitForAuthCallback:
    def test_reads_callback_file(self, xdg_runtime):
        callback_path = str(xdg_runtime / "avd-client-auth-callback")
        proc = MagicMock()
        proc.poll.return_value = None
        proc.returncode = 0

        # Write callback file
        with open(callback_path, "w") as f:
            f.write("ms-appx-web://microsoft.aad.brokerplugin/?code=test123")

        result = _wait_for_auth_callback(callback_path, proc, timeout=2)
        assert result == "ms-appx-web://microsoft.aad.brokerplugin/?code=test123"

    def test_returns_empty_on_timeout(self, xdg_runtime):
        callback_path = str(xdg_runtime / "avd-client-auth-callback")
        proc = MagicMock()
        proc.poll.return_value = None

        result = _wait_for_auth_callback(callback_path, proc, timeout=1)
        assert result == ""

    def test_returns_empty_when_proc_exits(self, xdg_runtime):
        callback_path = str(xdg_runtime / "avd-client-auth-callback")
        proc = MagicMock()
        proc.poll.return_value = 1
        proc.returncode = 1

        result = _wait_for_auth_callback(callback_path, proc, timeout=5)
        assert result == ""

    def test_handles_io_error(self, xdg_runtime):
        callback_path = str(xdg_runtime / "avd-client-auth-callback")
        # Create a directory instead of file to trigger IOError
        os.makedirs(callback_path, exist_ok=True)
        proc = MagicMock()
        proc.poll.return_value = None

        result = _wait_for_auth_callback(callback_path, proc, timeout=1)
        assert result == ""


class TestLaunch:
    @patch("avd_client.launcher._wait_for_auth_callback")
    @patch("avd_client.launcher._open_browser_isolated")
    @patch("avd_client.launcher.subprocess.run")  # xdg-mime check
    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.write")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_happy_path_with_callback(self, mock_unlink, mock_close, mock_write,
                                       mock_read, mock_select, mock_openpty,
                                       mock_popen, mock_xdg_run, mock_browser,
                                       mock_wait_callback, xdg_runtime):
        # Setup PTY
        mock_openpty.return_value = (10, 11)

        # Setup FreeRDP process
        proc = MagicMock()
        proc.pid = 12345
        # poll: first few None (running), then simulate auth, then exit
        proc.poll.side_effect = [None, None, None, None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        # PTY read: simulate FreeRDP auth prompt
        auth_output = (
            b"Browse to: https://login.microsoftonline.com/common/oauth2/v2.0/authorize?test=1\n"
            b"Paste redirect URL here:\n"
        )
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError("pty closed")]

        # xdg-mime check
        mock_xdg_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="avd-client-auth.desktop\n", stderr="")

        # Auth callback returns valid URL
        mock_wait_callback.return_value = (
            "ms-appx-web://microsoft.aad.brokerplugin/a85cf173?code=abc123"
        )

        frontend = MagicMock()
        exit_code = launch(
            "/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp", "/tmp/test.rdp"],
            rdp_path="/tmp/test.rdp", frontend=frontend, session_info={"title": "Test"}
        )

        assert exit_code == 0
        frontend.on_browser_opened.assert_called_once()
        frontend.on_auth_success.assert_called_once()
        mock_browser.assert_called_once()

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
    def test_manual_fallback_valid_url(self, mock_unlink, mock_close, mock_write,
                                        mock_read, mock_select, mock_openpty,
                                        mock_popen, mock_xdg_run, mock_browser,
                                        mock_wait_callback, xdg_runtime):
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        auth_output = (
            b"Browse to: https://login.microsoftonline.com/test\n"
            b"Paste redirect URL here:\n"
        )
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]

        mock_xdg_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_wait_callback.return_value = ""  # No automatic callback

        frontend = MagicMock()
        frontend.prompt_url.return_value = (
            "ms-appx-web://microsoft.aad.brokerplugin/test?code=manual"
        )

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
    def test_manual_fallback_empty_url_returns_1(self, mock_unlink, mock_close, mock_write,
                                                   mock_read, mock_select, mock_openpty,
                                                   mock_popen, mock_xdg_run, mock_browser,
                                                   mock_wait_callback, xdg_runtime):
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None]
        proc.returncode = 0
        proc.terminate.return_value = None
        mock_popen.return_value = proc

        auth_output = (
            b"Browse to: https://login.microsoftonline.com/x\n"
            b"Paste redirect URL here:\n"
        )
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]

        mock_xdg_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_wait_callback.return_value = ""

        frontend = MagicMock()
        frontend.prompt_url.return_value = ""  # User cancels

        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           frontend=frontend, session_info={"title": "T"})
        assert exit_code == 1
        proc.terminate.assert_called()

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
    def test_invalid_callback_url_rejected(self, mock_unlink, mock_close, mock_write,
                                            mock_read, mock_select, mock_openpty,
                                            mock_popen, mock_xdg_run, mock_browser,
                                            mock_wait_callback, xdg_runtime):
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        proc.terminate.return_value = None
        mock_popen.return_value = proc

        auth_output = (
            b"Browse to: https://login.microsoftonline.com/x\n"
            b"Paste redirect URL here:\n"
        )
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]

        mock_xdg_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        # Callback returns invalid URL (wrong scheme)
        mock_wait_callback.return_value = "https://evil.com/steal"

        frontend = MagicMock()
        frontend.prompt_url.return_value = ""

        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           frontend=frontend, session_info={"title": "T"})
        assert exit_code == 1

    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.os.close")
    def test_popen_failure_cleans_fds(self, mock_close, mock_openpty, mock_popen, xdg_runtime):
        mock_openpty.return_value = (10, 11)
        mock_popen.side_effect = OSError("fork failed")

        with pytest.raises(OSError):
            launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                   session_info={"title": "T"})
        # Both FDs should be closed
        assert mock_close.call_count >= 2

    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_no_auth_prompt_just_runs(self, mock_unlink, mock_close, mock_read,
                                       mock_select, mock_openpty, mock_popen, xdg_runtime):
        """Process exits without auth prompt (e.g., connection refused)."""
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 42
        # First poll returns None (loop enters), second returns exit code
        proc.poll.side_effect = [None, 131, 131, 131]
        proc.returncode = 131
        mock_popen.return_value = proc
        mock_select.return_value = ([], [], [])

        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           session_info={"title": "T"})
        assert exit_code == 131

    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_keyboard_interrupt_terminates(self, mock_unlink, mock_close, mock_read,
                                            mock_select, mock_openpty, mock_popen, xdg_runtime):
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 42
        proc.poll.side_effect = KeyboardInterrupt
        proc.wait.return_value = 143
        proc.terminate.return_value = None
        mock_popen.return_value = proc

        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           session_info={"title": "T"})
        assert exit_code == 143
        proc.terminate.assert_called_once()

    @patch("avd_client.launcher.subprocess.Popen")
    @patch("avd_client.launcher.pty.openpty")
    @patch("avd_client.launcher.select.select")
    @patch("avd_client.launcher.os.read")
    @patch("avd_client.launcher.os.close")
    @patch("avd_client.launcher.os.unlink")
    def test_keyboard_interrupt_sigkill_fallback(self, mock_unlink, mock_close, mock_read,
                                                  mock_select, mock_openpty, mock_popen,
                                                  xdg_runtime):
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 42
        proc.poll.side_effect = KeyboardInterrupt
        proc.terminate.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=10), 137]
        proc.kill.return_value = None
        mock_popen.return_value = proc

        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           session_info={"title": "T"})
        assert exit_code == 137
        proc.kill.assert_called_once()

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
    def test_browser_open_failure_notifies(self, mock_unlink, mock_close, mock_write,
                                            mock_read, mock_select, mock_openpty,
                                            mock_popen, mock_xdg_run, mock_browser,
                                            mock_wait_callback, xdg_runtime):
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        proc.terminate.return_value = None
        mock_popen.return_value = proc

        auth_output = (
            b"Browse to: https://login.microsoftonline.com/x\n"
            b"Paste redirect URL here:\n"
        )
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]
        mock_xdg_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_wait_callback.return_value = ""

        frontend = MagicMock()
        frontend.prompt_url.return_value = ""

        launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
               frontend=frontend, session_info={"title": "T"})
        # Should have notified about browser failure
        assert frontend.notify.call_count >= 1

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
    def test_no_frontend_uses_print(self, mock_unlink, mock_close, mock_write,
                                     mock_read, mock_select, mock_openpty,
                                     mock_popen, mock_xdg_run, mock_browser,
                                     mock_wait_callback, xdg_runtime, capsys):
        mock_openpty.return_value = (10, 11)
        proc = MagicMock()
        proc.pid = 99
        proc.poll.side_effect = [None, None, None, 0]
        proc.returncode = 0
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        auth_output = (
            b"Browse to: https://login.microsoftonline.com/x\n"
            b"Paste redirect URL here:\n"
        )
        mock_select.return_value = ([10], [], [])
        mock_read.side_effect = [auth_output, OSError()]
        mock_xdg_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_wait_callback.return_value = "ms-appx-web://microsoft.aad.brokerplugin/test?code=x"

        exit_code = launch("/usr/local/bin/xfreerdp", ["/usr/local/bin/xfreerdp"],
                           frontend=None, session_info={"title": "T"})
        assert exit_code == 0
        output = capsys.readouterr().out
        assert len(output) > 0  # Something was printed
