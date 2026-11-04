"""Tests for the optional headless session-host authentication."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from avd_client.launcher import _headless_auth

URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1"
REDIRECT = "ms-appx-web://microsoft.aad.brokerplugin/test?code=abc&state=xyz"


def _fake_playwright(redirect=REDIRECT):
    page = MagicMock()
    handlers = []
    page.on.side_effect = lambda event, handler: handlers.append(handler)

    def goto(url, **kwargs):
        for handler in handlers:
            handler(SimpleNamespace(url=redirect))

    page.goto.side_effect = goto
    page.wait_for_timeout.return_value = None
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.__enter__.return_value = playwright
    playwright.chromium.launch.return_value = browser
    return playwright


class TestHeadlessAuth:
    @patch("avd_client.launcher.sync_playwright", None)
    def test_without_playwright(self):
        assert _headless_auth(URL) == ""

    @patch("avd_client.launcher.get_prt_cookie", return_value=None)
    @patch("avd_client.launcher.sync_playwright")
    def test_without_cookie(self, mock_playwright, mock_cookie):
        assert _headless_auth(URL) == ""
        mock_playwright.assert_not_called()

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_success(self, mock_playwright, mock_cookie):
        mock_playwright.return_value = _fake_playwright()
        assert _headless_auth(URL) == REDIRECT

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_no_redirect(self, mock_playwright, mock_cookie):
        mock_playwright.return_value = _fake_playwright(redirect="https://example.invalid/")
        assert _headless_auth(URL) == ""

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_goto_error_is_ignored(self, mock_playwright, mock_cookie):
        fake = _fake_playwright()
        page = fake.chromium.launch.return_value.new_context.return_value.new_page.return_value
        page.goto.side_effect = RuntimeError("nav")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == ""

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_wait_error_breaks(self, mock_playwright, mock_cookie):
        fake = _fake_playwright(redirect="https://example.invalid/")
        page = fake.chromium.launch.return_value.new_context.return_value.new_page.return_value
        page.wait_for_timeout.side_effect = RuntimeError("closed")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == ""

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_browser_launch_error(self, mock_playwright, mock_cookie):
        fake = _fake_playwright()
        fake.chromium.launch.side_effect = RuntimeError("no browser")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == ""
