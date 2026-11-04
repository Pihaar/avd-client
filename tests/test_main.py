"""Tests for avd_client.__main__ — CLI parsing and orchestration."""

import pytest

from avd_client.__main__ import parse_args
from avd_client.auth import _upn_hash


class TestParseArgs:
    def test_version_flag(self):
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_list_flag(self):
        args = parse_args(["--list"])
        assert args.list is True

    def test_workspace_flag(self):
        args = parse_args(["--workspace", "Europe"])
        assert args.workspace == "Europe"

    def test_resource_flag(self):
        args = parse_args(["--resource", "SAP Desktop"])
        assert args.resource == "SAP Desktop"

    def test_clipboard_flag(self):
        args = parse_args(["--clipboard"])
        assert args.clipboard is True

    def test_sound_flag(self):
        args = parse_args(["--sound"])
        assert args.sound is True

    def test_microphone_flag(self):
        args = parse_args(["--microphone"])
        assert args.microphone is True

    def test_multimon_flag(self):
        args = parse_args(["--multimon"])
        assert args.multimon is True

    def test_favorite_flag(self):
        args = parse_args(["--favorite", "d0e3096f-08bb-4959-a85a-08de6c261b58"])
        assert args.favorite == "d0e3096f-08bb-4959-a85a-08de6c261b58"

    def test_all_flag(self):
        args = parse_args(["--all"])
        assert args.all is True

    def test_verbose_counting(self):
        args = parse_args(["-vv"])
        assert args.verbose == 2

    def test_defaults(self):
        args = parse_args([])
        assert args.list is False
        assert args.workspace is None
        assert args.resource is None
        assert args.clipboard is False
        assert args.verbose == 0


class TestUpnHash:
    def test_deterministic(self):
        assert _upn_hash("user@example.com") == _upn_hash("user@example.com")

    def test_different_inputs(self):
        assert _upn_hash("user1@example.com") != _upn_hash("user2@example.com")

    def test_length(self):
        assert len(_upn_hash("test@test.com")) == 12

    def test_hex_chars(self):
        h = _upn_hash("test@test.com")
        assert all(c in "0123456789abcdef" for c in h)
