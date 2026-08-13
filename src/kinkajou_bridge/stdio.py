"""Stdio helpers for frozen / windowed Windows builds."""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO


class _NonTtyStream:
    """Wrap a text stream and always report as non-interactive."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def ensure_stdio() -> None:
    """Guarantee ``sys.stdout`` / ``sys.stderr`` exist.

    PyInstaller ``console=False`` (windowed) EXEs set both to ``None``. Uvicorn's
    default colorized logging then crashes on ``sys.stdout.isatty()``. On Windows,
    ``nul`` can also falsely report ``isatty() == True``, so replacements are
    wrapped to always report non-TTY.
    """
    if sys.stdout is None:
        sys.stdout = _NonTtyStream(_null_stream())  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _NonTtyStream(_null_stream())  # type: ignore[assignment]


def uvicorn_use_colors() -> bool:
    """Whether uvicorn should emit ANSI colors (never when there is no TTY)."""
    if getattr(sys, "frozen", False):
        return False
    stream = sys.stdout
    if stream is None:
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def _null_stream() -> TextIO:
    return open(os.devnull, "w", encoding="utf-8", errors="replace")
