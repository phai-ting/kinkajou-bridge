"""Ensure only one Bridge process runs per machine/user session."""

from __future__ import annotations

import atexit
import logging
import sys
from pathlib import Path
from types import TracebackType
from typing import Self

logger = logging.getLogger(__name__)

# Local (per-user-session) mutex — avoids needing admin for Global\\.
_WINDOWS_MUTEX_NAME = "Local\\KinkajouBridgeSingleInstance"


class SingleInstanceLock:
    """Process-wide lock. Keep the instance alive for the lifetime of Bridge."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._held = False
        self._handle: object | None = None
        self._fp: object | None = None

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns False if another instance holds it."""
        if self._held:
            return True
        if sys.platform == "win32":
            ok = self._acquire_windows()
        else:
            ok = self._acquire_posix()
        if ok:
            self._held = True
            atexit.register(self.release)
        return ok

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            atexit.unregister(self.release)
        except Exception:
            pass
        if sys.platform == "win32":
            self._release_windows()
        else:
            self._release_posix()

    def __enter__(self) -> Self:
        if not self.acquire():
            raise RuntimeError("Another Kinkajou Bridge instance is already running.")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    def _acquire_windows(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, _WINDOWS_MUTEX_NAME)
        if not handle:
            logger.warning(
                "Could not create single-instance mutex (error %s)",
                ctypes.get_last_error(),
            )
            return True  # fail open — don't block startup on mutex errors
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def _release_windows(self) -> None:
        if self._handle is None:
            return
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        try:
            kernel32.CloseHandle(self._handle)
        except Exception:
            logger.debug("Failed to release single-instance mutex", exc_info=True)
        self._handle = None

    def _acquire_posix(self) -> bool:
        import fcntl

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fp = open(self._lock_path, "a+", encoding="utf-8")  # noqa: SIM115
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fp.close()
            return False
        except Exception:
            logger.exception("Could not acquire single-instance lock file")
            fp.close()
            return True  # fail open
        fp.seek(0)
        fp.truncate()
        fp.write(str(__import__("os").getpid()))
        fp.flush()
        self._fp = fp
        return True

    def _release_posix(self) -> None:
        fp = self._fp
        self._fp = None
        if fp is None:
            return
        import fcntl

        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except Exception:
            logger.debug("Failed to unlock single-instance file", exc_info=True)
        try:
            fp.close()
        except Exception:
            pass
        try:
            self._lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def acquire_single_instance(data_dir: Path) -> SingleInstanceLock | None:
    """Acquire the Bridge single-instance lock.

    Returns the held lock, or ``None`` if another instance is already running.
    """
    lock = SingleInstanceLock(data_dir / "bridge.instance.lock")
    if lock.acquire():
        return lock
    return None
