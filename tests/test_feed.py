"""Tests for avd_client.feed — XML parsing, error handling, URL validation."""

import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from avd_client.feed import (
    FeedError,
    Resource,
    Workspace,
    discover_workspaces,
    download_rdp_file,
    fetch_resources,
    parse_rdp_properties,
)

SAMPLE_DISCOVERY_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<TenantFeedURLs
  UserIdType="OrgId"
  ClassicResources="false"
  ARMResources="true"
  xmlns="http://schemas.microsoft.com/ts/2014/03/tswfdiscovery">
  <TenantFeedURL
    TenantId="99c795d2-a02a-4fa1-aa17-ebd9acafb548"
    TenantDefaultDomain="example.com"
    WorkspaceName="Test Workspace"
    ContactEmail=""
    ConsentStatus="Accepted"
    Geo="EU"
    FeedURL="https://rdweb.wvd.microsoft.com/api/arm/feeddiscovery/tenants/99c795d2/webfeed?geo=EU"
    ArmPath="/subscriptions/sub1/resourcegroups/rg1" />
</TenantFeedURLs>
"""

SAMPLE_WORKSPACE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<ResourceCollection PubDate="0001-01-01T00:00:00Z" SchemaVersion="2.1"
  xmlns="http://schemas.microsoft.com/ts/2007/05/tswf">
  <Publisher LastUpdated="2026-01-01T00:00:00Z" Name="Test" ID="ws1">
    <Resources>
      <Resource ID="res1" Title="Test Desktop" Type="Desktop" ShowByDefault="true">
        <Icons><IconRaw FileType="Ico" FileURL="https://rdweb.wvd.microsoft.com/icon.ico" /></Icons>
        <HostingTerminalServers>
          <HostingTerminalServer>
            <ResourceFile FileExtension=".rdp"
              URL="https://rdweb.wvd.microsoft.com/api/arm/feeddiscovery/tenants/t1/rdps/res1.rdp?geo=EU"
            />
          </HostingTerminalServer>
        </HostingTerminalServers>
      </Resource>
    </Resources>
    <TerminalServers><TerminalServer ID="ts1" Name="ts1" /></TerminalServers>
  </Publisher>
</ResourceCollection>
"""

SAMPLE_RDP = """\
gatewayusagemethod:i:1
gatewayhostname:s:afdfp-rdgateway.wvd.microsoft.com:443
full address:s:rdgateway.wvd.microsoft.com
loadbalanceinfo:s:mth://localhost/pool1/host1
enablerdsaadauth:i:1
smart sizing:i:1
dynamic resolution:i:1
"""

DUMMY_TOKEN = "eyJhbGciOiJkaXIi..ivdata.ciphertext.authtag"


