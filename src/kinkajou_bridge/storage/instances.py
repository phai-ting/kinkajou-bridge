from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PrinterInstance(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    plugin_id: str
    enabled: bool = True
    service_instance_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ServiceInstance(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    plugin_id: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class InstanceStore:
    """Persists printer instances (legacy path: instances.json)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._instances: dict[str, PrinterInstance] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._instances = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("instances", raw if isinstance(raw, list) else [])
        self._instances = {
            item["id"]: PrinterInstance.model_validate(item) for item in items
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"instances": [i.model_dump(mode="json") for i in self._instances.values()]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list(self) -> list[PrinterInstance]:
        return sorted(self._instances.values(), key=lambda i: i.name.lower())

    def get(self, instance_id: str) -> PrinterInstance | None:
        return self._instances.get(instance_id)

    def upsert(self, instance: PrinterInstance) -> PrinterInstance:
        self._instances[instance.id] = instance
        self.save()
        return instance

    def delete(self, instance_id: str) -> bool:
        if instance_id not in self._instances:
            return False
        del self._instances[instance_id]
        self.save()
        return True

    def list_by_service(self, service_instance_id: str) -> list[PrinterInstance]:
        return [i for i in self._instances.values() if i.service_instance_id == service_instance_id]


class ServiceStore:
    """Persists connected service instances (services.json)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._instances: dict[str, ServiceInstance] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._instances = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("services", raw if isinstance(raw, list) else [])
        self._instances = {
            item["id"]: ServiceInstance.model_validate(item) for item in items
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"services": [i.model_dump(mode="json") for i in self._instances.values()]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list(self) -> list[ServiceInstance]:
        return sorted(self._instances.values(), key=lambda i: i.name.lower())

    def get(self, instance_id: str) -> ServiceInstance | None:
        return self._instances.get(instance_id)

    def upsert(self, instance: ServiceInstance) -> ServiceInstance:
        self._instances[instance.id] = instance
        self.save()
        return instance

    def delete(self, instance_id: str) -> bool:
        if instance_id not in self._instances:
            return False
        del self._instances[instance_id]
        self.save()
        return True


class IntegrationInstance(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    plugin_id: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class IntegrationStore:
    """Persists outbound integration instances (integrations.json)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._instances: dict[str, IntegrationInstance] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._instances = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("integrations", raw if isinstance(raw, list) else [])
        self._instances = {
            item["id"]: IntegrationInstance.model_validate(item) for item in items
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "integrations": [i.model_dump(mode="json") for i in self._instances.values()]
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list(self) -> list[IntegrationInstance]:
        return sorted(self._instances.values(), key=lambda i: i.name.lower())

    def get(self, instance_id: str) -> IntegrationInstance | None:
        return self._instances.get(instance_id)

    def upsert(self, instance: IntegrationInstance) -> IntegrationInstance:
        self._instances[instance.id] = instance
        self.save()
        return instance

    def delete(self, instance_id: str) -> bool:
        if instance_id not in self._instances:
            return False
        del self._instances[instance_id]
        self.save()
        return True
