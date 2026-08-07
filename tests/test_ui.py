from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kinkajou_bridge.api import create_api
from kinkajou_bridge.app import BridgeApp
from kinkajou_bridge.settings import Settings
from kinkajou_bridge.ui.state import UiStateStore


def test_ui_state_welcome_flag(tmp_path: Path) -> None:
    store = UiStateStore(tmp_path / "ui_state.json")
    assert store.load().welcome_completed is False
    store.mark_welcome_completed()
    assert UiStateStore(tmp_path / "ui_state.json").load().welcome_completed is True


def test_welcome_and_setup_pages(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, open_ui_on_start=False)
    bridge = BridgeApp(settings)
    with TestClient(create_api(bridge)) as client:
        welcome = client.get("/ui/welcome")
        assert welcome.status_code == 200
        assert "Welcome to Kinkajou Bridge" in welcome.text
        assert "Documentation" in welcome.text
        assert "Project Kinkajou website" not in welcome.text
        assert 'href="https://kinkajou.dev/bridge/"' in welcome.text

        setup = client.get("/ui/setup")
        assert setup.status_code == 200
        assert "Add a printer" in setup.text
        assert "Services" in setup.text
        assert "Printers" in setup.text
        assert "Connect service" not in setup.text
        assert "Streamer.bot" in setup.text
        assert "Connect Streamer.bot" not in setup.text
        assert "How do you want to add this printer?" in setup.text
        assert "Cloud via service" in setup.text

        overview = client.get("/bridge/overview/")
        assert overview.status_code == 200
        assert "bridge-client.js" in overview.text
        client_js = client.get("/bridge/_shared/bridge-client.js")
        assert client_js.status_code == 200
        assert "watchPrinter" in client_js.text
        assert 'id="choose-cloud"' in setup.text
        assert "Standalone / LAN" in setup.text
        assert "Which printer type?" in setup.text

        setup_service = client.get("/ui/setup?kind=service")
        assert setup_service.status_code == 200

        setup_integration = client.get("/ui/setup?kind=integration")
        assert setup_integration.status_code == 200
        assert 'href="/ui/setup?kind=integration"' in setup_integration.text
        assert 'id="link-integration"' in setup_integration.text
        assert 'id="integration-status-panel"' in setup_integration.text
        assert "Edit connection" in setup_integration.text
        assert ">Streamer.bot<" in setup_integration.text

        state = client.get("/v1/ui/state")
        assert state.status_code == 200
        assert state.json()["welcome_completed"] is False
        assert state.json()["website_url"] == "https://kinkajou.dev"
        assert state.json()["docs_url"] == "https://kinkajou.dev/bridge/"

        complete = client.post("/v1/ui/welcome/complete")
        assert complete.status_code == 200
        assert complete.json()["welcome_completed"] is True

        root = client.get("/", follow_redirects=False)
        assert root.status_code in {307, 302}
        assert root.headers["location"] == "/ui/"


