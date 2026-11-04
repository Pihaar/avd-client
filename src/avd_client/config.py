"""Configuration constants for avd-client."""

import os
import re

# Microsoft Identity Broker (D-Bus)
BROKER_BUS_NAME = "com.microsoft.identity.broker1"
BROKER_OBJECT_PATH = "/com/microsoft/identity/broker1"
BROKER_INTERFACE = "com.microsoft.identity.Broker1"
BROKER_TIMEOUT = 30  # seconds (first activation can take 25s)
BROKER_INTERACTIVE_TIMEOUT = 300  # seconds (SSO dialog needs user interaction)
BROKER_PRT_TIMEOUT = 10  # seconds (fall back to the browser if the cookie is slow)

# OAuth / Token
RDP_CLIENT_ID = "a85cf173-4192-42f8-81fa-777a763e6e2c"
RDP_REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"
AVD_SCOPE = "https://www.wvd.microsoft.com/.default"

# PRT SSO cookie requests use the Edge browser client identity
EDGE_BROWSER_CLIENT_ID = "d7b530a4-7680-4c23-a8bf-c52c121d2e87"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

# Broker-free browser login (OAuth2 authorization code with PKCE)
PKCE_AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
PKCE_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
PKCE_SCOPE = f"{AVD_SCOPE} openid profile email offline_access"
PKCE_MAX_RESPONSE_BYTES = 1024 * 1024
PKCE_TIMEOUT = 30

# Feed Discovery
FEED_URL = "https://rdweb.wvd.microsoft.com/api/arm/feeddiscovery"
FEED_USER_AGENT = "Microsoft.RDInfra.RDClient/10.0.0"
FEED_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB

# Feed XML namespaces
NS_DISCOVERY = "http://schemas.microsoft.com/ts/2014/03/tswfdiscovery"
NS_WEBFEED = "http://schemas.microsoft.com/ts/2007/05/tswf"

# FreeRDP
FREERDP_BIN = os.environ.get("FREERDP_BIN", "")
# The private avd-freerdp build carries the SSO MIB support on EL systems.
FREERDP_SEARCH_NAMES = ("xfreerdp-avd", "xfreerdp3", "xfreerdp")
FREERDP_WAYLAND_NAMES = (
    "wlfreerdp-avd",
    "wlfreerdp3",
    "wlfreerdp",
    "xfreerdp-avd",
    "xfreerdp3",
    "xfreerdp",
)
FREERDP_MIN_VERSION = (3, 5, 0)
FREERDP_ALLOWED_PATHS = (
    "/usr/bin/",
    "/usr/local/bin/",
    "/usr/lib/avd-freerdp/bin/",
    "/usr/lib/freerdp3/",
    "/usr/lib64/",
)
FREERDP_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")

# Hostname allowlist for session hosts and gateways
HOSTNAME_PATTERN = re.compile(
    r"^([a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)"
    r"(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)*"
    r"\.(wvd|cloudpc)\.microsoft\.com$"
)
MAX_HOSTNAME_LENGTH = 253
