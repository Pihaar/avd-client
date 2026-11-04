"""AVD Feed Discovery — two-stage XML-based workspace enumeration."""

import logging
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .config import (
    FEED_MAX_RESPONSE_BYTES,
    FEED_URL,
    FEED_USER_AGENT,
    NS_DISCOVERY,
    NS_WEBFEED,
)
from .security import SecurityError, validate_feed_url, validate_token_shape

log = logging.getLogger(__name__)


class FeedError(Exception):
    pass


@dataclass
class Resource:
    id: str
    title: str
    type: str
    rdp_url: str
    show_by_default: bool


@dataclass
class Workspace:
    name: str
    tenant_id: str
    feed_url: str
    geo: str
    resources: list  # list[Resource], populated after fetch


def _create_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _fetch(url: str, token: str) -> str:
    validate_token_shape(token)
    validate_feed_url(url)

    ctx = _create_ssl_context()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/xml",
        "Accept-Encoding": "identity",
        "User-Agent": FEED_USER_AGENT,
        "x-ms-user-agent": FEED_USER_AGENT,
        "Connection": "close",
    })
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            raw = resp.read(FEED_MAX_RESPONSE_BYTES + 1)
            if len(raw) > FEED_MAX_RESPONSE_BYTES:
                raise FeedError("Feed response exceeds size limit")
            return raw.decode("utf-8-sig").strip()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise FeedError("Token rejected (HTTP 401). Token may have expired.")
        if e.code == 403:
            raise FeedError("Access denied (HTTP 403). User may not be entitled to AVD.")
        raise FeedError(f"Feed request failed: HTTP {e.code}")
    except urllib.error.URLError as e:
        raise FeedError(f"Network error: {str(e.reason)[:200]}")
    except UnicodeDecodeError as e:
        raise FeedError(f"Invalid response encoding: {e}")


def discover_workspaces(token: str, feed_url: str = FEED_URL) -> list:
    log.info("Discovering workspaces from %s", feed_url)
    text = _fetch(feed_url, token)

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise FeedError(f"Invalid XML in feed response: {str(e)[:200]}")

    if root.get("ARMResources") != "true":
        raise FeedError("No AVD workspaces assigned to this account (ARMResources=false)")

    workspaces = []
    for tf in root.findall(f"{{{NS_DISCOVERY}}}TenantFeedURL"):
        feed_url_attr = tf.get("FeedURL", "")
        if feed_url_attr:
            try:
                validate_feed_url(feed_url_attr)
            except SecurityError:
                log.warning("Skipping workspace with invalid feed URL: %s", feed_url_attr[:50])
                continue
            workspaces.append(Workspace(
                name=tf.get("WorkspaceName", "Unknown"),
                tenant_id=tf.get("TenantId", ""),
                feed_url=feed_url_attr,
                geo=tf.get("Geo", ""),
                resources=[],
            ))

    log.info("Found %d workspace(s)", len(workspaces))
    return workspaces


def fetch_resources(token: str, workspace: Workspace) -> list:
    log.info("Fetching resources for workspace: %s", workspace.name)
    text = _fetch(workspace.feed_url, token)

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise FeedError(f"Invalid XML in workspace feed: {str(e)[:200]}")

    resources = []
    for res_elem in root.findall(f".//{{{NS_WEBFEED}}}Resource"):
        rdp_elem = res_elem.find(f".//{{{NS_WEBFEED}}}ResourceFile")
        rdp_url = ""
        if rdp_elem is not None:
            rdp_url = rdp_elem.get("URL", "")
            # ET already decodes XML entities; no manual &amp; replacement needed

        resources.append(Resource(
            id=res_elem.get("ID", ""),
            title=res_elem.get("Title", "Unknown"),
            type=res_elem.get("Type", "Desktop"),
            rdp_url=rdp_url,
            show_by_default=res_elem.get("ShowByDefault", "true").lower() == "true",
        ))

    workspace.resources = resources
    log.info("Found %d resource(s) in %s", len(resources), workspace.name)
    return resources


def download_rdp_file(token: str, resource: Resource) -> str:
    if not resource.rdp_url:
        raise FeedError(f"No RDP URL for resource {resource.title}")
    log.info("Downloading RDP file for: %s", resource.title)
    content = _fetch(resource.rdp_url, token)
    # FreeRDP 3.x crashes when both smart-sizing and dynamic-resolution are set
    content = content.replace("smart sizing:i:1", "smart sizing:i:0")
    return content


def parse_rdp_properties(rdp_content: str) -> dict:
    props = {}
    for line in rdp_content.splitlines():
        if ":" not in line:
            continue
        parts = line.split(":", 2)
        if len(parts) == 3:
            key, type_char, value = parts
            props[key.strip()] = value.strip()
    return props
