from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE, CONF_DEVICE_NAME, CONF_SERIAL, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL): str,
    }
)


async def _get_device_info(hass: HomeAssistant, serial: str) -> dict | None:
    """Return the device info dict from the API, or None if the serial is invalid."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(f"{API_BASE}/haikubox/{serial}") as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except aiohttp.ClientError:
        return None


class HaikuboxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Haikubox."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            serial = user_input[CONF_SERIAL].strip()

            await self.async_set_unique_id(serial)
            self._abort_if_unique_id_configured()

            device = await _get_device_info(self.hass, serial)
            if device is None:
                errors["base"] = "cannot_connect"
            else:
                device_name = device.get("haikuboxName") or f"Haikubox {serial}"
                return self.async_create_entry(
                    title=device_name,
                    data={CONF_SERIAL: serial, CONF_DEVICE_NAME: device_name},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            serial = user_input[CONF_SERIAL].strip()

            await self.async_set_unique_id(serial)
            self._abort_if_unique_id_mismatch()

            device = await _get_device_info(self.hass, serial)
            if device is None:
                errors["base"] = "cannot_connect"
            else:
                device_name = device.get("haikuboxName") or f"Haikubox {serial}"
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    title=device_name,
                    data_updates={CONF_SERIAL: serial, CONF_DEVICE_NAME: device_name},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
