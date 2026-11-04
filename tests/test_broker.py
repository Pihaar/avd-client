"""Tests for avd_client.broker — D-Bus broker client with mocked dbus."""

import json
from unittest.mock import MagicMock

import pytest

from avd_client.broker import BrokerClient, BrokerError

SAMPLE_ACCOUNTS = json.dumps({
    "accounts": [
        {
            "username": "test@example.com", "homeAccountId": "abc-123",
            "environment": "login.microsoftonline.com"
        }
    ],
    "telemetry": {}
})

SAMPLE_TOKEN = json.dumps({
    "brokerTokenResponse": {
        "accessToken": "eyJhbGciOiJkaXIi..ivdata.ciphertext.tag",
        "expiresOn": 1780050000000,
        "grantedScopes": "https://www.wvd.microsoft.com/.default",
    },
    "telemetry": {}
})

SAMPLE_ERROR = json.dumps({
    "brokerTokenResponse": {
        "error": {"context": "invalid_request", "errorCode": -1, "status": 9}
    }
})

SAMPLE_VERSION = json.dumps({"linuxBrokerVersion": "3.0.2", "telemetry": {}})


class TestBrokerClient:
    def _make_client(self):
        client = BrokerClient()
        client._bus = MagicMock()
        client._iface = MagicMock()
        return client

    def test_connect_success(self):
        client = BrokerClient()
        client.connect()
        # Should not raise (dbus is mocked in conftest)

    def test_get_version(self):
        client = self._make_client()
        client._iface.getLinuxBrokerVersion.return_value = SAMPLE_VERSION
        assert client.get_version() == "3.0.2"

    def test_get_accounts_success(self):
        client = self._make_client()
        client._iface.getAccounts.return_value = SAMPLE_ACCOUNTS
        accounts = client.get_accounts()
        assert len(accounts) == 1
        assert accounts[0]["username"] == "test@example.com"

    def test_get_accounts_empty_raises(self):
        client = self._make_client()
        client._iface.getAccounts.return_value = json.dumps({"accounts": []})
        with pytest.raises(BrokerError, match="No accounts"):
            client.get_accounts()

    def test_acquire_token_success(self):
        client = self._make_client()
        client._iface.acquireTokenSilently.return_value = SAMPLE_TOKEN
        token = client.acquire_token({"username": "test@example.com"})
        assert token.startswith("eyJ")

    def test_acquire_token_error_raises(self):
        client = self._make_client()
        client._iface.acquireTokenSilently.return_value = SAMPLE_ERROR
        with pytest.raises(BrokerError, match="Token acquisition failed"):
            client.acquire_token({"username": "test@example.com"})

    def test_acquire_token_expired_falls_back_to_interactive(self):
        client = self._make_client()
        expired = json.dumps({
            "brokerTokenResponse": {
                "error": {"context": "invalid_grant suberror: 'token_expired'"}
            }
        })
        client._iface.acquireTokenSilently.return_value = expired
        client._iface.acquireTokenInteractively.return_value = SAMPLE_TOKEN

        token = client.acquire_token({"username": "test@example.com"})

        assert token.startswith("eyJ")
        client._iface.acquireTokenInteractively.assert_called_once()
        request = json.loads(client._iface.acquireTokenInteractively.call_args[0][2])
        assert request["authParameters"]["authorizationType"] == 0

    def test_acquire_token_interactive_error_raises(self):
        client = self._make_client()
        expired = json.dumps({
            "brokerTokenResponse": {
                "error": {"context": "invalid_grant suberror: 'token_expired'"}
            }
        })
        client._iface.acquireTokenSilently.return_value = expired
        client._iface.acquireTokenInteractively.return_value = SAMPLE_ERROR

        with pytest.raises(BrokerError, match="Interactive token acquisition failed"):
            client.acquire_token({"username": "test@example.com"})

    def test_acquire_token_other_error_does_not_retry_interactive(self):
        client = self._make_client()
        client._iface.acquireTokenSilently.return_value = SAMPLE_ERROR

        with pytest.raises(BrokerError, match="Token acquisition failed"):
            client.acquire_token({"username": "test@example.com"})

        client._iface.acquireTokenInteractively.assert_not_called()

    def test_acquire_token_empty_raises(self):
        client = self._make_client()
        client._iface.acquireTokenSilently.return_value = json.dumps({
            "brokerTokenResponse": {"accessToken": ""}
        })
        with pytest.raises(BrokerError, match="empty access token"):
            client.acquire_token({"username": "test@example.com"})

    def test_acquire_prt_sso_cookie_v2(self):
        client = self._make_client()
        client._iface.acquirePrtSsoCookie.return_value = json.dumps({
            "cookieName": "x-ms-RefreshTokenCredential",
            "cookieContent": "cookie-value",
        })
        cookie = client.acquire_prt_sso_cookie(
            {"username": "user@example.com"},
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1",
        )
        assert cookie == {
            "cookieName": "x-ms-RefreshTokenCredential",
            "cookieContent": "cookie-value",
        }
        request = json.loads(client._iface.acquirePrtSsoCookie.call_args[0][2])
        assert request["authParameters"]["authorizationType"] == 8
        assert request["authParameters"]["clientId"] == "ecd6b820-32c2-49b6-98a6-444530e5a77a"
        assert request["ssoUrl"].startswith("https://login.microsoftonline.com/")

    def test_acquire_prt_sso_cookie_v3(self):
        client = self._make_client()
        client._iface.acquirePrtSsoCookie.return_value = json.dumps({
            "cookieItems": [{
                "cookieName": "x-ms-RefreshTokenCredential",
                "cookieContent": "v3-value",
            }]
        })
        cookie = client.acquire_prt_sso_cookie(
            {"username": "user@example.com"},
            "https://login.microsoftonline.com/x",
        )
        assert cookie["cookieContent"] == "v3-value"

    def test_acquire_prt_sso_cookie_error(self):
        client = self._make_client()
        client._iface.acquirePrtSsoCookie.return_value = json.dumps({
            "error": {"context": "boom"}
        })
        with pytest.raises(BrokerError, match="PRT cookie acquisition failed"):
            client.acquire_prt_sso_cookie(
                {"username": "user@example.com"}, "https://login.microsoftonline.com/x"
            )

    def test_acquire_prt_sso_cookie_empty(self):
        client = self._make_client()
        client._iface.acquirePrtSsoCookie.return_value = json.dumps({})
        with pytest.raises(BrokerError, match="empty PRT cookie"):
            client.acquire_prt_sso_cookie(
                {"username": "user@example.com"}, "https://login.microsoftonline.com/x"
            )

    def test_acquire_prt_sso_cookie_empty_items(self):
        client = self._make_client()
        client._iface.acquirePrtSsoCookie.return_value = json.dumps({"cookieItems": []})
        with pytest.raises(BrokerError, match="empty PRT cookie"):
            client.acquire_prt_sso_cookie(
                {"username": "user@example.com"}, "https://login.microsoftonline.com/x"
            )

    def test_dbus_exception_raises_broker_error(self):
        import dbus.exceptions
        client = self._make_client()
        exc = dbus.exceptions.DBusException("service not found")
        exc._dbus_message = "org.freedesktop.DBus.Error.ServiceUnknown"
        client._iface.getAccounts.side_effect = exc
        with pytest.raises(BrokerError, match="D-Bus call"):
            client.get_accounts()

    def test_not_connected_raises(self):
        client = BrokerClient()
        # _iface is None without connect()
        client._iface = None
        with pytest.raises(BrokerError, match="Not connected"):
            client.get_accounts()
