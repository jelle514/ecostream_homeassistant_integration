from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class EcostreamConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Ecostream."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle manual configuration."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]

            # If device already configured → abort
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=f"Ecostream ({host})", data={CONF_HOST: host})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info) -> FlowResult:
        """Handle automatic discovery via Zeroconf / mDNS."""
        host = discovery_info.get("host")

        # Use host as temporary unique_id (will be replaced by system_name later)
        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()

        # Suggest configuration flow to the user instead of auto-adding
        return self.async_show_form(
            step_id="user",
            description_placeholders={"host": host},
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=host): str}),
        )

    async def async_step_ssdp(self, discovery_info) -> FlowResult:
        """Handle SSDP discovery (if present)."""
        host = discovery_info.get("host")

        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=host): str}),
        )

    async def async_step_reconfigure(self, entry_data) -> FlowResult:
        """Allow reconfiguration if needed."""
        host = entry_data.get(CONF_HOST)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=host): str}),
        )
