"""Tests for the optional headless session-host authentication."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from avd_client.launcher import _headless_auth

URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1"
REDIRECT = "ms-appx-web://microsoft.aad.brokerplugin/test?code=abc&state=xyz"


def _working_browser_type(redirect):
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
    browser_type = MagicMock()
    browser_type.launch.return_value = browser
    return browser_type, page


def _fake_playwright(redirect=REDIRECT, working="chromium"):
    chromium, chrome_page = _working_browser_type(redirect)
    firefox, firefox_page = _working_browser_type(redirect)
    if working != "chromium":
        chromium.launch.side_effect = RuntimeError("no chromium")
    if working != "firefox":
        firefox.launch.side_effect = RuntimeError("no firefox")
    playwright = MagicMock()
    playwright.__enter__.return_value = playwright
    playwright.chromium = chromium
    playwright.firefox = firefox
    return playwright, chrome_page if working == "chromium" else firefox_page


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
    def test_success_chromium(self, mock_playwright, mock_cookie):
        fake, _ = _fake_playwright()
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == REDIRECT

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_firefox_fallback(self, mock_playwright, mock_cookie):
        fake, _ = _fake_playwright(working="firefox")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == REDIRECT

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_both_browsers_fail(self, mock_playwright, mock_cookie):
        fake, _ = _fake_playwright()
        fake.chromium.launch.side_effect = RuntimeError("no chromium")
        fake.firefox.launch.side_effect = RuntimeError("no firefox")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == ""

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_playwright_context_error(self, mock_playwright, mock_cookie):
        mock_playwright.side_effect = RuntimeError("no playwright")
        assert _headless_auth(URL) == ""

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_no_redirect(self, mock_playwright, mock_cookie):
        fake, _ = _fake_playwright(redirect="https://example.invalid/")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == ""

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_goto_error_is_ignored(self, mock_playwright, mock_cookie):
        fake, page = _fake_playwright()
        page.goto.side_effect = RuntimeError("nav")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == ""

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_wait_error_breaks(self, mock_playwright, mock_cookie):
        fake, page = _fake_playwright(redirect="https://example.invalid/")
        page.wait_for_timeout.side_effect = RuntimeError("closed")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == ""
