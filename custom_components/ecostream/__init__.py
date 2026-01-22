"""Ecostream integration (no pings, with application-level heartbeat)."""

from __future__ import annotations

import asyncio
from datetime import timedelta, datetime
import json
import logging
import websockets  # type: ignore

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.const import CONF_HOST, Platform  # type: ignore
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator  # type: ignore

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_STALE_TIMEOUT = "stale_timeout"

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.FAN,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.VALVE,
    Platform.SWITCH,
    Platform.BINARY_SENSOR
]


class EcostreamWebsocketsAPI:
    """Maintain a persistent WebSocket connection to an Ecostream device."""

    def __init__(self, stale_timeout: int = 300) -> None:
        self.connection: websockets.WebSocketClientProtocol | None = None
        self._host: str | None = None
        self._data: dict = {}
        self._device_name: str | None = None
        self._listen_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._last_message_time: datetime | None = None
        self._stale_timeout = stale_timeout

    async def connect(self, host: str):
        """Establish a websocket connection and start background tasks."""
        self._host = host
        await self._connect_once()
        self._listen_task = asyncio.create_task(self._listen())
        self._watchdog_task = asyncio.create_task(self._watchdog())
        self._heartbeat_task = asyncio.create_task(self._heartbeat())

    async def _connect_once(self):
        """Perform one connection attempt without protocol-level pings."""
        _LOGGER.debug("Connecting to Ecostream at ws://%s", self._host)
        self.connection = await websockets.connect(
            f"ws://{self._host}",
            ping_interval=None,   # disable protocol-level pings
            ping_timeout=None,
        )
        _LOGGER.info("Connected to Ecostream at %s", self._host)
        self._last_message_time = datetime.utcnow()

    async def _listen(self):
        """Continuously receive and process messages from the device."""
        while not self._stop_event.is_set():
            if not self.connection:
                await asyncio.sleep(2)
                continue
            try:
                msg = await self.connection.recv()
                parsed = json.loads(msg)
                self._last_message_time = datetime.utcnow()

                for key in ["comm_wifi", "system", "config", "status"]:
                    self._data[key] = self._data.get(key, {}) | parsed.get(key, {})

                if "system" in parsed and "system_name" in parsed["system"]:
                    self._device_name = parsed["system"]["system_name"]

            except websockets.ConnectionClosed as e:
                _LOGGER.warning("Websocket closed (%s). Reconnecting...", e.code)
                await self._reconnect_loop()
            except Exception as e:
                _LOGGER.error("Websocket listener error: %s", e)
                await asyncio.sleep(5)

    async def _heartbeat(self):
        """Send a small heartbeat message every 20 s so the device sees activity."""
        while not self._stop_event.is_set():
            await asyncio.sleep(20)
            try:
                if self.connection:
                    await self.connection.send("{}")
                    _LOGGER.debug("Heartbeat sent")
            except Exception:
                _LOGGER.debug("Heartbeat failed, will rely on reconnect loop")

    async def _watchdog(self):
        """Force reconnect if no messages are received for longer than stale_timeout."""
        while not self._stop_event.is_set():
            await asyncio.sleep(60)
            if not self._last_message_time:
                continue
            elapsed = (datetime.utcnow() - self._last_message_time).total_seconds()
            if elapsed > self._stale_timeout:
                _LOGGER.warning(
                    "No data received for %d s (>%d) — forcing reconnect",
                    int(elapsed),
                    self._stale_timeout,
                )
                await self._reconnect_loop()

    async def _reconnect_loop(self):
        """Try reconnecting with exponential backoff (starting at 10 s)."""
        delay = 10
        for attempt in range(1, 6):
            if self._stop_event.is_set():
                return
            try:
                _LOGGER.info("Reconnect attempt %d to %s (waiting %ds)", attempt, self._host, delay)
                await asyncio.sleep(delay)
                await self._connect_once()
                _LOGGER.info("Reconnected successfully.")
                return
            except Exception as e:
                _LOGGER.warning("Reconnect attempt %d failed: %s", attempt, e)
                delay = min(delay * 2, 60)
        _LOGGER.error("Failed to reconnect after multiple attempts; will retry later.")

    async def send_json(self, payload: dict):
        """Send a JSON payload to the WebSocket."""
        if not self.connection:
            _LOGGER.warning("No active connection, attempting reconnect before sending.")
            await self._reconnect_loop()
        try:
            await self.connection.send(json.dumps(payload))
        except websockets.ConnectionClosed:
            _LOGGER.warning("Connection closed during send. Reconnecting and retrying...")
            await self._reconnect_loop()
            if self.connection:
                await self.connection.send(json.dumps(payload))
        except Exception as e:
            _LOGGER.error("Failed to send data: %s", e)

    async def get_data(self):
        """Return the latest known data (non-blocking)."""
        return self._data

    async def close(self):
        """Cleanly close the connection and stop background tasks."""
        _LOGGER.debug("Closing Ecostream websocket connection.")
        self._stop_event.set()
        for task in (self._listen_task, self._watchdog_task, self._heartbeat_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self.connection:
            await self.connection.close()
            self.connection = None


class EcostreamDataUpdateCoordinator(DataUpdateCoordinator):
    """Home Assistant DataUpdateCoordinator wrapper for Ecostream."""

    def __init__(self, hass: HomeAssistant, api: EcostreamWebsocketsAPI):
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=120),
        )

    async def _async_update_data(self):
        """Fetch current cached data from the WebSocket API."""
        return await self.api.get_data()

    async def send_json(self, payload: dict):
        await self.api.send_json(payload)
        await self.async_refresh()
        await self.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ecostream integration."""
    hass.data.setdefault(DOMAIN, {})

    stale_timeout = entry.options.get(CONF_STALE_TIMEOUT, 300)
    api = EcostreamWebsocketsAPI(stale_timeout=stale_timeout)
    await api.connect(entry.data[CONF_HOST])

    coordinator = EcostreamDataUpdateCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    # Set unique device ID to prevent rediscovery duplicates
    device_name = api._data.get("system", {}).get("system_name")
    if device_name and entry.unique_id is None:
        hass.config_entries.async_update_entry(entry, unique_id=device_name)    

    hass.data[DOMAIN][entry.entry_id] = api
    hass.data[DOMAIN]["ws_client"] = api
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info(
        "Ecostream integration setup complete for host %s "
        "(stale_timeout=%ds, heartbeat=20s, pings disabled)",
        entry.data[CONF_HOST],
        stale_timeout,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Ecostream integration."""
    api: EcostreamWebsocketsAPI | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if api:
        await api.close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
