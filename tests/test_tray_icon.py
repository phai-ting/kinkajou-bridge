from __future__ import annotations

from kinkajou_bridge.ui.tray import _TRAY_ICON_PATH, _load_tray_image


def test_tray_icon_asset_exists() -> None:
    assert _TRAY_ICON_PATH.is_file()


def test_load_tray_image_uses_asset() -> None:
    image = _load_tray_image()
    assert image.size == (64, 64)
    assert image.mode == "RGBA"