def test_service_and_printer_api_flow(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, open_ui_on_start=False)
    bridge = BridgeApp(settings)
    with TestClient(create_api(bridge)) as client:
        service_plugins = client.get("/v1/services/plugins")
        assert service_plugins.status_code == 200
        assert any(p["id"] == "bambu_cloud" for p in service_plugins.json())

        printer_plugins = client.get("/v1/printers/plugins")
        assert printer_plugins.status_code == 200
        ids = {p["id"] for p in printer_plugins.json()}
        assert "bambu" in ids
        assert "octoprint" in ids

        created = client.post(
            "/v1/services",
            json={
                "name": "Bambu",
                "plugin_id": "bambu_cloud",
                "config": {"cloud_token": "tok-secret-value", "name": "Bambu"},
            },
        )
        assert created.status_code == 200
        created_body = created.json()
        service_id = created_body["id"]
        assert created_body["config"]["cloud_token"] == "***"
        assert "tok-secret-value" not in created.text

        devices = client.get(f"/v1/services/{service_id}/devices")
        assert devices.status_code == 200
        listed = devices.json()
        assert len(listed) >= 1
        assert listed[0]["serial"]
        assert listed[0]["name"]

        printer = client.post(
            "/v1/printers",
            json={
                "name": "P1S",
                "plugin_id": "bambu",
                "service_instance_id": service_id,
                "config": {"connection_mode": "service", "serial": "01P00CTEST000001"},
            },
        )
        assert printer.status_code == 200
        assert printer.json()["service_instance_id"] == service_id

        lan = client.post(
            "/v1/printers",
            json={
                "name": "LAN",
                "plugin_id": "bambu",
                "config": {
                    "connection_mode": "lan",
                    "serial": "01P00CLAN0000001",
                    "host": "192.168.1.50",
                    "access_code": "secretcode",
                },
            },
        )
        assert lan.status_code == 200
        assert lan.json()["config"]["access_code"] == "***"
        assert lan.json()["config"]["host"] == "192.168.1.50"
        assert "secretcode" not in lan.text

        listed = client.get("/v1/services")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["name"]
        assert "config" in listed.json()[0]
        assert listed.json()[0]["config"].get("cloud_token") == "***"
        assert "status" in listed.json()[0]
        assert "tok-secret-value" not in listed.text


def test_integration_api_redacts_password(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, open_ui_on_start=False)
    bridge = BridgeApp(settings)
    with TestClient(create_api(bridge)) as client:
        plugins = client.get("/v1/integrations/plugins")
        assert plugins.status_code == 200
        assert any(p["id"] == "streamerbot" for p in plugins.json())

        created = client.post(
            "/v1/integrations",
            json={
                "name": "Streamer.bot",
                "plugin_id": "streamerbot",
                "config": {
                    "host": "127.0.0.1",
                    "port": 8080,
                    "endpoint": "/",
                    "password": "super-secret-pw",
                },
            },
        )
        assert created.status_code == 200
        body = created.json()
        assert body["name"] == "Streamer.bot"
        assert body["config"]["password"] == "***"
        assert body["config"]["host"] == "127.0.0.1"
        assert "name" not in body["config"] or body["config"].get("name") == "Streamer.bot"
        assert "super-secret-pw" not in created.text

        listed = client.get("/v1/integrations")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["name"] == "Streamer.bot"
        assert listed.json()[0]["config"]["host"] == "127.0.0.1"
        assert listed.json()[0]["config"]["password"] == "***"
        assert "status" in listed.json()[0]
        assert "super-secret-pw" not in listed.text

        # Saving again updates the single Streamer.bot connection (covers all printers).
        # Omitting password keeps the existing secret.
        again = client.post(
            "/v1/integrations",
            json={
                "name": "Something Else",
                "plugin_id": "streamerbot",
                "config": {
                    "host": "127.0.0.1",
                    "port": 8081,
                    "endpoint": "/",
                },
            },
        )
        assert again.status_code == 200
        assert len(client.get("/v1/integrations").json()) == 1
        assert again.json()["name"] == "Streamer.bot"
        assert again.json()["config"]["port"] == 8081
        assert again.json()["config"]["password"] == "***"
        stored = bridge.integration_store.list()[0]
        assert stored.config["password"] == "super-secret-pw"


def test_no_autolaunch_when_printer_exists(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, open_ui_on_start=True)
    bridge = BridgeApp(settings)
    with TestClient(create_api(bridge)) as client:
        assert bridge.should_open_ui_on_start() is True
        client.post(
            "/v1/printers",
            json={
                "name": "P1S",
                "plugin_id": "bambu",
                "config": {
                    "connection_mode": "lan",
                    "serial": "01P00C123456789",
                    "host": "192.168.1.50",
                    "access_code": "12345678",
                },
            },
        )
        assert bridge.should_show_welcome() is False
        assert bridge.should_open_ui_on_start() is False
        root = client.get("/", follow_redirects=False)
        assert root.headers["location"] == "/ui/"
