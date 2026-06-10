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
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    API_BASE,
    CONF_ABSENCE_DAYS,
    CONF_AUDIO_CACHE_DAYS,
    CONF_AUDIO_ENABLED,
    CONF_AUDIO_NORM_TARGET,
    CONF_DEVICE_NAME,
    CONF_NEW_SPECIES_WINDOW_DAYS,
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_RARITY_WINDOW_DAYS,
    CONF_RECENT_WINDOW_HOURS,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_WATCHED_EXTRA,
    CONF_WATCHED_SPECIES,
    DEFAULT_ABSENCE_DAYS,
    DEFAULT_AUDIO_CACHE_DAYS,
    DEFAULT_AUDIO_ENABLED,
    DEFAULT_AUDIO_NORM_TARGET,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    NEW_SPECIES_WINDOW_DAYS,
    RARITY_WINDOW_DAYS,
    RECENT_WINDOW_HOURS,
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


# Collapsible UI sections in the options form. Presentation-only grouping keys;
# their fields are flattened back into flat options on save.
SECTION_WATCHED = "watched"
SECTION_AUDIO = "audio"
SECTION_ADVANCED = "advanced"


class HaikuboxOptionsFlow(OptionsFlow):
    """Per-entry options, single step with two collapsible sections.

    No __init__ — HA's flow manager sets `self.config_entry` for us when
    the flow is created. Assigning it ourselves errors on HA 2024.12+
    (it became a read-only property), which is now our minimum.

    Watched-species and audio settings live in collapsible sections (folded by
    default, auto-expanded when in use). Section fields arrive nested under the
    section key, so on save we flatten them back to flat options — the
    coordinator keeps reading plain top-level keys.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            data = {
                k: v
                for k, v in user_input.items()
                if k not in (SECTION_WATCHED, SECTION_AUDIO, SECTION_ADVANCED)
            }
            data.update(user_input.get(SECTION_WATCHED, {}))
            data.update(user_input.get(SECTION_AUDIO, {}))
            data.update(user_input.get(SECTION_ADVANCED, {}))
            return self.async_create_entry(title="", data=data)

        opts = self.config_entry.options
        current_weight = opts.get(
            CONF_NOTABLE_RARITY_WEIGHT, DEFAULT_NOTABLE_RARITY_WEIGHT
        )
        current_absence = opts.get(CONF_ABSENCE_DAYS, DEFAULT_ABSENCE_DAYS)
        current_audio_on = opts.get(CONF_AUDIO_ENABLED, DEFAULT_AUDIO_ENABLED)
        current_audio_days = opts.get(CONF_AUDIO_CACHE_DAYS, DEFAULT_AUDIO_CACHE_DAYS)
        current_audio_norm = opts.get(CONF_AUDIO_NORM_TARGET, DEFAULT_AUDIO_NORM_TARGET)
        current_recent = opts.get(CONF_RECENT_WINDOW_HOURS, RECENT_WINDOW_HOURS)
        current_scan = opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL // 60)
        current_rarity = opts.get(CONF_RARITY_WINDOW_DAYS, RARITY_WINDOW_DAYS)
        current_new_window = opts.get(
            CONF_NEW_SPECIES_WINDOW_DAYS, NEW_SPECIES_WINDOW_DAYS
        )

        # Watch-list picker: union of species the box has detected with any
        # already-saved selections (so a saved name that's since dropped off the
        # seen list isn't silently lost from the dropdown).
        coordinator = getattr(self.config_entry, "runtime_data", None)
        known = coordinator.known_species if coordinator else []
        saved = opts.get(CONF_WATCHED_SPECIES) or []
        watch_options = [
            SelectOptionDict(value=n, label=n)
            for n in sorted(set(known) | set(saved))
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NOTABLE_RARITY_WEIGHT,
                        default=current_weight,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=100,
                            step=5,
                            mode=NumberSelectorMode.SLIDER,
                            unit_of_measurement="%",
                        )
                    ),
                    vol.Required(
                        CONF_ABSENCE_DAYS,
                        default=current_absence,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=365,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="days",
                        )
                    ),
                    vol.Required(SECTION_WATCHED): section(
                        vol.Schema(
                            {
                                vol.Optional(
                                    CONF_WATCHED_SPECIES, default=saved
                                ): SelectSelector(
                                    SelectSelectorConfig(
                                        options=watch_options,
                                        multiple=True,
                                        custom_value=False,
                                        mode=SelectSelectorMode.DROPDOWN,
                                    )
                                ),
                                vol.Optional(
                                    CONF_WATCHED_EXTRA,
                                    default=opts.get(CONF_WATCHED_EXTRA, ""),
                                ): TextSelector(TextSelectorConfig(multiline=True)),
                            }
                        ),
                        {"collapsed": not saved},
                    ),
                    vol.Required(SECTION_AUDIO): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_AUDIO_ENABLED,
                                    default=current_audio_on,
                                ): BooleanSelector(),
                                vol.Required(
                                    CONF_AUDIO_CACHE_DAYS,
                                    default=current_audio_days,
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=0,
                                        max=90,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="days",
                                    )
                                ),
                                vol.Required(
                                    CONF_AUDIO_NORM_TARGET,
                                    default=current_audio_norm,
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=-24,
                                        max=0,
                                        step=1,
                                        mode=NumberSelectorMode.SLIDER,
                                        unit_of_measurement="dB",
                                    )
                                ),
                            }
                        ),
                        {"collapsed": not current_audio_on},
                    ),
                    vol.Required(SECTION_ADVANCED): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_RECENT_WINDOW_HOURS,
                                    default=current_recent,
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=24,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="hours",
                                    )
                                ),
                                vol.Required(
                                    CONF_SCAN_INTERVAL,
                                    default=current_scan,
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=5,
                                        max=60,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="min",
                                    )
                                ),
                                vol.Required(
                                    CONF_RARITY_WINDOW_DAYS,
                                    default=current_rarity,
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=30,
                                        max=730,
                                        step=5,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="days",
                                    )
                                ),
                                vol.Required(
                                    CONF_NEW_SPECIES_WINDOW_DAYS,
                                    default=current_new_window,
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=7,
                                        max=365,
                                        step=1,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="days",
                                    )
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                }
            ),
        )
