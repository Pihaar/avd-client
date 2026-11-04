"""D-Bus client for microsoft-identity-broker."""

import json
import logging
import uuid

import dbus

from .config import (
    AVD_SCOPE,
    BROKER_BUS_NAME,
    BROKER_INTERACTIVE_TIMEOUT,
    BROKER_INTERFACE,
    BROKER_OBJECT_PATH,
    BROKER_PRT_TIMEOUT,
    BROKER_TIMEOUT,
    EDGE_BROWSER_CLIENT_ID,
    GRAPH_SCOPE,
    RDP_CLIENT_ID,
    RDP_REDIRECT_URI,
)

log = logging.getLogger(__name__)


class BrokerError(Exception):
    pass


class BrokerClient:
    def __init__(self):
        self._bus = None
        self._iface = None

    def connect(self):
        try:
            self._bus = dbus.SessionBus()
            obj = self._bus.get_object(BROKER_BUS_NAME, BROKER_OBJECT_PATH)
            self._iface = dbus.Interface(obj, BROKER_INTERFACE)
        except dbus.exceptions.DBusException as e:
            raise BrokerError(
                "Cannot connect to microsoft-identity-broker. "
                "Is the package installed? (zypper in microsoft-identity-broker / "
                "dnf install microsoft-identity-broker)"
            ) from e

    def get_version(self) -> str:
        result = self._call("getLinuxBrokerVersion", "{}")
        return result.get("linuxBrokerVersion", "unknown")

    def get_accounts(self, client_id: str = RDP_CLIENT_ID,
                     redirect_uri: str = RDP_REDIRECT_URI) -> list:
        request = json.dumps({
            "clientId": client_id,
            "redirectUri": redirect_uri,
            "environment": "login.microsoftonline.com",
        })
        result = self._call("getAccounts", request)
        accounts = result.get("accounts", [])
        if not accounts:
            raise BrokerError(
                "No accounts found in identity broker. "
                "Is this device enrolled in Intune? (Run intune-portal to enroll)"
            )
        return accounts

    def acquire_token(self, account: dict, scopes: list = None) -> str:
        if scopes is None:
            scopes = [AVD_SCOPE]
        auth_params = {
            "account": account,
            "additionalQueryParametersForAuthorization": {},
            "authority": "https://login.microsoftonline.com/common",
            "authorizationType": 1,
            "clientId": RDP_CLIENT_ID,
            "enrollmentId": "",
            "isTestMode": False,
            "popParams": None,
            "redirectUri": RDP_REDIRECT_URI,
            "requestOptions": [205, 202],
            "requestedScopes": scopes,
            "username": account.get("username", ""),
            "uxContextHandle": -1,
        }
        result = self._call("acquireTokenSilently", json.dumps({"authParameters": auth_params}))
        btr = result.get("brokerTokenResponse", {})
        if btr.get("error"):
            err = btr["error"]
            context = err.get("context", "unknown")[:200]
            if "token_expired" in context or "invalid_grant" in context:
                log.info("Silent token expired, trying interactive acquisition")
                auth_params["authorizationType"] = 0
                result = self._call(
                    "acquireTokenInteractively",
                    json.dumps({"authParameters": auth_params}),
                    timeout=BROKER_INTERACTIVE_TIMEOUT,
                )
                btr = result.get("brokerTokenResponse", {})
                if btr.get("error"):
                    err = btr["error"]
                    context = err.get("context", "unknown")[:200]
                    raise BrokerError(f"Interactive token acquisition failed: {context}")
            else:
                raise BrokerError(f"Token acquisition failed: {context}")
        token = btr.get("accessToken", "")
        if not token:
            raise BrokerError("Broker returned empty access token")
        log.info("Token acquired (%d bytes)", len(token))
        return token

    def acquire_prt_sso_cookie(self, account: dict, sso_url: str) -> dict:
        # Parameter set mirrors the linux-entra-sso PRT implementation.
        auth_params = {
            "account": account,
            "additionalQueryParametersForAuthorization": {},
            "authority": "https://login.microsoftonline.com/common",
            "authorizationType": 8,
            "clientId": EDGE_BROWSER_CLIENT_ID,
            "redirectUri": RDP_REDIRECT_URI,
            "requestedScopes": [GRAPH_SCOPE],
            "username": account.get("username", ""),
            "uxContextHandle": -1,
            "ssoUrl": sso_url,
        }
        request = {
            "account": account,
            "authParameters": auth_params,
            "mamEnrollment": False,
            "ssoUrl": sso_url,
        }
        result = self._call(
            "acquirePrtSsoCookie", json.dumps(request), timeout=BROKER_PRT_TIMEOUT
        )
        if "cookieItems" in result and not result.get("cookieName"):
            items = result["cookieItems"]
            if items:
                result = items[0]
        error = result.get("error")
        if error:
            context = error.get("context", "unknown") if isinstance(error, dict) else error
            raise BrokerError(f"PRT cookie acquisition failed: {str(context)[:200]}")
        cookie_name = result.get("cookieName", "")
        cookie_content = result.get("cookieContent", "")
        if not cookie_name or not cookie_content:
            raise BrokerError("Broker returned an empty PRT cookie")
        return {"cookieName": cookie_name, "cookieContent": cookie_content}

    def _call(self, method: str, request_json: str, timeout: int = None) -> dict:
        if not self._iface:
            raise BrokerError("Not connected to broker")
        try:
            result = getattr(self._iface, method)(
                "0.0", str(uuid.uuid4()), request_json,
                timeout=timeout if timeout is not None else BROKER_TIMEOUT,
            )
            return json.loads(result)
        except dbus.exceptions.DBusException as e:
            raise BrokerError(f"D-Bus call {method} failed: {e.get_dbus_message()[:200]}") from e
