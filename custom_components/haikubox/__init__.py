from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import CONF_DEVICE_NAME, CONF_SERIAL, DOMAIN
from .coordinator import HaikuboxCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

_CARDS = [
    ("/haikubox/haikubox-bird-card.js",        "www/haikubox-bird-card.js"),
    ("/haikubox/haikubox-new-species-card.js", "www/haikubox-new-species-card.js"),
    ("/haikubox/haikubox-bird-list-card.js",    "www/haikubox-details-card.js"),
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register static paths and inject card JS once at integration load time."""
    www = Path(__file__).parent
    await hass.http.async_register_static_paths([
        StaticPathConfig(url, str(www / path), cache_headers=False)
        for url, path in _CARDS
    ])
    for url, _ in _CARDS:
        add_extra_js_url(hass, url)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = HaikuboxCoordinator(
        hass,
        entry.data[CONF_SERIAL],
        entry.data.get(CONF_DEVICE_NAME, "Haikubox"),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


