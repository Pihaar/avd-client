"""Internationalization support for avd-client."""

import gettext
import os

_localedir = os.path.join(os.path.dirname(__file__), "locale")

# gettext.translation with languages=None automatically respects
# LANGUAGE > LC_ALL > LC_MESSAGES > LANG environment variables.
_t = gettext.translation("avd-client", localedir=_localedir, fallback=True)
_ = _t.gettext
