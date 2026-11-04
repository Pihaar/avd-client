# avd-client

Native Linux client for Azure Virtual Desktop (AVD). Connects to SAP AVD desktops using Microsoft Identity Broker authentication — no browser login required for the gateway connection.

## Features

- Automatic authentication via `microsoft-identity-broker` (D-Bus)
- AVD workspace discovery (all assigned desktops/RemoteApps)
- One-command connection to AVD session hosts via FreeRDP
- Local favorites management
- Internationalization (English + German)
- GUI-ready architecture (Frontend Protocol for future GTK/Qt)

## Requirements

- Linux with `microsoft-identity-broker` installed and device enrolled in Intune
- FreeRDP >= 3.5.0 (with `WITH_AAD=ON`)
- Python >= 3.9
- `dbus-python` >= 1.2

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
│  5. Browser opens for session-host AAD authentication     │
│     (linux-entra-sso provides automatic SSO)              │
│                                                           │
│  6. Protocol handler catches redirect → FreeRDP connects  │
└──────────────────────────────────────────────────────────┘
```

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
| "No accounts found" | Run `intune-portal` to enroll the device |
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
