from __future__ import annotations

import sys

from kinkajou_bridge.stdio import ensure_stdio, uvicorn_use_colors


def test_ensure_stdio_replaces_none_streams(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    ensure_stdio()
    assert sys.stdout is not None
    assert sys.stderr is not None
    assert sys.stdout.isatty() is False
    assert sys.stderr.isatty() is False


def test_uvicorn_use_colors_false_without_tty(monkeypatch) -> None:
    class _NoTty:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdout", _NoTty())
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert uvicorn_use_colors() is False


def test_uvicorn_use_colors_false_when_stdout_none(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert uvicorn_use_colors() is False


def test_uvicorn_use_colors_false_when_frozen(monkeypatch) -> None:
    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdout", _Tty())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert uvicorn_use_colors() is False
