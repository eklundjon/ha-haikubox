from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    API_BASE,
    CONF_DEVICE_NAME,
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_SERIAL,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL): str,
    }
)

# Substituted into the user-step description and the cannot_connect error
# via description_placeholders. Lives in code (not in the translation
# string) because hassfest's translation validator rejects URLs in
# translation values — they're meant to be passed in at form-render time.
_LISTEN_URL = "https://listen.haikubox.com"


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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HaikuboxOptionsFlow()

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
            description_placeholders={"listen_url": _LISTEN_URL},
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
            # Same placeholder — the reconfigure step doesn't show the
            # prerequisite in its own description, but a cannot_connect
            # error rendered here still needs {listen_url} substituted.
            description_placeholders={"listen_url": _LISTEN_URL},
        )


class HaikuboxOptionsFlow(OptionsFlow):
    """Per-entry options: notable-species rarity/recency blend.

    No __init__ — HA's flow manager sets `self.config_entry` for us when
    the flow is created. Assigning it ourselves errors on HA 2024.12+
    (it became a read-only property), which is now our minimum.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_NOTABLE_RARITY_WEIGHT, DEFAULT_NOTABLE_RARITY_WEIGHT
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NOTABLE_RARITY_WEIGHT,
                        default=current,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=100,
                            step=5,
                            mode=NumberSelectorMode.SLIDER,
                            unit_of_measurement="%",
                        )
                    ),
                }
            ),
        )
