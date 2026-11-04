"""Tests for avd_client.launcher — binary resolution, version check, argv building."""

import os
import subprocess
from unittest.mock import patch

import pytest

from avd_client.launcher import (
    LauncherError,
    _build_exec_env,
    build_argv,
    check_version,
    resolve_binary,
)

SAMPLE_RDP = """\
gatewayusagemethod:i:1
gatewayhostname:s:afdfp-rdgateway.wvd.microsoft.com:443
full address:s:rdgateway.wvd.microsoft.com
loadbalanceinfo:s:mth://localhost/pool1/host1
enablerdsaadauth:i:1
dynamic resolution:i:1
"""

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

    def test_env_override(self, monkeypatch, tmp_path):
        binary = tmp_path / "xfreerdp3"
        binary.touch()
        monkeypatch.setattr("avd_client.launcher.FREERDP_BIN", str(binary))
        with patch("os.path.realpath", return_value="/usr/local/bin/xfreerdp3"):
            with patch("os.path.isfile", return_value=True):
                resolve_binary()


class TestCheckVersion:
    @patch("avd_client.launcher.subprocess.run")
    def test_parses_version(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="This is FreeRDP version 3.10.2 (build)\n", stderr=""
        )
        version = check_version("/usr/local/bin/xfreerdp")
        assert version == (3, 10, 2)

    @patch("avd_client.launcher.subprocess.run")
    def test_old_version_raises(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="This is FreeRDP version 2.11.7\n", stderr=""
        )
        with pytest.raises(LauncherError, match="too old"):
            check_version("/usr/local/bin/xfreerdp")

    @patch("avd_client.launcher.subprocess.run")
    def test_timeout_returns_zero(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=5)
        version = check_version("/usr/local/bin/xfreerdp")
        assert version == (0, 0, 0)

    @patch("avd_client.launcher.subprocess.run")
    def test_no_version_string_returns_zero(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="no version here", stderr=""
        )
        version = check_version("/usr/local/bin/xfreerdp")
        assert version == (0, 0, 0)


class TestBuildArgv:
    def test_basic_argv(self):
        cmd, rdp_path = build_argv(
            "/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "user@example.com"
        )
        try:
            assert cmd[0] == "/usr/local/bin/xfreerdp"
            assert cmd[1] == rdp_path
            assert any("gateway:type:arm,bearer:" in c for c in cmd)
            assert "/cert:tofu" in cmd
            assert "+clipboard" not in cmd
        finally:
            os.unlink(rdp_path)

    def test_clipboard_option(self):
        cmd, rdp_path = build_argv(
            "/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "user@example.com",
            clipboard=True
        )
        try:
            assert "+clipboard" in cmd
        finally:
            os.unlink(rdp_path)

    def test_multimon_option(self):
        cmd, rdp_path = build_argv(
            "/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "user@example.com",
            multimon=True
        )
        try:
            assert "/multimon" in cmd
        finally:
            os.unlink(rdp_path)

    def test_rdp_file_created_0600(self):
        _, rdp_path = build_argv(
            "/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "user@example.com"
        )
        try:
            mode = oct(os.stat(rdp_path).st_mode & 0o777)
            assert mode == "0o600"
        finally:
            os.unlink(rdp_path)

    def test_validates_gateway_hostname(self):
        bad_rdp = SAMPLE_RDP.replace("afdfp-rdgateway.wvd.microsoft.com", "evil.com")
        from avd_client.security import SecurityError
        with pytest.raises(SecurityError, match="not in allowlist"):
            build_argv("/usr/local/bin/xfreerdp", bad_rdp, DUMMY_TOKEN, "user@example.com")

    def test_validates_upn(self):
        from avd_client.security import SecurityError
        with pytest.raises(SecurityError, match="Invalid UPN"):
            build_argv("/usr/local/bin/xfreerdp", SAMPLE_RDP, DUMMY_TOKEN, "")


class TestBuildExecEnv:
    def test_path_is_fixed(self):
        env = _build_exec_env()
        assert env["PATH"] == "/usr/bin:/usr/local/bin:/bin"

    def test_filters_dangerous_vars(self, monkeypatch):
        monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
        monkeypatch.setenv("PYTHONPATH", "/tmp")
        env = _build_exec_env()
        assert "LD_PRELOAD" not in env
        assert "PYTHONPATH" not in env

    def test_keeps_display(self, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        env = _build_exec_env()
        assert env.get("DISPLAY") == ":0"

    def test_keeps_xdg_runtime(self, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        env = _build_exec_env()
        assert env.get("XDG_RUNTIME_DIR") == "/run/user/1000"
