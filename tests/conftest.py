"""Shared test fixtures for avd-client."""

import sys
import types
from unittest.mock import MagicMock

import pytest

# --- Fake dbus module (must be set before any avd_client.broker import) ---
fake_dbus = types.ModuleType("dbus")
fake_dbus_exceptions = types.ModuleType("dbus.exceptions")


class FakeDBusException(Exception):
    def get_dbus_message(self):
        return getattr(self, "_dbus_message", "mock dbus error")


def _fake_interface(*args, **kwargs):
    return MagicMock()


fake_dbus_exceptions.DBusException = FakeDBusException
fake_dbus.exceptions = fake_dbus_exceptions
fake_dbus.SessionBus = MagicMock
# Calling the MagicMock class directly would treat the first argument as its spec.
fake_dbus.Interface = _fake_interface

sys.modules.setdefault("dbus", fake_dbus)
sys.modules.setdefault("dbus.exceptions", fake_dbus_exceptions)


@pytest.fixture
def xdg_runtime(tmp_path, monkeypatch):
    """Provide a temporary XDG_RUNTIME_DIR."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def xdg_config(tmp_path, monkeypatch):
    """Provide a temporary XDG_CONFIG_HOME."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    return config_dir


@pytest.fixture
def mock_urlopen(monkeypatch):
    """Mock urllib.request.urlopen with controllable responses."""

    class FakeResponse:
        def __init__(self, data, status=200, headers=None):
            self._data = data if isinstance(data, bytes) else data.encode("utf-8")
            self.status = status
            self.headers = headers or {}

        def read(self, n=-1):
            if n == -1:
                return self._data
            return self._data[:n]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    return FakeResponse
