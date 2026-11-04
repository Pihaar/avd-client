"""Security validation functions for avd-client."""

import logging
import re
import sys
from urllib.parse import parse_qs, urlparse

from .config import HOSTNAME_PATTERN, MAX_HOSTNAME_LENGTH

log = logging.getLogger(__name__)

# Token shape: 3-part JWS or 5-part JWE, base64url with optional padding.
# JWE with alg=dir has an EMPTY encrypted-key segment, so we allow zero-length parts.
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-=]*(\.[A-Za-z0-9_\-=]*){2,4}$")
_MAX_TOKEN_LENGTH = 32768

# Redaction pattern: matches both 3-part JWS and 5-part JWE tokens starting with eyJ
_JWT_REDACTION_PATTERN = re.compile(
    r"eyJ[A-Za-z0-9_\-=]*(?:\.[A-Za-z0-9_\-=]*){2,4}"
)

_UPN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@\-]{0,253}$")

_CALLBACK_URL_PREFIX = "ms-appx-web://microsoft.aad.brokerplugin/"
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


class SecurityError(Exception):
    pass


def validate_token_shape(token: str) -> str:
    token = token.strip()
    if not token:
        raise SecurityError("Empty token")
    if len(token) > _MAX_TOKEN_LENGTH:
        raise SecurityError("Token exceeds maximum length")
    if not _TOKEN_PATTERN.fullmatch(token):
        raise SecurityError("Token has invalid shape")
    return token


def validate_hostname(host: str) -> str:
    host = host.lower().rstrip(".")
    if not host:
        raise SecurityError("Empty hostname")
    if len(host) > MAX_HOSTNAME_LENGTH:
        raise SecurityError("Hostname exceeds maximum length")
    if host.startswith("xn--") or ".xn--" in host:
        raise SecurityError("IDN/Punycode hostnames not allowed")
    if not HOSTNAME_PATTERN.fullmatch(host):
        raise SecurityError(f"Hostname not in allowlist: {host[:50]}")
    return host


def validate_upn(username: str) -> str:
    if not username or not _UPN_PATTERN.fullmatch(username):
        raise SecurityError(f"Invalid UPN format: {username[:30] if username else '(empty)'}")
    return username


def validate_redirect_url(url: str) -> str:
    if not url:
        raise SecurityError("Empty redirect URL")
    if not url.lower().startswith(_CALLBACK_URL_PREFIX):
        raise SecurityError("Redirect URL must start with ms-appx-web://Microsoft.AAD.BrokerPlugin/")
    if _CONTROL_CHAR_PATTERN.search(url):
        raise SecurityError("Redirect URL contains control characters")
    if len(url) > 8192:
        raise SecurityError("Redirect URL too long")
    return url


def validate_pkce_redirect(url: str) -> tuple:
    """Return (code, state) from the nativeclient redirect; never echo either value."""
    if not url:
        raise SecurityError("Empty redirect URL")
    if _CONTROL_CHAR_PATTERN.search(url):
        raise SecurityError("Redirect URL contains control characters")
    if len(url) > 8192:
        raise SecurityError("Redirect URL too long")
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "login.microsoftonline.com":
        raise SecurityError("Redirect URL is not a Microsoft login URL")
    if not parsed.path.startswith("/common/oauth2/nativeclient"):
        raise SecurityError("Redirect URL has an unexpected path")
    query = parse_qs(parsed.query)
    code = query.get("code", [""])[0]
    state = query.get("state", [""])[0]
    if not code or not state:
        raise SecurityError("Redirect URL is missing code or state")
    if len(code) > 8192 or len(state) > 256:
        raise SecurityError("Redirect parameters are too long")
    return code, state


def validate_feed_url(url: str) -> str:
    """Validate that a feed-returned URL points to an allowed Microsoft host."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SecurityError(f"Feed URL must use HTTPS: {url[:50]}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise SecurityError("Feed URL has no hostname")
    allowed_suffixes = (".wvd.microsoft.com", ".cloudpc.microsoft.com")
    if not any(host == s.lstrip(".") or host.endswith(s) for s in allowed_suffixes):
        raise SecurityError(f"Feed URL host not allowed: {host[:50]}")
    return url


class TokenRedactionFilter(logging.Filter):
    """Logging filter that redacts JWT/JWE tokens from log output."""

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _JWT_REDACTION_PATTERN.sub("[REDACTED]", record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _JWT_REDACTION_PATTERN.sub("[REDACTED]", v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _JWT_REDACTION_PATTERN.sub("[REDACTED]", a) if isinstance(a, str) else a
                    for a in record.args
                )
        return True


def install_token_redaction():
    filt = TokenRedactionFilter()
    root = logging.getLogger()
    root.addFilter(filt)
    if logging.lastResort:
        logging.lastResort.addFilter(filt)

    original_excepthook = sys.excepthook

    def redacting_excepthook(exc_type, exc_value, exc_tb):
        if exc_value and hasattr(exc_value, "args"):
            redacted_args = []
            for arg in exc_value.args:
                if isinstance(arg, str):
                    arg = _JWT_REDACTION_PATTERN.sub("[REDACTED]", arg)
                redacted_args.append(arg)
            try:
                exc_value.args = tuple(redacted_args)
            except (TypeError, AttributeError):
                pass
        original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = redacting_excepthook
