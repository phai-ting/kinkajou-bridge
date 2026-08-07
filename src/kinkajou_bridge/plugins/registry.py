from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from importlib.metadata import entry_points
from typing import TypeVar

from kinkajou_bridge.plugins.base import IntegrationPlugin, PrinterPlugin, ServicePlugin

logger = logging.getLogger(__name__)

T = TypeVar("T")
PluginFactory = Callable[[], T]


class _Registry[T]:
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._factories: dict[str, PluginFactory[T]] = {}

    def register(self, plugin_id: str, factory: PluginFactory[T]) -> None:
        if plugin_id in self._factories:
            raise ValueError(f"{self._kind} plugin already registered: {plugin_id}")
        self._factories[plugin_id] = factory

    def create(self, plugin_id: str) -> T:
        try:
            factory = self._factories[plugin_id]
        except KeyError as exc:
            raise KeyError(f"Unknown {self._kind} plugin: {plugin_id}") from exc
        return factory()

    def list_ids(self) -> list[str]:
        return sorted(self._factories)

    def load_entry_points(self, group: str) -> None:
        for ep in entry_points(group=group):
            if ep.name in self._factories:
                continue
            try:
                cls = ep.load()
            except Exception:
                logger.exception("Failed to load %s entry point %s", self._kind, ep.name)
                continue
            self.register(ep.name, cls)

    def load_builtins(self, factories: Iterable[tuple[str, PluginFactory[T]]]) -> None:
        for plugin_id, factory in factories:
            if plugin_id not in self._factories:
                self.register(plugin_id, factory)


class ServiceRegistry(_Registry[ServicePlugin]):
    def __init__(self) -> None:
        super().__init__("service")

    def load_entry_points(self, group: str = "kinkajou_bridge.services") -> None:
        super().load_entry_points(group)


class PrinterRegistry(_Registry[PrinterPlugin]):
    def __init__(self) -> None:
        super().__init__("printer")

    def load_entry_points(self, group: str = "kinkajou_bridge.printers") -> None:
        super().load_entry_points(group)


class IntegrationRegistry(_Registry[IntegrationPlugin]):
    def __init__(self) -> None:
        super().__init__("integration")

    def load_entry_points(self, group: str = "kinkajou_bridge.integrations") -> None:
        super().load_entry_points(group)


# Back-compat alias used by older imports / tests.
PluginRegistry = PrinterRegistry
