"""Async MQTT session helpers for Bambu Lab LAN and cloud brokers."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiomqtt

from kinkajou_bridge.plugins.bambu.cloud import (
    cloud_mqtt_username,
    mqtt_broker_for_region,
    normalize_cloud_token,
)

logger = logging.getLogger(__name__)

MQTT_PORT = 8883
PUSHALL_PAYLOAD = {
    "pushing": {
        "sequence_id": "0",
        "command": "pushall",
        "version": 1,
        "push_target": 1,
    }
}


@dataclass(frozen=True)
class MqttEndpoint:
    host: str
    port: int
    username: str
    password: str
    serial: str
    tls_insecure: bool
    label: str

    @property
    def report_topic(self) -> str:
        return f"device/{self.serial}/report"

    @property
    def request_topic(self) -> str:
        return f"device/{self.serial}/request"


def lan_endpoint(*, host: str, serial: str, access_code: str) -> MqttEndpoint:
    return MqttEndpoint(
        host=host.strip(),
        port=MQTT_PORT,
        username="bblp",
        password=access_code.strip(),
        serial=serial.strip().upper(),
        tls_insecure=True,
        label=f"LAN ({host.strip()})",
    )


def cloud_endpoint(
    *,
    serial: str,
    cloud_token: str,
    user_id: str,
    region: str | None = None,
) -> MqttEndpoint:
    return MqttEndpoint(
        host=mqtt_broker_for_region(region),
        port=MQTT_PORT,
        username=cloud_mqtt_username(user_id),
        password=normalize_cloud_token(cloud_token),
        serial=serial.strip().upper(),
        tls_insecure=False,
        label=f"cloud ({mqtt_broker_for_region(region)})",
    )


def _ssl_context(*, insecure: bool) -> ssl.SSLContext:
    if insecure:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


def _client_for(endpoint: MqttEndpoint) -> aiomqtt.Client:
    return aiomqtt.Client(
        hostname=endpoint.host,
        port=endpoint.port,
        username=endpoint.username,
        password=endpoint.password,
        tls_context=_ssl_context(insecure=endpoint.tls_insecure),
        keepalive=60,
    )


async def probe_mqtt(endpoint: MqttEndpoint, *, timeout: float = 8.0) -> None:
    """Connect, subscribe, and disconnect to validate credentials/reachability."""
    client = aiomqtt.Client(
        hostname=endpoint.host,
        port=endpoint.port,
        username=endpoint.username,
        password=endpoint.password,
        tls_context=_ssl_context(insecure=endpoint.tls_insecure),
        keepalive=60,
        timeout=timeout,
    )
    async with client:
        await client.subscribe(endpoint.report_topic)


OnMessage = Callable[[dict[str, Any]], Awaitable[None] | None]
OnConnection = Callable[[bool, str | None], Awaitable[None] | None]


async def _publish_pushall(client: aiomqtt.Client, endpoint: MqttEndpoint) -> None:
    await client.publish(
        endpoint.request_topic,
        payload=json.dumps(PUSHALL_PAYLOAD),
    )


async def run_mqtt_session(
    endpoint: MqttEndpoint,
    *,
    on_message: OnMessage,
    on_connection: OnConnection | None = None,
    should_stop: Callable[[], bool],
    reconnect_base_s: float = 2.0,
    reconnect_max_s: float = 30.0,
    pushall_interval_s: float = 45.0,
    stall_timeout_s: float = 90.0,
) -> None:
    """Maintain an MQTT connection until ``should_stop()`` is true.

    If no report arrives for ``stall_timeout_s``, the session reconnects so a
    hung printer/broker link (common with Bambu MQTT) can recover without a
    Bridge restart.
    """
    delay = reconnect_base_s
    while not should_stop():
        push_task: asyncio.Task[None] | None = None
        stalled = False
        try:
            async with _client_for(endpoint) as client:

                async def _periodic_pushall() -> None:
                    while not should_stop():
                        await asyncio.sleep(pushall_interval_s)
                        if should_stop():
                            return
                        try:
                            await _publish_pushall(client, endpoint)
                        except Exception as exc:
                            logger.debug("Periodic pushall failed: %s", exc)
                            return

                await client.subscribe(endpoint.report_topic)
                await _publish_pushall(client, endpoint)
                delay = reconnect_base_s
                if on_connection is not None:
                    result = on_connection(True, None)
                    if asyncio.iscoroutine(result):
                        await result
                logger.info(
                    "Bambu MQTT connected to %s for %s",
                    endpoint.label,
                    endpoint.serial,
                )
                push_task = asyncio.create_task(
                    _periodic_pushall(),
                    name=f"bambu-pushall-{endpoint.serial}",
                )

                messages = aiter(client.messages)
                last_message_at = time.monotonic()
                while not should_stop():
                    remaining = stall_timeout_s - (time.monotonic() - last_message_at)
                    if remaining <= 0:
                        stalled = True
                        break
                    try:
                        message = await asyncio.wait_for(anext(messages), timeout=remaining)
                    except TimeoutError:
                        stalled = True
                        break
                    except StopAsyncIteration:
                        break

                    last_message_at = time.monotonic()
                    try:
                        raw = message.payload
                        if isinstance(raw, bytes):
                            text = raw.decode("utf-8", errors="replace")
                        else:
                            text = str(raw)
                        data = json.loads(text)
                    except Exception as exc:
                        logger.debug("Ignoring bad MQTT payload: %s", exc)
                        continue
                    if not isinstance(data, dict):
                        continue
                    result = on_message(data)
                    if asyncio.iscoroutine(result):
                        await result

                if stalled and not should_stop():
                    logger.warning(
                        "Bambu MQTT telemetry stalled for %.0fs (%s / %s) — reconnecting",
                        stall_timeout_s,
                        endpoint.label,
                        endpoint.serial,
                    )
                    if on_connection is not None:
                        result = on_connection(
                            False,
                            f"telemetry stalled for {int(stall_timeout_s)}s",
                        )
                        if asyncio.iscoroutine(result):
                            await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if should_stop():
                break
            logger.warning(
                "Bambu MQTT session error (%s / %s): %s",
                endpoint.label,
                endpoint.serial,
                exc,
            )
            if on_connection is not None:
                result = on_connection(False, str(exc))
                if asyncio.iscoroutine(result):
                    await result
            await asyncio.sleep(delay)
            delay = min(reconnect_max_s, delay * 1.8)
            continue
        finally:
            if push_task is not None:
                push_task.cancel()
                try:
                    await push_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

        if should_stop():
            break
        # Clean exit from inner loop (stall or iterator ended) — reconnect soon.
        await asyncio.sleep(delay if stalled else reconnect_base_s)
        if stalled:
            delay = reconnect_base_s
        else:
            delay = min(reconnect_max_s, delay * 1.8)
