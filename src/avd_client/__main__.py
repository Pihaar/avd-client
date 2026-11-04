"""CLI entry point for avd-client."""

import argparse
import hashlib
import logging
import sys

from . import __version__
from .broker import BrokerClient, BrokerError
from .favorites import load_favorites, toggle_favorite
from .feed import FeedError, discover_workspaces, download_rdp_file, fetch_resources
from .i18n import _
from .launcher import LauncherError, build_argv, check_version, launch, resolve_binary
from .security import SecurityError, install_token_redaction
from .ui import CliFrontend

log = logging.getLogger("avd_client")


def setup_logging(verbosity: int):
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    install_token_redaction()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="avd-client",
        description=_("Native Linux client for Azure Virtual Desktop"),
    )
    parser.add_argument("--version", action="version", version=f"avd-client {__version__}")
    parser.add_argument("--list", action="store_true", help=_("List available desktops and exit"))
    parser.add_argument("--resource", metavar="TITLE", help=_("Connect to a specific resource by title"))
    parser.add_argument("--workspace", metavar="NAME", help=_("Select workspace by name substring"))
    parser.add_argument("--clipboard", action="store_true", help=_("Enable clipboard sharing"))
    parser.add_argument("--sound", action="store_true", help=_("Enable audio output"))
    parser.add_argument("--microphone", action="store_true", help=_("Enable microphone sharing"))
    parser.add_argument("--multimon", action="store_true", help=_("Enable multi-monitor"))
    parser.add_argument("--favorite", metavar="ID", help=_("Toggle a resource as favorite by ID"))
    parser.add_argument("--all", action="store_true", help=_("Show all resources (including non-favorites)"))
    parser.add_argument("-v", "--verbose", action="count", default=0, help=_("Increase verbosity"))
    return parser.parse_args(argv)


def _upn_hash(username: str) -> str:
    return hashlib.sha256(username.encode()).hexdigest()[:12]


def _select_workspace(frontend, workspaces, preference=None):
    if preference:
        for ws in workspaces:
            if preference.lower() in ws.name.lower():
                return ws
        frontend.notify_error(_("No workspace matching '{name}'.").format(name=preference))
        sys.exit(1)

    if len(workspaces) == 1:
        return workspaces[0]

    items = [(ws.name, ws.geo) for ws in workspaces]
    idx = frontend.pick_one(_("Available workspaces:"), items)
    return workspaces[idx]


def _select_resource(frontend, resources, preference=None):
    if preference:
        for r in resources:
            if preference.lower() in r.title.lower():
                return r
        frontend.notify_error(_("No resource matching '{name}'.").format(name=preference))
        sys.exit(1)

    if len(resources) == 1:
        return resources[0]

    items = [(r.title, r.type) for r in resources]
    idx = frontend.pick_one(_("Available resources:"), items)
    return resources[idx]


def main(argv=None):
    args = parse_args(argv)
    setup_logging(args.verbose)
    frontend = CliFrontend()

    try:
        # --favorite: toggle and exit
        if args.favorite:
            added = toggle_favorite(args.favorite)
            if added:
                frontend.notify(_("Added to favorites: {id}").format(id=args.favorite))
            else:
                frontend.notify(_("Removed from favorites: {id}").format(id=args.favorite))
            sys.exit(0)

        # Preflight
        binary = resolve_binary()
        check_version(binary)

        # Auth
        broker = BrokerClient()
        broker.connect()
        log.info("Broker version: %s", broker.get_version())
        accounts = broker.get_accounts()
        account = accounts[0]
        username = account.get("username", "")
        log.info("Account: %s", _upn_hash(username))

        token = broker.acquire_token(account)

        # Discovery
        workspaces = discover_workspaces(token)

        # --list: show resources and exit
        if args.list:
            favorites = load_favorites()
            ws_data = []
            for ws in workspaces:
                resources = fetch_resources(token, ws)
                res_data = [(r.id, r.title, r.type) for r in resources]
                ws_data.append((ws.name, ws.geo, res_data))
            frontend.list_resources(ws_data, favorites=favorites, show_all=args.all)
            sys.exit(0)

        # Connect flow
        workspace = _select_workspace(frontend, workspaces, args.workspace)
        resources = fetch_resources(token, workspace)
        if not resources:
            frontend.notify_error(_("No resources in workspace '{name}'.").format(name=workspace.name))
            sys.exit(3)

        resource = _select_resource(frontend, resources, args.resource)
        rdp_content = download_rdp_file(token, resource)

        cmd, rdp_path = build_argv(
            binary, rdp_content, token, username,
            clipboard=args.clipboard,
            sound=args.sound,
            microphone=args.microphone,
            multimon=args.multimon,
        )

        frontend.on_connecting(resource.title)
        exit_code = launch(binary, cmd, rdp_path=rdp_path, frontend=frontend,
                           session_info={"title": resource.title, "host": workspace.name})
        sys.exit(exit_code)

    except BrokerError as e:
        frontend.notify_error(_("Auth error: {msg}").format(msg=str(e)[:200]))
        sys.exit(2)
    except FeedError as e:
        frontend.notify_error(_("Feed error: {msg}").format(msg=str(e)[:200]))
        sys.exit(3)
    except LauncherError as e:
        frontend.notify_error(_("Launcher error: {msg}").format(msg=str(e)[:200]))
        sys.exit(4)
    except SecurityError as e:
        frontend.notify_error(_("Security error: {msg}").format(msg=str(e)[:200]))
        sys.exit(5)
    except KeyboardInterrupt:
        sys.exit(130)
    except ValueError as e:
        frontend.notify_error(str(e)[:200])
        sys.exit(1)


if __name__ == "__main__":
    main()
