"""Protocol handler for ms-appx-web:// URIs.

Registered as the xdg handler for ms-appx-web:// protocol.
When the browser redirects to ms-appx-web://Microsoft.AAD.BrokerPlugin/...,
the OS invokes this script with the full URL as argument.

It writes the URL atomically to a well-known file that avd-client is watching.
"""

import os
import re
import sys
import tempfile

_ALLOWED_PREFIX = "ms-appx-web://microsoft.aad.brokerplugin/"
_MAX_URL_LENGTH = 8192
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def main():
    if len(sys.argv) < 2:
        sys.exit(1)

    redirect_url = sys.argv[1]

    if len(redirect_url) > _MAX_URL_LENGTH:
        sys.exit(1)

    if not redirect_url.lower().startswith(_ALLOWED_PREFIX):
        sys.exit(1)

    if _CONTROL_CHAR_PATTERN.search(redirect_url):
        sys.exit(1)

    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    callback_path = os.path.join(xdg_runtime, "avd-client-auth-callback")

    # Atomic write: write to .tmp then rename (POSIX guarantees rename atomicity)
    tmp_path = callback_path + ".tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, redirect_url.encode("utf-8"))
    finally:
        os.close(fd)
    os.rename(tmp_path, callback_path)


if __name__ == "__main__":
    main()
