"""Tests for avd_client.auth — broker first, browser PKCE fallback."""

import base64
import io
import json
import urllib.error
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from avd_client.auth import (
    AuthError,
    AuthResult,
    _exchange_code,
    _id_token_username,
    _notify,
    _pkce_auth,
    _prompt,
    get_token,
)
from avd_client.broker import BrokerError
from avd_client.config import PKCE_SCOPE
from avd_client.security import SecurityError, validate_pkce_redirect


def _jwt(claims):
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def _token_response(**overrides):
    data = {
        "access_token": "eyJ.test.token",
        "id_token": _jwt({"preferred_username": "user@example.com"}),
        "refresh_token": "refresh-token",
    }
    data.update(overrides)
    return data


def _frontend_for_state(mock_open, code="abc"):
    frontend = MagicMock()

    def prompt(instructions):
        authorize_url = mock_open.call_args[0][0]
        state = parse_qs(urlparse(authorize_url).query)["state"][0]
        return (
            "https://login.microsoftonline.com/common/oauth2/nativeclient"
            f"?code={code}&state={state}"
        )

    frontend.prompt_url.side_effect = prompt
    return frontend


class TestBrokerFirst:
    @patch("avd_client.auth.BrokerClient")
    def test_broker_success(self, mock_cls):
        broker = MagicMock()
        broker.get_accounts.return_value = [{"username": "user@example.com"}]
        broker.acquire_token.return_value = "eyJ.test.token"
        mock_cls.return_value = broker

        result = get_token()

        assert result == AuthResult("eyJ.test.token", "user@example.com", "broker")
        broker.connect.assert_called_once()

    @patch("avd_client.auth._pkce_auth")
    @patch("avd_client.auth.BrokerClient")
    def test_broker_connect_error_falls_back(self, mock_cls, mock_pkce):
        mock_cls.return_value.connect.side_effect = BrokerError("no broker")
        mock_pkce.return_value = AuthResult("eyJ.test.token", "user@example.com", "pkce")
        frontend = MagicMock()

        result = get_token(frontend)

        assert result.source == "pkce"
        mock_pkce.assert_called_once_with(frontend)

    @patch("avd_client.auth._pkce_auth")
    @patch("avd_client.auth.BrokerClient")
    def test_broker_invalid_account_falls_back(self, mock_cls, mock_pkce):
        broker = MagicMock()
        broker.get_accounts.return_value = [{"username": ""}]
        mock_cls.return_value = broker
        mock_pkce.return_value = AuthResult("eyJ.test.token", "user@example.com", "pkce")

        result = get_token()

        assert result.source == "pkce"
        mock_pkce.assert_called_once()


