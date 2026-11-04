# avd-client

Native Linux client for Azure Virtual Desktop (AVD). Connects to SAP AVD desktops with Microsoft Identity Broker authentication or a browser-based PKCE login for devices without Intune.

## Features

- Automatic authentication via `microsoft-identity-broker` (D-Bus), with a browser PKCE fallback
- AVD workspace discovery (all assigned desktops/RemoteApps)
- One-command connection to AVD session hosts via FreeRDP
- Local favorites management
- Internationalization (English + German)
- GUI-ready architecture (Frontend Protocol for future GTK/Qt)

## Requirements

- Linux with `microsoft-identity-broker` and an Intune-enrolled device, or a browser for the PKCE login on private devices
- FreeRDP >= 3.5.0 (with `WITH_AAD=ON`)
- Python >= 3.9
- `dbus-python` >= 1.2
- Optional: `python3-keyring` for persistent refresh tokens on private devices
- Optional: Playwright and a Chromium build for headless session-host authentication

## Installation

```bash
# From source (development)
pip install --user -e .

# Register the ms-appx-web:// protocol handler (one-time)
bash contrib/install-protocol-handler.sh
```

After installation, `avd-client` is available in `~/.local/bin/`.

## Usage

```bash
# List all available desktops
avd-client --list --all

# Connect to a specific workspace
avd-client --workspace Europe

# Connect to a specific desktop by title
avd-client --resource "SAP Desktop - Europe"

# With options
avd-client --workspace Europe --clipboard --sound --multimon

# Manage favorites
avd-client --favorite d0e3096f-08bb-4959-a85a-08de6c261b58  # Toggle
avd-client --list                                            # Show only favorites

# German output
LANGUAGE=de avd-client --list
```

## How It Works

```
┌──────────────────────────────────────────────────────────┐
│  avd-client                                               │
│                                                           │
│  1. D-Bus → microsoft-identity-broker                     │
│     acquireTokenSilently → Bearer access token            │
│                                                           │
│  2. HTTPS → rdweb.wvd.microsoft.com                       │
│     Feed Discovery (XML) → Workspaces + Resources         │
│                                                           │
│  3. Download .rdp file for selected desktop               │
│                                                           │
│  4. Launch xfreerdp with gateway bearer token             │
│     /gateway:type:arm,bearer:<token>                      │
│                                                           │
│  5. Browser or headless browser with a PRT cookie         │
│     (linux-entra-sso provides SSO in a normal browser)    │
│                                                           │
│  6. Protocol handler catches redirect → FreeRDP connects  │
└──────────────────────────────────────────────────────────┘
```

Authentication uses the broker when it is available. On private devices without
Intune, the client falls back to an OAuth2 authorization-code flow with PKCE.
On broker devices with Playwright, the session-host login can run in a headless
browser with a PRT cookie.

## Private devices without Intune

If the broker is unavailable or no account is enrolled, `avd-client` opens the
Microsoft sign-in page and then asks for the full redirect URL from the browser
address bar. The URL contains the authorization code; the client validates the
state and exchanges the code immediately. The refresh token is stored in the
system keyring when `python3-keyring` is available; otherwise it stays in memory
only and each start asks for a browser login. Broker-enrolled devices use the
broker's own token cache; the keyring is only used on this PKCE path.

## Headless session-host authentication

On Intune-enrolled devices the client can complete the session-host login in a
headless browser. It requests a PRT SSO cookie from the broker, injects it into
a local headless Chromium, and catches the `ms-appx-web://` redirect. Install
the optional dependency and browser:

```bash
pip install playwright
playwright install chromium
```

Without Playwright or without a broker, the normal browser opens. Private
devices without a broker have no PRT, so the session-host login stays
interactive.

## Configuration

| Environment Variable | Description |
|---|---|
| `FREERDP_BIN` | Path to xfreerdp binary (default: auto-detect) |
| `LANGUAGE` / `LANG` | UI language (`de` for German, `en` for English) |
| `XDG_CONFIG_HOME` | Favorites storage location (default: `~/.config`) |

Favorites are stored in `~/.config/avd-client/favorites.json`.

## Troubleshooting

| Problem | Solution |
|---|---|
| "Cannot connect to microsoft-identity-broker" | Install: `dnf install microsoft-identity-broker` |
| "No accounts found" | The client falls back to the browser PKCE login; run `intune-portal` to enroll the device if the broker is wanted |
| "xfreerdp3 not found" | Install FreeRDP >= 3.5.0 |
| Browser doesn't open | Check X11/Wayland display is available |
| Auth redirect not received | Verify protocol handler: `xdg-mime query default x-scheme-handler/ms-appx-web` |

## Development

```bash
# Install with test dependencies
pip install --user -e ".[test,dev]"

# Run tests
pytest --cov=avd_client --cov-branch

# Lint
ruff check src/ tests/

# Update translations
make i18n
```

## License

MIT — see [LICENSE](LICENSE)
