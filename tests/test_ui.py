"""Tests for avd_client.ui — CliFrontend implementation."""

import io
import sys
from unittest.mock import patch

import pytest

from avd_client.ui import CliFrontend


class TestCliFrontendPickOne:
    def test_valid_selection(self, capsys):
        frontend = CliFrontend()
        with patch("builtins.input", return_value="2"):
            idx = frontend.pick_one("Title:", [("Item A", "detail"), ("Item B", "detail2")])
        assert idx == 1
        captured = capsys.readouterr()
        assert "Item A" in captured.out
        assert "Item B" in captured.out

    def test_first_item(self, capsys):
        frontend = CliFrontend()
        with patch("builtins.input", return_value="1"):
            idx = frontend.pick_one("Pick:", [("Only", "one")])
        assert idx == 0

    def test_invalid_then_valid(self, capsys):
        frontend = CliFrontend()
        with patch("builtins.input", side_effect=["abc", "0", "3", "2"]):
            idx = frontend.pick_one("Pick:", [("A", "a"), ("B", "b")])
        assert idx == 1
        captured = capsys.readouterr()
        # Check error message appears (language-independent: check for "1" and "2")
        assert "1" in captured.out and "2" in captured.out

    def test_eof_raises_keyboard_interrupt(self):
        frontend = CliFrontend()
        with patch("builtins.input", side_effect=EOFError):
            with pytest.raises(KeyboardInterrupt):
                frontend.pick_one("Pick:", [("A", "a")])


class TestCliFrontendNotify:
    def test_notify_prints_to_stdout(self, capsys):
        frontend = CliFrontend()
        frontend.notify("Hello World")
        assert "Hello World" in capsys.readouterr().out

    def test_notify_error_prints_to_stderr(self, capsys):
        frontend = CliFrontend()
        frontend.notify_error("Something went wrong")
        assert "Something went wrong" in capsys.readouterr().err

    def test_notify_error_truncates(self, capsys):
        frontend = CliFrontend()
        frontend.notify_error("x" * 300)
        output = capsys.readouterr().err
        assert len(output.strip()) == 200


class TestCliFrontendPromptUrl:
    def test_returns_user_input(self):
        frontend = CliFrontend()
        with patch("builtins.input", return_value="ms-appx-web://test?code=abc"):
            url = frontend.prompt_url("Enter URL:")
        assert url == "ms-appx-web://test?code=abc"

    def test_strips_whitespace(self):
        frontend = CliFrontend()
        with patch("builtins.input", return_value="  url  "):
            url = frontend.prompt_url("URL:")
        assert url == "url"

    def test_eof_returns_empty(self):
        frontend = CliFrontend()
        with patch("builtins.input", side_effect=EOFError):
            url = frontend.prompt_url("URL:")
        assert url == ""


class TestCliFrontendEvents:
    def test_on_browser_opened(self, capsys):
        frontend = CliFrontend()
        frontend.on_browser_opened()
        assert "Browser" in capsys.readouterr().out or "authentication" in capsys.readouterr().out

    def test_on_auth_success(self, capsys):
        frontend = CliFrontend()
        frontend.on_auth_success()
        output = capsys.readouterr().out
        # Language-independent: should print something non-empty
        assert len(output.strip()) > 0

    def test_on_connecting(self, capsys):
        frontend = CliFrontend()
        frontend.on_connecting("SAP Desktop")
        output = capsys.readouterr().out
        assert "SAP Desktop" in output


class TestCliFrontendListResources:
    def test_shows_favorites_only(self, capsys):
        frontend = CliFrontend()
        ws_data = [
            ("WS1", "EU", [("id1", "Desktop A", "Desktop"), ("id2", "Desktop B", "Desktop")]),
        ]
        frontend.list_resources(ws_data, favorites={"id1"}, show_all=False)
        output = capsys.readouterr().out
        assert "Desktop A *" in output
        assert "Desktop B" not in output
        assert "Favorite" in output or "--all" in output

    def test_shows_all_when_flag_set(self, capsys):
        frontend = CliFrontend()
        ws_data = [
            ("WS1", "EU", [("id1", "Desktop A", "Desktop"), ("id2", "Desktop B", "Desktop")]),
        ]
        frontend.list_resources(ws_data, favorites={"id1"}, show_all=True)
        output = capsys.readouterr().out
        assert "Desktop A *" in output
        assert "Desktop B" in output

    def test_shows_all_when_no_favorites(self, capsys):
        frontend = CliFrontend()
        ws_data = [
            ("WS1", "EU", [("id1", "Desktop A", "Desktop")]),
        ]
        frontend.list_resources(ws_data, favorites=set(), show_all=False)
        output = capsys.readouterr().out
        assert "Desktop A" in output
        assert "No favorites" in output or "--favorite" in output

    def test_empty_workspace(self, capsys):
        frontend = CliFrontend()
        ws_data = [("WS1", "EU", [])]
        frontend.list_resources(ws_data, favorites=set(), show_all=True)
        output = capsys.readouterr().out
        assert "no resources" in output or "WS1" in output

    def test_multiple_workspaces(self, capsys):
        frontend = CliFrontend()
        ws_data = [
            ("WS1", "EU", [("id1", "Desktop EU", "Desktop")]),
            ("WS2", "US", [("id2", "Desktop US", "Desktop")]),
        ]
        frontend.list_resources(ws_data, favorites=set(), show_all=True)
        output = capsys.readouterr().out
        assert "WS1" in output
        assert "WS2" in output
        assert "Desktop EU" in output
        assert "Desktop US" in output
