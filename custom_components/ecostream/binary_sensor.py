"""Sensor platform for the ecostream integration."""
from __future__ import annotations
from datetime import datetime

from homeassistant.helpers.entity import Entity # type: ignore
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.core import HomeAssistant # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity # type: ignore
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass

from . import EcostreamDataUpdateCoordinator
from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry[EcostreamDataUpdateCoordinator], 
    async_add_entities: AddEntitiesCallback,
):
    """Set up ecostream sensors from a config entry."""
    coordinator = entry.runtime_data

    sensors = [
        EcostreamFilterReplacementWarningSensor(coordinator, entry),
        EcostreamFrostProtectionSensor(coordinator, entry),
        EcostreamScheduledEnabledSensor(coordinator, entry),
        EcostreamSummerComfortEnabledSensor(coordinator, entry),
    ]

    async_add_entities(sensors, update_before_add=True)

class EcostreamBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for ecostream sensors."""

    def __init__(self, coordinator: EcostreamDataUpdateCoordinator, entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry.entry_id

    @property
    def should_poll(self):
        """No polling needed, coordinator will handle updates."""
        return False

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.api._host)},
            name="EcoStream",
            manufacturer="Buva",
            model="EcoStream",
        )

class EcostreamFrostProtectionSensor(EcostreamBinarySensorBase):
    """Sensor for frost protection status."""

    @property
    def unique_id(self):
        return f"{self._entry_id}_frost_protection"

    @property
    def name(self):
        return "Ecostream Frost Protection"

    @property
    def is_on(self):
        return self.coordinator.data.get("status", {}).get("frost_protection")

    @property
    def device_class(self):
        return BinarySensorDeviceClass.COLD

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return "mdi:snowflake-melt"

class EcostreamFilterReplacementWarningSensor(EcostreamBinarySensorBase):
    """Sensor for the filter replacement warning."""

    @property
    def unique_id(self):
        return f"{self._entry_id}_filter_replacement_warning"

    @property
    def name(self):
        return "Ecostream Filter Replacement"

    @property
    def is_on(self):
        errors = self.coordinator.data.get("status", {}).get("errors", [])

        return any(error["type"] == "ERROR_FILTER" for error in errors)

    @property
    def device_class(self):
        """Return the device class of the binary sensor."""
        return BinarySensorDeviceClass.PROBLEM

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return "mdi:air-filter"

class EcostreamScheduledEnabledSensor(EcostreamBinarySensorBase):
    @property
    def unique_id(self):
        return f"{self._entry_id}_schedule_enabled"
    
    @property
    def name(self):
        return "Ecostream Schedule Enabled"

    @property
    def is_on(self):
        return self.coordinator.data["config"]["schedule_enabled"]

    @property
    def icon(self):
        return "mdi:toggle-switch-variant" if self.state else "mdi:toggle-switch-variant-off"

class EcostreamSummerComfortEnabledSensor(EcostreamBinarySensorBase):
    @property
    def unique_id(self):
        return f"{self._entry_id}_summer_comfort_enabled"
    
    @property
    def name(self):
        return "Ecostream Summer Comfort Enabled"

    @property
    def is_on(self):
        return self.coordinator.data["config"]["sum_com_enabled"]

    @property
    def icon(self):
        return "mdi:toggle-switch-variant" if self.state else "mdi:toggle-switch-variant-off"