"""D-Bus client for microsoft-identity-broker."""

import json
import logging
import uuid

import dbus

from .config import (
    AVD_SCOPE,
    BROKER_BUS_NAME,
    BROKER_INTERFACE,
    BROKER_OBJECT_PATH,
    BROKER_TIMEOUT,
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

    def get_accounts(self) -> list:
        request = json.dumps({
            "clientId": RDP_CLIENT_ID,
            "redirectUri": RDP_REDIRECT_URI,
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
        request = json.dumps({
            "authParameters": {
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
        })
        result = self._call("acquireTokenSilently", request)
        btr = result.get("brokerTokenResponse", {})
        if btr.get("error"):
            err = btr["error"]
            context = err.get("context", "unknown")[:200]
            raise BrokerError(f"Token acquisition failed: {context}")
        token = btr.get("accessToken", "")
        if not token:
            raise BrokerError("Broker returned empty access token")
        log.info("Token acquired (%d bytes)", len(token))
        return token

    def _call(self, method: str, request_json: str) -> dict:
        if not self._iface:
            raise BrokerError("Not connected to broker")
        try:
            result = getattr(self._iface, method)(
                "0.0", str(uuid.uuid4()), request_json, timeout=BROKER_TIMEOUT
            )
            return json.loads(result)
        except dbus.exceptions.DBusException as e:
            raise BrokerError(f"D-Bus call {method} failed: {e.get_dbus_message()[:200]}") from e
