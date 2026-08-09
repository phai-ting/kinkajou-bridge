"""Helpers for choosing tray vs headless UI by platform / session."""

from __future__ import annotations

import os
import sys


def gui_session_available() -> bool:
    """Return True when a system tray icon is likely to work in this session.

    Windows desktop sessions always report True. macOS assumes a local GUI login
    unless the process is clearly in an SSH session. Linux requires ``DISPLAY``
    or ``WAYLAND_DISPLAY``.
    """
    if sys.platform == "win32":
        return True
    if sys.platform == "darwin":
        if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
            return False
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
