"""Local favorites management for avd-client.

Favorites are stored as a JSON array of resource UUIDs in
~/.config/avd-client/favorites.json (mode 0600).

SECURITY: Favorites are ONLY used for filtering feed results.
They are NEVER interpolated into argv or passed to external processes.
"""

import json
import logging
import os
import re

log = logging.getLogger(__name__)

_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_MAX_FAVORITES = 1000


def _favorites_path() -> str:
    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg_config, "avd-client", "favorites.json")


def load_favorites() -> set:
    path = _favorites_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, TypeError, OSError):
        return set()

    if not isinstance(data, list):
        return set()

    result = set()
    for item in data[:_MAX_FAVORITES]:
        if isinstance(item, str) and _UUID_PATTERN.fullmatch(item):
            result.add(item)
    return result


def save_favorites(favorites: set) -> None:
    path = _favorites_path()
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, mode=0o700, exist_ok=True)

    validated = sorted(f for f in favorites if _UUID_PATTERN.fullmatch(f))[:_MAX_FAVORITES]

    tmp_path = path + ".tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(validated, f)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    os.rename(tmp_path, path)


def toggle_favorite(resource_id: str) -> bool:
    """Toggle a resource as favorite. Returns True if added, False if removed."""
    if not _UUID_PATTERN.fullmatch(resource_id):
        raise ValueError(f"Invalid resource ID format: {resource_id[:50]}")

    favs = load_favorites()
    if resource_id in favs:
        favs.discard(resource_id)
        save_favorites(favs)
        return False
    else:
        if len(favs) >= _MAX_FAVORITES:
            raise ValueError(f"Maximum number of favorites ({_MAX_FAVORITES}) reached")
        favs.add(resource_id)
        save_favorites(favs)
        return True
