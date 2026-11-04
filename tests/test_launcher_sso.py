"""Tests for the SSO MIB launch path."""

import signal
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import avd_client.launcher as launcher
from avd_client.launcher import _has_sso_mib, _launch_direct, launch


@pytest.fixture(autouse=True)
def _clear_sso_cache():
    launcher._sso_mib_cache.clear()


def _completed(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


class TestHasSsoMib:
    def test_reports_support(self):
        with patch(
            "avd_client.launcher.subprocess.run",
            return_value=_completed("WITH_SSO_MIB=ON"),
        ):
            assert _has_sso_mib("test-sso-on") is True

    def test_reports_missing_support(self):
        with patch(
            "avd_client.launcher.subprocess.run", return_value=_completed("WITH_SSO_MIB=OFF")
        ):
            assert _has_sso_mib("test-sso-off") is False

    def test_probe_error_is_false(self):
        with patch("avd_client.launcher.subprocess.run", side_effect=OSError("missing")):
            assert _has_sso_mib("test-sso-error") is False

    def test_result_is_cached(self):
        with patch(
            "avd_client.launcher.subprocess.run", return_value=_completed("WITH_SSO_MIB=ON")
        ) as run:
            assert _has_sso_mib("test-sso-cache") is True
            assert _has_sso_mib("test-sso-cache") is True
        run.assert_called_once()


class TestLaunchDirect:
    def test_returns_exit_code_and_cleans_rdp(self, tmp_path):
        rdp = tmp_path / "session.rdp"
        rdp.write_text("")
        proc = MagicMock()
        proc.wait.return_value = 0
        with patch("avd_client.launcher.subprocess.Popen", return_value=proc) as popen:
            with patch("avd_client.launcher.signal.signal"):
                assert _launch_direct(["/bin/true"], {}, str(rdp)) == 0
        popen.assert_called_once_with(["/bin/true"], env={})
        assert not rdp.exists()

    def test_missing_rdp_file_is_ignored(self):
        proc = MagicMock()
        proc.wait.return_value = 0
        with patch("avd_client.launcher.subprocess.Popen", return_value=proc):
            with patch("avd_client.launcher.signal.signal"):
                assert _launch_direct(["bin"], {}, "/nonexistent/session.rdp") == 0

    def test_keyboard_interrupt_terminates(self):
        proc = MagicMock()
        proc.wait.side_effect = [KeyboardInterrupt, 0]
        with patch("avd_client.launcher.subprocess.Popen", return_value=proc):
            with patch("avd_client.launcher.signal.signal"):
                assert _launch_direct(["bin"], {}) == 0
        proc.terminate.assert_called_once()

    def test_timeout_kills_process(self):
        proc = MagicMock()
        proc.wait.side_effect = [
            KeyboardInterrupt,
            subprocess.TimeoutExpired("bin", 10),
            0,
        ]
        with patch("avd_client.launcher.subprocess.Popen", return_value=proc):
            with patch("avd_client.launcher.signal.signal"):
                assert _launch_direct(["bin"], {}) == 0
        proc.kill.assert_called_once()

    def test_launch_dispatches_direct_path(self):
        with patch("avd_client.launcher._has_sso_mib", return_value=True):
            with patch("avd_client.launcher._launch_direct", return_value=7) as direct:
                assert launch("bin", ["bin"], rdp_path="/tmp/session.rdp") == 7
        assert direct.call_args.args[0] == ["bin"]
        assert direct.call_args.args[2] == "/tmp/session.rdp"

    def test_signal_forwarding(self):
        proc = MagicMock()
        proc.wait.return_value = 0
        proc.poll.return_value = None
        calls = []
        with patch("avd_client.launcher.subprocess.Popen", return_value=proc):
            with patch(
                "avd_client.launcher.signal.signal",
                side_effect=lambda signum, handler: calls.append((signum, handler)),
            ):
                assert _launch_direct(["bin"], {}) == 0
        forward = next(
            handler
            for signum, handler in calls
            if signum == signal.SIGTERM and handler.__name__ == "forward_signal"
        )
        forward(signal.SIGTERM, None)
        proc.send_signal.assert_called_once_with(signal.SIGTERM)

        proc.poll.return_value = 0
        proc.send_signal.reset_mock()
        forward(signal.SIGTERM, None)
        proc.send_signal.assert_not_called()
