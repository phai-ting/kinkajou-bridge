from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kinkajou_bridge.single_instance import SingleInstanceLock, acquire_single_instance


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex path")
def test_windows_mutex_blocks_second_acquire(tmp_path: Path) -> None:
    first = SingleInstanceLock(tmp_path / "a.lock")
    second = SingleInstanceLock(tmp_path / "b.lock")
    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()
    assert second.acquire() is True
    second.release()


def test_acquire_single_instance_helper(tmp_path: Path) -> None:
    if sys.platform == "win32":
        lock = acquire_single_instance(tmp_path)
        assert lock is not None
        try:
            assert acquire_single_instance(tmp_path) is None
        finally:
            lock.release()
        return

    with patch("kinkajou_bridge.single_instance.SingleInstanceLock") as cls:
        held = MagicMock()
        held.acquire.return_value = True
        cls.return_value = held
        assert acquire_single_instance(tmp_path) is held

        held2 = MagicMock()
        held2.acquire.return_value = False
        cls.return_value = held2
        assert acquire_single_instance(tmp_path) is None
