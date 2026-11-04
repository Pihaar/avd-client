#!/bin/bash
# Register the ms-appx-web:// protocol handler for avd-client.
# This allows the browser to automatically redirect back to avd-client
# after successful authentication.
#
# Run once after installation: avd-client-install-handler
# Or as part of RPM %post scriptlet.

set -e

DESKTOP_FILE="avd-client-auth.desktop"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

# Find the .desktop file
SOURCE=""
for path in \
    "/usr/share/applications/${DESKTOP_FILE}" \
    "/usr/local/share/applications/${DESKTOP_FILE}" \
    "$(dirname "$0")/../contrib/${DESKTOP_FILE}" \
    "$(dirname "$(readlink -f "$0")")/../contrib/${DESKTOP_FILE}"; do
    if [ -f "$path" ]; then
        SOURCE="$path"
        break
    fi
done

if [ -z "$SOURCE" ]; then
    # Create it inline
    mkdir -p "$DESKTOP_DIR"
    cat > "${DESKTOP_DIR}/${DESKTOP_FILE}" << 'DESKTOP'
[Desktop Entry]
Type=Application
Name=AVD Client Auth Handler
Comment=Handles ms-appx-web:// protocol redirects for Azure Virtual Desktop authentication
Exec=avd-client-protocol-handler %u
NoDisplay=true
MimeType=x-scheme-handler/ms-appx-web;
DESKTOP
else
    mkdir -p "$DESKTOP_DIR"
    cp "$SOURCE" "${DESKTOP_DIR}/${DESKTOP_FILE}"
fi

# Register as default handler for ms-appx-web://
xdg-mime default "$DESKTOP_FILE" x-scheme-handler/ms-appx-web

echo "Protocol handler registered: ms-appx-web:// -> avd-client-protocol-handler"
echo "Browser will now automatically redirect AVD auth callbacks."
