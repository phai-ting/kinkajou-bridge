from __future__ import annotations

import sys

from kinkajou_bridge.platform_ui import gui_session_available


def test_gui_session_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert gui_session_available() is True


def test_gui_session_linux_needs_display(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert gui_session_available() is False
    monkeypatch.setenv("DISPLAY", ":0")
    assert gui_session_available() is True


def test_gui_session_darwin_ssh(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    assert gui_session_available() is True
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 1234 5.6.7.8 22")
    assert gui_session_available() is False
