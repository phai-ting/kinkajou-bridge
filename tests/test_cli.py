from __future__ import annotations

from kinkajou_bridge.cli import build_parser


def test_default_mode_is_tray() -> None:
    args = build_parser().parse_args([])
    assert args.service is False
    assert args.tray is False  # tray is default when neither flag is set
    assert args.windows_service is False


def test_service_flag() -> None:
    args = build_parser().parse_args(["--service"])
    assert args.service is True
    assert args.tray is False


def test_explicit_tray_flag() -> None:
    args = build_parser().parse_args(["--tray"])
    assert args.tray is True
    assert args.service is False
