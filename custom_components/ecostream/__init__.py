"""The ecostream integration (stable version with reconnect logic)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import logging
import websockets  # type: ignore

from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.const import CONF_HOST, Platform  # type: ignore
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator  # type: ignore

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.FAN,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.VALVE,
    Platform.SWITCH,
]


class EcostreamWebsocketsAPI:
    """Handle a persistent connection to an Ecostream websocket."""

    def __init__(self) -> None:
        self.connection: websockets.WebSocketClientProtocol | None = None
        self._host: str | None = None
        self._data: dict = {}
        self._device_name: str | None = None
        self._listen_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def connect(self, host: str):
        """Establish a websocket connection and start listener."""
        self._host = host
        await self._connect_once()
        self._listen_task = asyncio.create_task(self._listen())

    async def _connect_once(self):
        """Perform one connection attempt."""
        _LOGGER.debug("Connecting to Ecostream at ws://%s", self._host)
        self.connection = await websockets.connect(f"ws://{self._host}")
        _LOGGER.info("Connected to Ecostream at %s", self._host)

    async def _listen(self):
        """Background listener loop."""
        while not self._stop_event.is_set():
            if not self.connection:
                await asyncio.sleep(2)
                continue

            try:
                msg = await self.connection.recv()
                parsed = json.loads(msg)

                for key in ["comm_wifi", "system", "config", "status"]:
                    self._data[key] = self._data.get(key, {}) | parsed.get(key, {})

                # Capture device name if present
                if "system" in parsed and "system_name" in parsed["system"]:
                    self._device_name = parsed["system"]["system_name"]

            except websockets.ConnectionClosed as e:
                _LOGGER.warning("Websocket closed (%s). Reconnecting...", e.code)
                await self._reconnect_loop()
            except Exception as e:
                _LOGGER.error("Websocket listener error: %s", e)
                await asyncio.sleep(5)

    async def _reconnect_loop(self):
        """Try reconnecting with exponential backoff."""
        delay = 2
        for attempt in range(1, 6):
            try:
                _LOGGER.info("Reconnect attempt %d to %s", attempt, self._host)
                await self._connect_once()
                _LOGGER.info("Reconnected successfully.")
                return
            except Exception as e:
                _LOGGER.warning("Reconnect attempt %d failed: %s", attempt, e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
        _LOGGER.error("Failed to reconnect after multiple attempts; will keep retrying in background.")

    async def send_json(self, payload: dict):
        """Send a JSON payload through the WebSocket."""
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
        """Return the last known data (non-blocking)."""
        return self._data

    async def close(self):
        """Close connection and stop background task."""
        _LOGGER.debug("Closing Ecostream websocket connection.")
        self._stop_event.set()
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
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
            update_interval=timedelta(seconds=120),  # Only occasional refresh
        )

    async def _async_update_data(self):
        """Fetch current cached data from the websocket API."""
        return await self.api.get_data()

    async def send_json(self, payload: dict):
        await self.api.send_json(payload)
        # Immediate refresh to reflect the direct response
        await self.async_refresh()
        # Schedule a short delayed refresh for slower actions
        await self.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ecostream integration."""
    hass.data.setdefault(DOMAIN, {})

    api = EcostreamWebsocketsAPI()
    await api.connect(entry.data[CONF_HOST])

    coordinator = EcostreamDataUpdateCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = api
    hass.data[DOMAIN]["ws_client"] = api
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("Ecostream integration setup complete for host %s", entry.data[CONF_HOST])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Ecostream integration."""
    api: EcostreamWebsocketsAPI | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if api:
        await api.close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