class TestPkceFallback:
    @patch("avd_client.auth._exchange_code")
    @patch("avd_client.auth.webbrowser.open", return_value=True)
    @patch("avd_client.auth.BrokerClient")
    def test_broker_failure_then_pkce_success(self, mock_cls, mock_open, mock_exchange):
        mock_cls.return_value.connect.side_effect = BrokerError("no broker")
        mock_exchange.return_value = _token_response()
        frontend = _frontend_for_state(mock_open)

        result = get_token(frontend)

        assert result == AuthResult(
            "eyJ.test.token", "user@example.com", "pkce", "refresh-token"
        )
        mock_exchange.assert_called_once()
        code, verifier, scope = mock_exchange.call_args[0]
        assert code == "abc"
        assert verifier
        assert scope == PKCE_SCOPE
        assert "offline_access" in scope
        authorize_url = mock_open.call_args[0][0]
        assert "code_challenge_method=S256" in authorize_url
        frontend.prompt_url.assert_called_once()

    @patch("avd_client.auth.webbrowser.open", return_value=False)
    @patch("avd_client.auth.BrokerClient")
    def test_browser_open_failure_prints_url(self, mock_cls, mock_open):
        mock_cls.return_value.connect.side_effect = BrokerError("no broker")
        frontend = MagicMock()
        frontend.prompt_url.return_value = ""

        with pytest.raises(AuthError, match="Empty redirect"):
            get_token(frontend)

        messages = [call.args[0] for call in frontend.notify.call_args_list]
        assert any("https://login.microsoftonline.com" in message for message in messages)

    @patch("avd_client.auth._exchange_code", side_effect=AuthError("Token exchange failed"))
    @patch("avd_client.auth.webbrowser.open", return_value=True)
    @patch("avd_client.auth.BrokerClient")
    def test_exchange_error_propagates(self, mock_cls, mock_open, mock_exchange):
        mock_cls.return_value.connect.side_effect = BrokerError("no broker")
        frontend = _frontend_for_state(mock_open)

        with pytest.raises(AuthError, match="Token exchange failed"):
            get_token(frontend)

    @patch("avd_client.auth._exchange_code")
    @patch("avd_client.auth.webbrowser.open", return_value=True)
    @patch("avd_client.auth.BrokerClient")
    def test_missing_access_token(self, mock_cls, mock_open, mock_exchange):
        mock_cls.return_value.connect.side_effect = BrokerError("no broker")
        mock_exchange.return_value = {"id_token": _jwt({"preferred_username": "user@example.com"})}
        frontend = _frontend_for_state(mock_open)

        with pytest.raises(AuthError, match="Empty token"):
            get_token(frontend)

    @patch("avd_client.auth._exchange_code")
    @patch("avd_client.auth.webbrowser.open", return_value=True)
    @patch("avd_client.auth.BrokerClient")
    def test_missing_id_token(self, mock_cls, mock_open, mock_exchange):
        mock_cls.return_value.connect.side_effect = BrokerError("no broker")
        mock_exchange.return_value = {"access_token": "eyJ.test.token"}
        frontend = _frontend_for_state(mock_open)

        with pytest.raises(AuthError, match="no usable ID token"):
            get_token(frontend)

    @patch("avd_client.auth.webbrowser.open", return_value=True)
    @patch("avd_client.auth.BrokerClient")
    def test_state_mismatch(self, mock_cls, mock_open):
        mock_cls.return_value.connect.side_effect = BrokerError("no broker")
        frontend = MagicMock()
        frontend.prompt_url.return_value = (
            "https://login.microsoftonline.com/common/oauth2/nativeclient"
            "?code=abc&state=wrong"
        )

        with pytest.raises(AuthError, match="state mismatch"):
            get_token(frontend)

    @patch("avd_client.auth.webbrowser.open", return_value=True)
    @patch("avd_client.auth.BrokerClient")
    def test_invalid_redirect(self, mock_cls, mock_open):
        mock_cls.return_value.connect.side_effect = BrokerError("no broker")
        frontend = MagicMock()
        frontend.prompt_url.return_value = "https://evil.example/callback?code=abc&state=x"

        with pytest.raises(AuthError, match="not a Microsoft login URL"):
            get_token(frontend)

    @patch("avd_client.auth._exchange_code")
    @patch("avd_client.auth.webbrowser.open", return_value=True)
    def test_prompt_without_frontend_and_eof(self, mock_open, mock_exchange, capsys):
        mock_exchange.return_value = _token_response()

        def fake_input(_prompt):
            authorize_url = mock_open.call_args[0][0]
            state = parse_qs(urlparse(authorize_url).query)["state"][0]
            return (
                "https://login.microsoftonline.com/common/oauth2/nativeclient"
                f"?code=abc&state={state}"
            )

        with patch("builtins.input", side_effect=fake_input):
            result = _pkce_auth(None)

        assert result.source == "pkce"
        assert "Opening browser" in capsys.readouterr().out

    def test_prompt_eof_returns_empty(self, capsys):
        with patch("builtins.input", side_effect=EOFError):
            assert _prompt(None, "instruction") == ""

    def test_notify_without_frontend(self, capsys):
        _notify(None, "message")
        assert "message" in capsys.readouterr().out


class TestIdToken:
    def test_preferred_username(self):
        assert _id_token_username(_jwt({"preferred_username": "user@example.com"})) == (
            "user@example.com"
        )

    def test_upn_fallback(self):
        assert _id_token_username(_jwt({"upn": "user@example.com"})) == "user@example.com"

    def test_no_username(self):
        with pytest.raises(AuthError, match="no valid username"):
            _id_token_username(_jwt({}))

    def test_wrong_part_count(self):
        with pytest.raises(AuthError, match="no usable ID token"):
            _id_token_username("header.payload")

    def test_invalid_payload(self):
        with pytest.raises(AuthError, match="Could not parse ID token"):
            _id_token_username("header.!!!!.sig")


