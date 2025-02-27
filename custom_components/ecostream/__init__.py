"""The ecostream integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import logging
import websockets # type: ignore

from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.const import CONF_HOST, Platform # type: ignore
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator # type: ignore

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.FAN,
]

class EcostreamWebsocketsAPI:
    """Class representing the EcostreamWebsocketsAPI."""

    def __init__(self) -> None:
        """Initialize the EcostreamWebsocketsAPI class."""
        self.connection = None
        self._data = None
        self._host = None
        self._update_interval = 60  # Update interval in seconds
        self._update_task = None
        self._config = None

    async def connect(self, host):
        """Connect to the specified host."""
        _LOGGER.debug("Connecting to %s", host)
        self._host = host
        self.connection = await websockets.connect(f"ws://{host}")
        
        initial_response = await self.connection.recv()
        parsed_initial_response = json.loads(initial_response)
        self._config = parsed_initial_response.get('config', {})

    async def reconnect(self):
        """Reconnect to the websocket."""
        _LOGGER.debug("Reconnecting to %s", self._host)
        self.connection = await websockets.connect(f"ws://{self._host}")

    async def get_data(self):
        """Get the data from the API."""
        await self._update_data()
        return self._data

    async def _update_data(self):
        """Update data by receiving from the WebSocket."""
        try:
            response = await self.connection.recv()
            self._data = json.loads(response)
        except websockets.ConnectionClosed:
            _LOGGER.error("Connection closed unexpectedly.")
            await self.reconnect()
        except Exception as e:
            _LOGGER.error("Error receiving data: %s", e)

    async def send_json(self, payload: dict):
        """Send a JSON payload through the WebSocket connection."""
        try:
            await self.connection.send(json.dumps(payload))
        except websockets.ConnectionClosed:
            _LOGGER.error("Connection closed. Reconnecting...")
            await self.reconnect()
            await self.connection.send(json.dumps(payload))  # Resend after reconnecting
        except Exception as e:
            _LOGGER.error("Failed to send data: %s", e)

class EcostreamDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, api: EcostreamWebsocketsAPI):
        """Initialize."""
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30)  # Refresh interval in seconds
        )

    async def _async_update_data(self):
        """Fetch data from the API."""
        return await self.api.get_data()
    
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ecostream from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api = EcostreamWebsocketsAPI()
    await api.connect(entry.data[CONF_HOST])

    hass.data[DOMAIN][entry.entry_id] = api
    hass.data[DOMAIN]["ws_client"] = api

    coordinator = EcostreamDataUpdateCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ecostream config entry."""
    api = hass.data[DOMAIN].pop(entry.entry_id)
    if api._update_task:
        api._update_task.cancel()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