def _mock_urlopen(data, status=200):
    """Create a mock for urllib.request.urlopen context manager."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda s, *a: None
    return mock_resp


class TestDiscoverWorkspaces:
    @patch("avd_client.feed.urllib.request.urlopen")
    def test_happy_path(self, mock_url):
        mock_url.return_value = _mock_urlopen(SAMPLE_DISCOVERY_XML)
        workspaces = discover_workspaces(DUMMY_TOKEN)
        assert len(workspaces) == 1
        assert workspaces[0].name == "Test Workspace"
        assert workspaces[0].geo == "EU"
        assert "rdweb.wvd.microsoft.com" in workspaces[0].feed_url

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_no_arm_resources_raises(self, mock_url):
        xml = SAMPLE_DISCOVERY_XML.replace('ARMResources="true"', 'ARMResources="false"')
        mock_url.return_value = _mock_urlopen(xml)
        with pytest.raises(FeedError, match="ARMResources=false"):
            discover_workspaces(DUMMY_TOKEN)

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_http_401_raises(self, mock_url):
        mock_url.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, BytesIO(b""))
        with pytest.raises(FeedError, match="401"):
            discover_workspaces(DUMMY_TOKEN)

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_http_403_raises(self, mock_url):
        mock_url.side_effect = urllib.error.HTTPError(
            "url", 403, "Forbidden", {}, BytesIO(b""))
        with pytest.raises(FeedError, match="403"):
            discover_workspaces(DUMMY_TOKEN)

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_http_500_raises(self, mock_url):
        mock_url.side_effect = urllib.error.HTTPError(
            "url", 500, "Server Error", {}, BytesIO(b""))
        with pytest.raises(FeedError, match="500"):
            discover_workspaces(DUMMY_TOKEN)

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_network_error_raises(self, mock_url):
        mock_url.side_effect = urllib.error.URLError("DNS failed")
        with pytest.raises(FeedError, match="Network error"):
            discover_workspaces(DUMMY_TOKEN)

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_malformed_xml_raises(self, mock_url):
        mock_url.return_value = _mock_urlopen("<invalid xml>>>>>")
        with pytest.raises(FeedError, match="Invalid XML"):
            discover_workspaces(DUMMY_TOKEN)

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_oversized_response_raises(self, mock_url):
        mock_url.return_value = _mock_urlopen("x" * (10 * 1024 * 1024 + 10))
        with pytest.raises(FeedError, match="size limit"):
            discover_workspaces(DUMMY_TOKEN)

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_invalid_feed_url_skipped(self, mock_url):
        xml = SAMPLE_DISCOVERY_XML.replace(
            'FeedURL="https://rdweb.wvd.microsoft.com',
            'FeedURL="https://evil.example.com'
        )
        mock_url.return_value = _mock_urlopen(xml)
        workspaces = discover_workspaces(DUMMY_TOKEN)
        assert len(workspaces) == 0

    @patch("avd_client.feed.urllib.request.urlopen")
    def test_utf8_bom_handled(self, mock_url):
        bom_xml = b"\xef\xbb\xbf" + SAMPLE_DISCOVERY_XML.encode("utf-8")
        mock_url.return_value = _mock_urlopen(bom_xml)
        workspaces = discover_workspaces(DUMMY_TOKEN)
        assert len(workspaces) == 1


class TestFetchResources:
    @patch("avd_client.feed.urllib.request.urlopen")
    def test_happy_path(self, mock_url):
        mock_url.return_value = _mock_urlopen(SAMPLE_WORKSPACE_XML)
        ws = Workspace(name="Test", tenant_id="t1",
                       feed_url="https://rdweb.wvd.microsoft.com/feed", geo="EU", resources=[])
        resources = fetch_resources(DUMMY_TOKEN, ws)
        assert len(resources) == 1
        assert resources[0].title == "Test Desktop"
        assert resources[0].type == "Desktop"
        assert resources[0].show_by_default is True
        assert "rdweb.wvd.microsoft.com" in resources[0].rdp_url


class TestDownloadRdpFile:
    @patch("avd_client.feed.urllib.request.urlopen")
    def test_downloads_and_fixes_smart_sizing(self, mock_url):
        mock_url.return_value = _mock_urlopen(SAMPLE_RDP)
        resource = Resource(id="r1", title="Test", type="Desktop",
                            rdp_url="https://rdweb.wvd.microsoft.com/rdp/r1.rdp",
                            show_by_default=True)
        content = download_rdp_file(DUMMY_TOKEN, resource)
        assert "smart sizing:i:0" in content
        assert "smart sizing:i:1" not in content

    def test_no_rdp_url_raises(self):
        resource = Resource(id="r1", title="Test", type="Desktop",
                            rdp_url="", show_by_default=True)
        with pytest.raises(FeedError, match="No RDP URL"):
            download_rdp_file(DUMMY_TOKEN, resource)


class TestParseRdpProperties:
    def test_parses_key_type_value(self):
        props = parse_rdp_properties("gatewayhostname:s:host.wvd.microsoft.com:443\n")
        assert props["gatewayhostname"] == "host.wvd.microsoft.com:443"

    def test_handles_colons_in_value(self):
        props = parse_rdp_properties("loadbalanceinfo:s:mth://localhost/a/b\n")
        assert props["loadbalanceinfo"] == "mth://localhost/a/b"

    def test_skips_lines_without_colon(self):
        props = parse_rdp_properties("no colon here\nkey:s:val\n")
        assert props == {"key": "val"}

    def test_empty_input(self):
        assert parse_rdp_properties("") == {}

    def test_strips_whitespace(self):
        props = parse_rdp_properties("  key  :s:  value  \n")
        assert props["key"] == "value"
