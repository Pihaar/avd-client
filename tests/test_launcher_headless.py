"""Tests for the optional headless session-host authentication."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from avd_client.launcher import (
    _browser_candidates,
    _continue_with_prt,
    _headless_auth,
    _safe_url,
)

URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1"
REDIRECT = "ms-appx-web://microsoft.aad.brokerplugin/test?code=abc&state=xyz"


@pytest.fixture(autouse=True)
def _no_external_browsers(monkeypatch):
    monkeypatch.setattr("avd_client.launcher.shutil.which", lambda name: None)


def _working_browser_type(redirect, engine="chromium"):
    page = MagicMock()
    handlers = []
    page.on.side_effect = lambda event, handler: handlers.append(handler)

    def goto(url, **kwargs):
        for handler in handlers:
            handler(SimpleNamespace(url=redirect))

    page.goto.side_effect = goto
    page.url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    page.wait_for_timeout.return_value = None
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.version = "131.0.0.0"
    browser.browser_type.name = engine
    browser.new_context.return_value = context
    browser_type = MagicMock()
    browser_type.launch.return_value = browser
    return browser_type, page


def _fake_playwright(redirect=REDIRECT, working="chromium"):
    chromium, chrome_page = _working_browser_type(redirect, "chromium")
    firefox, firefox_page = _working_browser_type(redirect, "firefox")
    webkit, webkit_page = _working_browser_type(redirect, "webkit")
    if working != "chromium":
        chromium.launch.side_effect = RuntimeError("no chromium")
    if working != "firefox":
        firefox.launch.side_effect = RuntimeError("no firefox")
    if working != "webkit":
        webkit.launch.side_effect = RuntimeError("no webkit")
    playwright = MagicMock()
    playwright.__enter__.return_value = playwright
    playwright.chromium = chromium
    playwright.firefox = firefox
    playwright.webkit = webkit
    pages = {"chromium": chrome_page, "firefox": firefox_page, "webkit": webkit_page}
    return playwright, pages[working]


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
        browser = fake.chromium.launch.return_value
        options = browser.new_context.call_args.kwargs
        assert "HeadlessChrome" not in options["user_agent"]
        assert "Chrome/131.0.0.0" in options["user_agent"]
        context = browser.new_context.return_value
        pattern, handler = context.route.call_args.args
        assert pattern == "https://login.microsoftonline.com/**"
        route = MagicMock()
        route.request.headers = {"accept": "text/html"}
        handler(route)
        assert route.continue_.call_args.kwargs["headers"] == {
            "accept": "text/html",
            "n": "c",
        }

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_firefox_fallback(self, mock_playwright, mock_cookie):
        fake, _ = _fake_playwright(working="firefox")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == REDIRECT
        browser = fake.firefox.launch.return_value
        assert browser.new_context.call_args.kwargs == {}

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_webkit_fallback(self, mock_playwright, mock_cookie):
        fake, _ = _fake_playwright(working="webkit")
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == REDIRECT

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_all_browsers_fail(self, mock_playwright, mock_cookie):
        fake, _ = _fake_playwright()
        fake.chromium.launch.side_effect = RuntimeError("no chromium")
        fake.firefox.launch.side_effect = RuntimeError("no firefox")
        fake.webkit.launch.side_effect = RuntimeError("no webkit")
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
    def test_page_url_fallback(self, mock_playwright, mock_cookie):
        fake, page = _fake_playwright(redirect="https://example.invalid/")
        page.goto.side_effect = lambda url, **kwargs: None
        page.url = REDIRECT
        mock_playwright.return_value = fake
        assert _headless_auth(URL) == REDIRECT

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
    def test_no_redirect_logs_page_state(self, mock_playwright, mock_cookie, caplog):
        fake, page = _fake_playwright(redirect="https://example.invalid/")
        page.url = "https://login.microsoftonline.com/common/login?code=SECRET"
        page.title.return_value = "Sign in to your account"
        page.content.return_value = "<html>AADSTS50058: silent auth failed</html>"
        mock_playwright.return_value = fake
        with caplog.at_level("INFO", logger="avd_client.launcher"):
            assert _headless_auth(URL) == ""
        text = caplog.text
        assert "login.microsoftonline.com/common/login" in text
        assert "Sign in to your account" in text
        assert "AADSTS50058" in text
        assert "SECRET" not in text

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_no_redirect_without_error_code(self, mock_playwright, mock_cookie, caplog):
        fake, page = _fake_playwright(redirect="https://example.invalid/")
        page.title.return_value = "Sign in"
        page.content.return_value = "<html>no error code</html>"
        mock_playwright.return_value = fake
        with caplog.at_level("INFO", logger="avd_client.launcher"):
            assert _headless_auth(URL) == ""
        assert "AAD error code" not in caplog.text

    @patch("avd_client.launcher.get_prt_cookie",
           return_value={"cookieName": "n", "cookieContent": "c"})
    @patch("avd_client.launcher.sync_playwright")
    def test_no_redirect_title_error(self, mock_playwright, mock_cookie):
        fake, page = _fake_playwright(redirect="https://example.invalid/")
        page.title.side_effect = RuntimeError("closed")
        page.content.side_effect = RuntimeError("closed")
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

    def test_browser_candidates_include_channels_and_external(self, monkeypatch):
        monkeypatch.setattr(
            "avd_client.launcher.shutil.which",
            lambda name: f"/usr/bin/{name}" if name in {"brave", "opera", "librewolf"} else None,
        )
        playwright = MagicMock()
        labels = [label for label, _, _ in _browser_candidates(playwright)]
        assert labels[:3] == ["chromium", "firefox", "webkit"]
        assert "chrome" in labels and "msedge" in labels
        assert "brave" in labels and "opera" in labels and "librewolf" in labels
        assert "vivaldi" not in labels


def test_safe_url_strips_query_and_fragment():
    assert _safe_url("https://x.example/p?code=1#f") == "https://x.example/p"
    assert _safe_url("about:blank") == "about:blank"


def test_continue_with_prt_falls_back_without_headers():
    route = MagicMock()
    route.request.headers = {"accept": "text/html"}
    route.continue_.side_effect = [RuntimeError("closed"), None]
    _continue_with_prt(route, "n", "c")
    assert route.continue_.call_count == 2
    route.continue_.assert_called_with()


def test_continue_with_prt_swallows_errors():
    route = MagicMock()
    route.request.headers = {}
    route.continue_.side_effect = RuntimeError("closed")
    _continue_with_prt(route, "n", "c")
    assert route.continue_.call_count == 2
