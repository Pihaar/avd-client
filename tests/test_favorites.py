"""Tests for avd_client.favorites."""

import json

import pytest

from avd_client.favorites import (
    _UUID_PATTERN,
    load_favorites,
    save_favorites,
    toggle_favorite,
)


class TestLoadFavorites:
    def test_empty_when_no_file(self, xdg_config):
        assert load_favorites() == set()

    def test_loads_valid_uuids(self, xdg_config):
        fav_dir = xdg_config / "avd-client"
        fav_dir.mkdir()
        fav_file = fav_dir / "favorites.json"
        fav_file.write_text(json.dumps(["d0e3096f-08bb-4959-a85a-08de6c261b58"]))
        assert load_favorites() == {"d0e3096f-08bb-4959-a85a-08de6c261b58"}

    def test_rejects_invalid_uuids(self, xdg_config):
        fav_dir = xdg_config / "avd-client"
        fav_dir.mkdir()
        fav_file = fav_dir / "favorites.json"
        fav_file.write_text(json.dumps(["not-a-uuid", "d0e3096f-08bb-4959-a85a-08de6c261b58"]))
        assert load_favorites() == {"d0e3096f-08bb-4959-a85a-08de6c261b58"}

    def test_handles_corrupt_json(self, xdg_config):
        fav_dir = xdg_config / "avd-client"
        fav_dir.mkdir()
        (fav_dir / "favorites.json").write_text("{invalid json")
        assert load_favorites() == set()

    def test_handles_non_list(self, xdg_config):
        fav_dir = xdg_config / "avd-client"
        fav_dir.mkdir()
        (fav_dir / "favorites.json").write_text(json.dumps({"key": "value"}))
        assert load_favorites() == set()

    def test_max_limit(self, xdg_config):
        fav_dir = xdg_config / "avd-client"
        fav_dir.mkdir()
        uuids = [f"{i:08x}-0000-0000-0000-000000000000" for i in range(1500)]
        (fav_dir / "favorites.json").write_text(json.dumps(uuids))
        assert len(load_favorites()) == 1000


class TestSaveFavorites:
    def test_creates_directory(self, xdg_config):
        save_favorites({"d0e3096f-08bb-4959-a85a-08de6c261b58"})
        fav_file = xdg_config / "avd-client" / "favorites.json"
        assert fav_file.exists()

    def test_file_mode_0600(self, xdg_config):
        save_favorites({"d0e3096f-08bb-4959-a85a-08de6c261b58"})
        fav_file = xdg_config / "avd-client" / "favorites.json"
        mode = oct(fav_file.stat().st_mode & 0o777)
        assert mode == "0o600"

    def test_dir_mode_0700(self, xdg_config):
        save_favorites({"d0e3096f-08bb-4959-a85a-08de6c261b58"})
        fav_dir = xdg_config / "avd-client"
        mode = oct(fav_dir.stat().st_mode & 0o777)
        assert mode == "0o700"

    def test_validates_uuids_on_save(self, xdg_config):
        save_favorites({"invalid", "d0e3096f-08bb-4959-a85a-08de6c261b58"})
        data = json.loads((xdg_config / "avd-client" / "favorites.json").read_text())
        assert data == ["d0e3096f-08bb-4959-a85a-08de6c261b58"]

    def test_sorted_output(self, xdg_config):
        save_favorites({
            "d0e3096f-08bb-4959-a85a-08de6c261b58",
            "a0000000-0000-0000-0000-000000000000",
        })
        data = json.loads((xdg_config / "avd-client" / "favorites.json").read_text())
        assert data == sorted(data)


class TestToggleFavorite:
    def test_add(self, xdg_config):
        result = toggle_favorite("d0e3096f-08bb-4959-a85a-08de6c261b58")
        assert result is True
        assert "d0e3096f-08bb-4959-a85a-08de6c261b58" in load_favorites()

    def test_remove(self, xdg_config):
        save_favorites({"d0e3096f-08bb-4959-a85a-08de6c261b58"})
        result = toggle_favorite("d0e3096f-08bb-4959-a85a-08de6c261b58")
        assert result is False
        assert "d0e3096f-08bb-4959-a85a-08de6c261b58" not in load_favorites()

    def test_invalid_uuid_raises(self, xdg_config):
        with pytest.raises(ValueError, match="Invalid resource ID"):
            toggle_favorite("not-a-uuid")


class TestUuidPattern:
    @pytest.mark.parametrize("valid", [
        "d0e3096f-08bb-4959-a85a-08de6c261b58",
        "00000000-0000-0000-0000-000000000000",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
    ])
    def test_valid_uuids(self, valid):
        assert _UUID_PATTERN.fullmatch(valid)

    @pytest.mark.parametrize("invalid", [
        "",
        "not-a-uuid",
        "d0e3096f-08bb-4959-a85a-08de6c261b5",  # too short
        "d0e3096f-08bb-4959-a85a-08de6c261b58X",  # too long
        "D0E3096F-08BB-4959-A85A-08DE6C261B58",  # uppercase
        "------------------------------------",  # 36 dashes
    ])
    def test_invalid_uuids(self, invalid):
        assert not _UUID_PATTERN.fullmatch(invalid)