class TestExchangeCode:
    def _fake_response(self, data):
        class FakeResponse:
            def read(self, _size):
                return data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return FakeResponse()

    def test_success(self):
        response = self._fake_response(json.dumps(_token_response()).encode())
        with patch("avd_client.auth.urllib.request.urlopen", return_value=response) as mock_open:
            payload = _exchange_code("abc", "verifier", PKCE_SCOPE)

        assert payload["access_token"] == "eyJ.test.token"
        request = mock_open.call_args[0][0]
        body = request.data.decode()
        assert "grant_type=authorization_code" in body
        assert "code=abc" in body
        assert "code_verifier=verifier" in body

    def test_http_error(self):
        error = urllib.error.HTTPError(
            "https://login.microsoftonline.com/token",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"error":"invalid_grant"}'),
        )
        with patch("avd_client.auth.urllib.request.urlopen", side_effect=error):
            with pytest.raises(AuthError, match="HTTP 400 invalid_grant"):
                _exchange_code("abc", "verifier", PKCE_SCOPE)

    def test_http_error_without_json_body(self):
        error = urllib.error.HTTPError(
            "https://login.microsoftonline.com/token",
            400,
            "Bad Request",
            {},
            io.BytesIO(b"not json"),
        )
        with patch("avd_client.auth.urllib.request.urlopen", side_effect=error):
            with pytest.raises(AuthError, match="HTTP 400"):
                _exchange_code("abc", "verifier", PKCE_SCOPE)

    def test_url_error(self):
        with patch(
            "avd_client.auth.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            with pytest.raises(AuthError, match="Token exchange failed"):
                _exchange_code("abc", "verifier", PKCE_SCOPE)

    def test_invalid_json(self):
        response = self._fake_response(b"not json")
        with patch("avd_client.auth.urllib.request.urlopen", return_value=response):
            with pytest.raises(AuthError, match="Token exchange failed"):
                _exchange_code("abc", "verifier", PKCE_SCOPE)

    def test_response_too_large(self):
        response = self._fake_response(b"12345")
        with patch("avd_client.auth.PKCE_MAX_RESPONSE_BYTES", 4):
            with patch("avd_client.auth.urllib.request.urlopen", return_value=response):
                with pytest.raises(AuthError, match="exceeds size limit"):
                    _exchange_code("abc", "verifier", PKCE_SCOPE)


class TestValidatePkceRedirect:
    _VALID = (
        "https://login.microsoftonline.com/common/oauth2/nativeclient"
        "?code=abc&state=xyz"
    )

    def test_valid(self):
        assert validate_pkce_redirect(self._VALID) == ("abc", "xyz")

    def test_empty(self):
        with pytest.raises(SecurityError, match="Empty redirect"):
            validate_pkce_redirect("")

    def test_control_characters(self):
        with pytest.raises(SecurityError, match="control characters"):
            validate_pkce_redirect(self._VALID + "\x00")

    def test_too_long(self):
        with pytest.raises(SecurityError, match="too long"):
            validate_pkce_redirect("https://login.microsoftonline.com/" + "a" * 8192)

    def test_wrong_scheme(self):
        with pytest.raises(SecurityError, match="not a Microsoft login URL"):
            validate_pkce_redirect("http://login.microsoftonline.com/common/oauth2/nativeclient?code=a&state=b")

    def test_wrong_host(self):
        with pytest.raises(SecurityError, match="not a Microsoft login URL"):
            validate_pkce_redirect("https://evil.example/common/oauth2/nativeclient?code=a&state=b")

    def test_wrong_path(self):
        with pytest.raises(SecurityError, match="unexpected path"):
            validate_pkce_redirect("https://login.microsoftonline.com/evil?code=a&state=b")

    def test_missing_code(self):
        with pytest.raises(SecurityError, match="missing code or state"):
            validate_pkce_redirect(
                "https://login.microsoftonline.com/common/oauth2/nativeclient?state=b"
            )

    def test_state_too_long(self):
        state = "x" * 257
        with pytest.raises(SecurityError, match="too long"):
            validate_pkce_redirect(
                "https://login.microsoftonline.com/common/oauth2/nativeclient"
                f"?code=abc&state={state}"
            )
