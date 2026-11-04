"""Tests for avd_client.protocol_handler."""


import pytest


class TestProtocolHandler:
    def test_valid_redirect_writes_file(self, xdg_runtime, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["handler", "ms-appx-web://microsoft.aad.brokerplugin/a85cf173?code=testcode123"],
        )
        from avd_client.protocol_handler import main

        main()
        callback = xdg_runtime / "avd-client-auth-callback"
        assert callback.exists()
        content = callback.read_text()
        assert content == "ms-appx-web://microsoft.aad.brokerplugin/a85cf173?code=testcode123"

    def test_file_mode_0600(self, xdg_runtime, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["handler", "ms-appx-web://microsoft.aad.brokerplugin/a85cf173?code=x"],
        )
        from avd_client.protocol_handler import main

        main()
        callback = xdg_runtime / "avd-client-auth-callback"
        mode = oct(callback.stat().st_mode & 0o777)
        assert mode == "0o600"

    def test_rejects_wrong_scheme(self, xdg_runtime, monkeypatch):
        monkeypatch.setattr("sys.argv", ["handler", "https://evil.com/steal"])
        from avd_client.protocol_handler import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_rejects_control_chars(self, xdg_runtime, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["handler", "ms-appx-web://microsoft.aad.brokerplugin/\r\ninjection"],
        )
        from avd_client.protocol_handler import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_rejects_too_long(self, xdg_runtime, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["handler", "ms-appx-web://microsoft.aad.brokerplugin/" + "a" * 9000],
        )
        from avd_client.protocol_handler import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["handler"])
        from avd_client.protocol_handler import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_atomic_write(self, xdg_runtime, monkeypatch):
        """Verify .tmp file doesn't persist after successful write."""
        monkeypatch.setattr(
            "sys.argv",
            ["handler", "ms-appx-web://microsoft.aad.brokerplugin/test?code=x"],
        )
        from avd_client.protocol_handler import main

        main()
        tmp_file = xdg_runtime / "avd-client-auth-callback.tmp"
        assert not tmp_file.exists()
