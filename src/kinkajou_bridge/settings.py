from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KINKAJOU_BRIDGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 29067
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".kinkajou-bridge")
    api_token: str | None = None
    website_url: str = "https://kinkajou.dev"
    open_ui_on_start: bool = True
    streamerbot_host: str = "127.0.0.1"
    streamerbot_port: int = 8080
    streamerbot_endpoint: str = "/"
    streamerbot_password: str | None = None
    streamerbot_enabled: bool = False

    @property
    def instances_path(self) -> Path:
        return self.data_dir / "instances.json"

    @property
    def services_path(self) -> Path:
        return self.data_dir / "services.json"

    @property
    def integrations_path(self) -> Path:
        return self.data_dir / "integrations.json"

    @property
    def ui_state_path(self) -> Path:
        return self.data_dir / "ui_state.json"

    @property
    def custom_overlays_path(self) -> Path:
        """User-writable overlays served at ``/bridge/custom/``."""
        return self.data_dir / "overlays" / "custom"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def welcome_url(self) -> str:
        return f"{self.base_url}/ui/welcome"

    @property
    def dashboard_url(self) -> str:
        return f"{self.base_url}/ui/"

    @property
    def setup_url(self) -> str:
        return f"{self.base_url}/ui/setup"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/health"
