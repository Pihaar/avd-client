"""Frontend abstraction for avd-client UI interactions.

The Frontend protocol defines how the application communicates with the user.
CliFrontend implements it for terminal usage; a future GtkFrontend/QtFrontend
can implement the same protocol for GUI usage.

SECURITY INVARIANT: Frontend is an untrusted output sink. It MUST NOT perform
any validation. All input validation happens in security.py / launcher.py.
Frontend.prompt_url() returns raw user input; the caller validates it.
"""

import sys
from typing import TYPE_CHECKING

from .i18n import _

if TYPE_CHECKING:
    from typing import Protocol

    class Frontend(Protocol):
        def pick_one(self, title: str, items: list) -> int: ...
        def notify(self, msg: str) -> None: ...
        def notify_error(self, msg: str) -> None: ...
        def prompt_url(self, instructions: str) -> str: ...
        def on_browser_opened(self) -> None: ...
        def on_auth_success(self) -> None: ...
        def on_connecting(self, resource_title: str) -> None: ...
        def list_resources(self, workspaces_with_resources: list) -> None: ...


class CliFrontend:
    """Terminal-based frontend implementation."""

    def pick_one(self, title: str, items: list) -> int:
        print(title)
        for i, (label, detail) in enumerate(items, 1):
            print(f"  [{i}] {label} ({detail})")

        while True:
            try:
                choice = input(_("Select [1-{n}]: ").format(n=len(items))).strip()
                idx = int(choice) - 1
                if 0 <= idx < len(items):
                    return idx
            except ValueError:
                pass
            except EOFError:
                raise KeyboardInterrupt
            print(_("  Enter a number between 1 and {n}").format(n=len(items)))

    def notify(self, msg: str) -> None:
        print(msg)

    def notify_error(self, msg: str) -> None:
        print(str(msg)[:200], file=sys.stderr)

    def prompt_url(self, instructions: str) -> str:
        print(instructions)
        try:
            return input("> ").strip()
        except EOFError:
            return ""

    def on_browser_opened(self) -> None:
        print(_("Browser opened for authentication..."))

    def on_auth_success(self) -> None:
        print(_("Authentication successful, establishing connection..."))

    def on_connecting(self, resource_title: str) -> None:
        print(_("Connecting to: {title}...").format(title=resource_title))

    def list_resources(self, workspaces_with_resources: list, favorites: set = None,
                       show_all: bool = False) -> None:
        if favorites is None:
            favorites = set()
        for ws_name, ws_geo, resources in workspaces_with_resources:
            print(f"\n  Workspace: {ws_name} ({ws_geo})")
            if not resources:
                if show_all or not favorites:
                    print("    " + _("(no resources)"))
                continue
            for res_id, res_title, res_type in resources:
                is_fav = res_id in favorites
                if not show_all and favorites and not is_fav:
                    continue
                star = " *" if is_fav else ""
                print(f"    [{res_type}] {res_title}{star}")
                print(f"          id={res_id}")

        if favorites and not show_all:
            print("\n  " + _("(* = Favorite. Use --all to show all desktops)"))
        elif not favorites:
            print("\n  " + _("(No favorites set. Use --favorite <id> to set one)"))
