"""Authentication backends: identity broker first, browser PKCE fallback."""

import base64
import hashlib
import json
import logging
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass

from .broker import BrokerClient, BrokerError
from .config import (
    PKCE_AUTHORIZE_URL,
    PKCE_MAX_RESPONSE_BYTES,
    PKCE_SCOPE,
    PKCE_TIMEOUT,
    PKCE_TOKEN_URL,
    RDP_CLIENT_ID,
    RDP_REDIRECT_URI,
)
from .i18n import _
from .security import (
    SecurityError,
    validate_pkce_redirect,
    validate_token_shape,
    validate_upn,
)

log = logging.getLogger(__name__)


class AuthError(Exception):
    pass


@dataclass
class AuthResult:
    token: str
    username: str
    source: str
    refresh_token: str = ""


def _upn_hash(username: str) -> str:
    return hashlib.sha256(username.encode()).hexdigest()[:12]


def _create_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _broker_auth() -> AuthResult:
    broker = BrokerClient()
    broker.connect()
    log.info("Broker version: %s", broker.get_version())
    accounts = broker.get_accounts()
    account = accounts[0]
    username = validate_upn(account.get("username", ""))
    log.info("Account: %s", _upn_hash(username))
    token = validate_token_shape(broker.acquire_token(account))
    return AuthResult(token=token, username=username, source="broker")


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _notify(frontend, message: str) -> None:
    if frontend:
        frontend.notify(message)
    else:
        print(message)


def _prompt(frontend, instructions: str) -> str:
    if frontend:
        return frontend.prompt_url(instructions)
    print(instructions)
    try:
        return input("> ").strip()
    except EOFError:
        return ""


def _id_token_username(id_token: str) -> str:
    # The ID token comes directly from the TLS token endpoint; it is read
    # only for the FreeRDP username hint, not for authorization decisions.
    parts = id_token.split(".")
    if len(parts) != 3:
        raise AuthError("Token response has no usable ID token")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise AuthError("Could not parse ID token") from e
    username = claims.get("preferred_username") or claims.get("upn") or ""
    try:
        return validate_upn(username)
    except SecurityError as e:
        raise AuthError("ID token has no valid username") from e


def _exchange_code(code: str, verifier: str, scope: str) -> dict:
    data = urllib.parse.urlencode({
        "client_id": RDP_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": RDP_REDIRECT_URI,
        "code_verifier": verifier,
        "scope": scope,
    }).encode("utf-8")
    request = urllib.request.Request(
        PKCE_TOKEN_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "avd-client",
        },
        method="POST",
    )
    context = _create_ssl_context()
    try:
        with urllib.request.urlopen(request, timeout=PKCE_TIMEOUT, context=context) as response:
            raw = response.read(PKCE_MAX_RESPONSE_BYTES + 1)
            if len(raw) > PKCE_MAX_RESPONSE_BYTES:
                raise AuthError("Token response exceeds size limit")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read(PKCE_MAX_RESPONSE_BYTES).decode("utf-8"))
            detail = str(body.get("error", ""))[:200]
        except (OSError, ValueError, AttributeError):
            pass
        message = f"Token exchange failed: HTTP {e.code}"
        raise AuthError(f"{message} {detail}".strip()) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AuthError(f"Token exchange failed: {e}") from e


def _pkce_auth(frontend) -> AuthResult:
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": RDP_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": RDP_REDIRECT_URI,
        "scope": PKCE_SCOPE,
        "code_challenge": _code_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
    }
    authorize_url = f"{PKCE_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    _notify(frontend, _("Opening browser for Microsoft sign-in..."))
    if not webbrowser.open(authorize_url):
        log.warning("Could not open browser; open the URL manually")
        _notify(frontend, authorize_url)
    instructions = _(
        "After signing in, paste the full redirect URL "
        "(starts with https://login.microsoftonline.com/...):"
    )
    redirect_url = _prompt(frontend, instructions)
    try:
        code, returned_state = validate_pkce_redirect(redirect_url)
    except SecurityError as e:
        raise AuthError(str(e)) from e
    if not secrets.compare_digest(returned_state, state):
        raise AuthError("OAuth state mismatch")
    payload = _exchange_code(code, verifier, PKCE_SCOPE)
    try:
        token = validate_token_shape(payload.get("access_token", ""))
        username = _id_token_username(payload.get("id_token", ""))
    except SecurityError as e:
        raise AuthError(str(e)) from e
    return AuthResult(
        token=token,
        username=username,
        source="pkce",
        refresh_token=payload.get("refresh_token", ""),
    )


def get_token(frontend=None) -> AuthResult:
    try:
        return _broker_auth()
    except (BrokerError, SecurityError) as e:
        log.info("Broker authentication unavailable, using browser login: %s", e)
        return _pkce_auth(frontend)
