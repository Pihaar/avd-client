"""FreeRDP launcher — resolves binary, validates version, builds argv, spawns process."""

import logging
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import tempfile
import time
import webbrowser
from urllib.parse import urlsplit, urlunsplit

from .auth import get_prt_cookie
from .config import (
    FREERDP_ALLOWED_PATHS,
    FREERDP_BIN,
    FREERDP_MIN_VERSION,
    FREERDP_SEARCH_NAMES,
    FREERDP_VERSION_PATTERN,
)
from .feed import parse_rdp_properties
from .i18n import _
from .security import (
    SecurityError,
    validate_hostname,
    validate_redirect_url,
    validate_upn,
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # pragma: no cover

log = logging.getLogger(__name__)

# Browser profile dir for isolated instances (avoids conflicting with locked session)
_browser_profile_dir = None


def _open_browser_isolated(url: str):
    """Open URL in an isolated browser instance that works over X11 forwarding.

    Standard webbrowser.open() connects to an already-running browser process
    (which may be on a locked local session). Using --no-remote with a temporary
    profile forces a new independent instance that renders on the current DISPLAY.
    Hardware rendering is disabled for X11-forwarding compatibility.
    """
    global _browser_profile_dir
    browsers = [
        ("librewolf", ["librewolf", "--no-remote", "--new-instance"]),
        ("firefox", ["firefox", "--no-remote"]),
    ]

    for name, base_cmd in browsers:
        if shutil.which(name):
            if _browser_profile_dir is None:
                _browser_profile_dir = tempfile.mkdtemp(prefix="avd-browser-")
                # Disable GPU/WebRender for X11-forwarding compatibility
                user_js = os.path.join(_browser_profile_dir, "user.js")
                with open(user_js, "w") as f:
                    f.write('user_pref("gfx.webrender.all", false);\n')
                    f.write('user_pref("gfx.webrender.enabled", false);\n')
                    f.write('user_pref("layers.acceleration.disabled", true);\n')
                    f.write('user_pref("gfx.x11-egl.force-disabled", true);\n')
                    f.write('user_pref("widget.dmabuf.force-enabled", false);\n')
            cmd = base_cmd + ["--profile", _browser_profile_dir, "--new-window", url]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

    # Fallback to webbrowser module
    webbrowser.open(url)


def _browser_candidates(playwright):
    """Yield (label, browser_type, launch_options) for the available browsers."""
    yield "chromium", playwright.chromium, {}
    yield "firefox", playwright.firefox, {}
    yield "webkit", playwright.webkit, {}
    for channel in (
        "chrome", "chrome-beta", "msedge", "msedge-beta", "msedge-dev", "msedge-canary"
    ):
        yield channel, playwright.chromium, {"channel": channel}
    for name in (
        "brave-browser", "brave", "opera", "vivaldi",
        "google-chrome", "google-chrome-stable", "microsoft-edge", "microsoft-edge-stable",
    ):
        path = shutil.which(name)
        if path:
            yield name, playwright.chromium, {"executable_path": path}
    path = shutil.which("librewolf")
    if path:
        yield "librewolf", playwright.firefox, {"executable_path": path}


def _safe_url(url: str) -> str:
    """Drop query and fragment so diagnostics never contain an auth code."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _context_options(browser) -> dict:
    """Present a desktop Chrome user agent on Chromium based engines."""
    if browser.browser_type.name != "chromium":
        return {}
    major = str(browser.version).split(".")[0]
    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )
    return {"user_agent": user_agent}


def _aad_error_code(page) -> str:
    try:
        match = re.search(r"AADSTS\d+", page.content())
    except Exception:
        return ""
    return match.group(0) if match else ""


def _headless_auth(auth_url: str) -> str:
    """Try the session-host login in a headless browser with a PRT SSO cookie."""
    if sync_playwright is None:
        return ""
    cookie = get_prt_cookie(auth_url)
    if not cookie:
        return ""
    log.info(
        "PRT cookie acquired (%s, %d chars)",
        cookie["cookieName"], len(cookie["cookieContent"]),
    )
    try:
        with sync_playwright() as playwright:
            browser = None
            for label, browser_type, options in _browser_candidates(playwright):
                try:
                    browser = browser_type.launch(headless=True, timeout=5000, **options)
                    log.info("Headless browser: %s", label)
                    break
                except Exception as e:
                    log.info("Headless browser launch failed (%s): %s", label, type(e).__name__)
            if browser is None:
                return ""
            try:
                context = browser.new_context(**_context_options(browser))
                context.add_cookies([{
                    "name": cookie["cookieName"],
                    "value": cookie["cookieContent"],
                    "domain": "login.microsoftonline.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "None",
                }])
                page = context.new_page()
                captured = []

                def on_request(request):
                    if request.url.startswith("ms-appx-web://"):
                        captured.append(request.url)

                def on_navigation(frame):
                    if frame.url.startswith("ms-appx-web://"):
                        captured.append(frame.url)

                page.on("request", on_request)
                page.on("framenavigated", on_navigation)
                response = None
                try:
                    response = page.goto(auth_url, wait_until="commit", timeout=10000)
                    log.info(
                        "Authorize page status: %s",
                        response.status if response else "no response",
                    )
                except Exception as e:
                    log.info("Authorize page navigation failed: %s", type(e).__name__)
                for _ in range(40):
                    if captured:
                        break
                    try:
                        page.wait_for_timeout(250)
                    except Exception:
                        break
                if not captured and page.url.startswith("ms-appx-web://"):
                    captured.append(page.url)
                if not captured:
                    try:
                        title = page.title()
                    except Exception:
                        title = "?"
                    log.info(
                        "No ms-appx-web redirect in the headless browser "
                        "(page: %s, title: %s)",
                        _safe_url(page.url), title,
                    )
                    error = _aad_error_code(page)
                    if error:
                        log.info("AAD error code: %s", error)
                return captured[0] if captured else ""
            finally:
                browser.close()
    except Exception as e:
        log.warning("Headless authentication failed: %s", type(e).__name__)
        return ""


class LauncherError(Exception):
    pass


def resolve_binary() -> str:
    if FREERDP_BIN:
        binary = os.path.realpath(FREERDP_BIN)
        if not os.path.isfile(binary):
            raise LauncherError(f"FREERDP_BIN does not exist: {FREERDP_BIN}")
    else:
        binary = None
        for name in FREERDP_SEARCH_NAMES:
            found = shutil.which(name)
            if found:
                binary = os.path.realpath(found)
                break
        if not binary:
            raise LauncherError(
                "xfreerdp3 not found in PATH. Install FreeRDP >= 3.5.0 "
                "(build from source or use a package repo)"
            )

    if not any(binary.startswith(p) for p in FREERDP_ALLOWED_PATHS):
        raise LauncherError(
            f"FreeRDP binary outside allowed paths: {binary} "
            f"(allowed: {', '.join(FREERDP_ALLOWED_PATHS)})"
        )

    return binary


def check_version(binary: str) -> tuple:
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=5,
            env={"LC_ALL": "C",
                 "PATH": "/usr/bin:/usr/local/bin:/bin",
                 "LD_LIBRARY_PATH": "/usr/local/lib64:" + os.environ.get("LD_LIBRARY_PATH", ""),
                 "HOME": os.environ.get("HOME", "/tmp")},
        )
        output = result.stdout + result.stderr
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("Version check failed: %s", e)
        return (0, 0, 0)

    match = FREERDP_VERSION_PATTERN.search(output)
    if not match:
        log.warning("Could not parse FreeRDP version")
        return (0, 0, 0)

    version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    log.info("FreeRDP version: %d.%d.%d", *version)

    if version < FREERDP_MIN_VERSION:
        raise LauncherError(
            f"FreeRDP {'.'.join(str(v) for v in version)} is too old. "
            f"Minimum required: {'.'.join(str(v) for v in FREERDP_MIN_VERSION)}"
        )
    return version


def build_argv(binary: str, rdp_content: str, token: str, username: str,
               clipboard: bool = False, sound: bool = False,
               microphone: bool = False, multimon: bool = False) -> tuple:
    """Build xfreerdp command line. Returns (argv, rdp_path) tuple.

    rdp_path must be cleaned up by the caller after FreeRDP exits.
    """
    fd, rdp_path = tempfile.mkstemp(prefix="avd-", suffix=".rdp", dir="/tmp")
    os.write(fd, rdp_content.encode("utf-8"))
    os.close(fd)

    props = parse_rdp_properties(rdp_content)
    gateway_host = props.get("gatewayhostname", "").split(":")[0]
    if gateway_host:
        validate_hostname(gateway_host)
    validate_upn(username)

    cmd = [
        binary,
        rdp_path,
        f"/gateway:type:arm,bearer:{token}",
        "/cert:tofu",
    ]

    if clipboard:
        cmd.append("+clipboard")
    if sound:
        cmd.append("/sound:sys:pulse")
    if microphone:
        cmd.append("/microphone:sys:pulse")
    if multimon:
        cmd.append("/multimon")

    return cmd, rdp_path


def _build_exec_env() -> dict:
    """Build a restricted environment for the FreeRDP child process."""
    allowed_keys = {
        "HOME", "USER", "LOGNAME",
        "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
        "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
        "DBUS_SESSION_BUS_ADDRESS",
        "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
        "XKB_DEFAULT_LAYOUT", "XKB_DEFAULT_VARIANT",
        "TERM",
        "PULSE_SERVER", "PIPEWIRE_RUNTIME_DIR",
        "SDL_VIDEODRIVER",
        "GDK_BACKEND",
    }
    env = {k: v for k, v in os.environ.items() if k in allowed_keys}
    env["PATH"] = "/usr/bin:/usr/local/bin:/bin"
    env["LD_LIBRARY_PATH"] = "/usr/local/lib64"
    return env


def launch(
    binary: str, argv: list, rdp_path: str = None, frontend=None, session_info: dict = None
) -> int:
    """Launch FreeRDP with automated session-host auth via system browser.

    Intercepts FreeRDP's OAuth prompt, opens the system browser, and waits
    for the auth callback via the registered ms-appx-web:// protocol handler.
    """
    env = _build_exec_env()

    log.info("Launching FreeRDP: %s", session_info.get("title", "?") if session_info else "?")

    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    callback_path = os.path.join(xdg_runtime, "avd-client-auth-callback")
    try:
        os.unlink(callback_path)
    except FileNotFoundError:
        pass

    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(argv, env=env, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd)
    except OSError:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    os.close(slave_fd)

    log.info("FreeRDP started (PID %d)", proc.pid)

    original_sigterm = signal.getsignal(signal.SIGTERM)
    original_sighup = signal.getsignal(signal.SIGHUP)

    def forward_signal(signum, frame):
        if proc.poll() is None:
            proc.send_signal(signum)

    signal.signal(signal.SIGTERM, forward_signal)
    signal.signal(signal.SIGHUP, forward_signal)

    exit_code = -1
    start_time = time.monotonic()
    output = b""
    auth_handled = False

    try:
        while proc.poll() is None:
            ready = select.select([master_fd], [], [], 0.3)
            if ready[0]:
                try:
                    data = os.read(master_fd, 8192)
                    if not data:
                        break
                    if not auth_handled:
                        output += data
                except OSError:
                    break

            if auth_handled:
                continue

            decoded = output.decode("utf-8", errors="replace")

            url_match = re.search(
                r"Browse to:\s*(https://login\.microsoftonline\.com/[^\s\r\n]+)", decoded
            )
            paste_match = "Paste redirect URL" in decoded

            if url_match and paste_match:
                auth_url = url_match.group(1).strip()
                auth_handled = True
                output = b""  # Free buffer memory

                # Verify protocol handler is ours (#2)
                try:
                    registered = subprocess.run(
                        ["xdg-mime", "query", "default", "x-scheme-handler/ms-appx-web"],
                        capture_output=True, text=True, timeout=5
                    ).stdout.strip()
                    if registered and "avd-client" not in registered:
                        log.warning("ms-appx-web handler is not avd-client: %s", registered)
                except (OSError, subprocess.TimeoutExpired):
                    pass

                redirect_url = ""
                log.info("Trying headless session-host authentication")
                redirect_url = _headless_auth(auth_url)
                if redirect_url:
                    try:
                        validate_redirect_url(redirect_url)
                    except SecurityError as e:
                        log.warning("Headless redirect rejected: %s", e)
                        redirect_url = ""

                if not redirect_url:
                    if frontend:
                        frontend.on_browser_opened()
                    else:
                        print(_("Browser opened for authentication..."))

                    try:
                        _open_browser_isolated(auth_url)
                        log.info("Browser opened for session-host auth")
                    except Exception as e:
                        log.warning("Could not open browser: %s", e)
                        if frontend:
                            frontend.notify(_("Could not open browser. Open manually:"))
                            frontend.notify(f"  {auth_url}")
                        else:
                            print(f"Could not open browser: {auth_url}")

                    redirect_url = _wait_for_auth_callback(callback_path, proc, timeout=120)

                    if redirect_url:
                        try:
                            validate_redirect_url(redirect_url)
                        except SecurityError as e:
                            log.warning("Invalid redirect URL rejected: %s", e)
                            redirect_url = None

                if redirect_url:
                    os.write(master_fd, (redirect_url + "\r\n").encode())
                    log.info("Auth callback received, forwarded to FreeRDP")
                    if frontend:
                        frontend.on_auth_success()
                    else:
                        print(_("Authentication successful, establishing connection..."))
                else:
                    instructions = _(
                        "No automatic redirect received.\n"
                        "Please copy the URL from the browser address bar (starts with ms-appx-web://):"
                    )
                    if frontend:
                        manual_url = frontend.prompt_url(instructions)
                    else:
                        print(instructions)
                        try:
                            manual_url = input("> ").strip()
                        except (EOFError, KeyboardInterrupt):
                            proc.terminate()
                            return 130
                    if manual_url:
                        try:
                            validate_redirect_url(manual_url)
                        except SecurityError as e:
                            log.warning("Invalid redirect URL: %s", e)
                            proc.terminate()
                            return 1
                        os.write(master_fd, (manual_url + "\r\n").encode())
                    else:
                        proc.terminate()
                        return 1

        if proc.poll() is None:
            exit_code = proc.wait()
        else:
            exit_code = proc.returncode

    except KeyboardInterrupt:
        log.info("Ctrl-C received, terminating FreeRDP...")
        proc.terminate()
        try:
            exit_code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log.warning("FreeRDP did not terminate, sending SIGKILL")
            proc.kill()
            exit_code = proc.wait(timeout=5)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.unlink(callback_path)
        except FileNotFoundError:
            pass
        # Cleanup RDP temp file (#5)
        if rdp_path:
            try:
                os.unlink(rdp_path)
            except FileNotFoundError:
                pass
        # Restore signal handlers (#10)
        signal.signal(signal.SIGTERM, original_sigterm)
        signal.signal(signal.SIGHUP, original_sighup)

        duration = int(time.monotonic() - start_time)
        log.info("Session ended (exit=%d, duration=%ds)", exit_code, duration)

    return exit_code


def _wait_for_auth_callback(callback_path: str, proc, timeout: int = 120) -> str:
    """Wait for the protocol handler to write the redirect URL to the callback file.

    Also checks if FreeRDP is still alive (#24).
    """
    start = time.monotonic()

    while time.monotonic() - start < timeout:
        if proc.poll() is not None:
            log.warning("FreeRDP exited during auth wait (code=%d)", proc.returncode)
            return ""
        try:
            with open(callback_path, "r", encoding="utf-8") as f:
                url = f.read().strip()
            if url:
                return url
        except FileNotFoundError:
            pass
        except (OSError, IOError):
            pass
        time.sleep(0.5)

    return ""
