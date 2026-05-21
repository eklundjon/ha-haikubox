from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.loader import async_get_integration

from .const import CONF_SERIAL, DOMAIN
from .coordinator import HaikuboxConfigEntry, HaikuboxCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = ["sensor"]

_CARDS = [
    ("/haikubox/haikubox-bird-card.js",      "www/haikubox-bird-card.js"),
    ("/haikubox/haikubox-bird-list-card.js", "www/haikubox-details-card.js"),
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register static paths and inject card JS once at integration load time."""
    www = Path(__file__).parent
    await hass.http.async_register_static_paths([
        StaticPathConfig(url, str(www / path))
        for url, path in _CARDS
    ])
    integration = await async_get_integration(hass, DOMAIN)
    version = integration.version or "dev"
    for url, _ in _CARDS:
        # The ?v= query busts the browser cache on upgrade; without it,
        # default cache headers would serve a stale card after an update.
        add_extra_js_url(hass, f"{url}?v={version}")
    return True


# 0.4 renamed sensors for naming consistency; migrate their
# entity-registry entries (keyed by the last released 0.3.x unique_id)
# so existing installs keep history / entity_ids instead of orphaning.
# Note: 0.3.x already used `new_species`, which is the final 0.4 id too,
# so it needs no entry — mapping it would wrongly rename a working
# entity. (daily_species was removed and attribute renames aren't
# unique_id changes, so those aren't — and can't be — migrated.)
_UNIQUE_ID_RENAMES = {
    "last_detected": "last_detection",
    "notable_detection": "notable_species",
    "daily_top": "daily_top_species",
    "yearly_top": "yearly_top_species",
    "seven_day_rare": "rarest_species",
}


@callback
def _migrate_unique_ids(hass: HomeAssistant, entry: HaikuboxConfigEntry) -> None:
    """One-time: rename old sensor unique_ids to their 0.4 equivalents."""
    registry = er.async_get(hass)
    serial = entry.data[CONF_SERIAL]
    for old_suffix, new_suffix in _UNIQUE_ID_RENAMES.items():
        old_uid = f"{serial}_{old_suffix}"
        new_uid = f"{serial}_{new_suffix}"
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, old_uid)
        if entity_id is None:
            continue  # fresh install or already migrated
        if registry.async_get_entity_id("sensor", DOMAIN, new_uid) is not None:
            continue  # target already exists — don't collide
        registry.async_update_entity(entity_id, new_unique_id=new_uid)


async def async_setup_entry(hass: HomeAssistant, entry: HaikuboxConfigEntry) -> bool:
    _migrate_unique_ids(hass, entry)
    coordinator = HaikuboxCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    # Refresh immediately when the user adjusts options (e.g. notability
    # weight). Without this they'd wait up to 10 minutes for the next
    # scheduled poll to see the slider take effect. The coordinator reads
    # the live options dict on each poll, so no other plumbing is needed.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: HaikuboxConfigEntry
) -> None:
    coordinator: HaikuboxCoordinator = entry.runtime_data
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: HaikuboxConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
