from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.loader import async_get_integration

from .audio_cache import AudioCache
from .const import (
    CACHE_DIR_NAME,
    CACHE_URL_BASE,
    CONF_AUDIO_ENABLED,
    CONF_SERIAL,
    DEFAULT_AUDIO_ENABLED,
    DOMAIN,
)
from .coordinator import HaikuboxConfigEntry, HaikuboxCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

_CARDS = [
    ("/haikubox/haikubox-bird-card.js",      "www/haikubox-bird-card.js"),
    ("/haikubox/haikubox-bird-list-card.js", "www/haikubox-details-card.js"),
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register static paths and inject card JS once at integration load time."""
    www = Path(__file__).parent
    # Relocate any pre-existing cache out of config/www, then ensure the cache
    # dir exists *before* registering it: HA only mounts a static directory
    # whose path exists at registration time (the same rule that makes /local
    # unavailable on a fresh install until a restart). Doing it here means the
    # cache is always served, with no /local dependency.
    cache_dir = hass.config.path(CACHE_DIR_NAME)
    await hass.async_add_executor_job(_migrate_cache_location, hass)
    await hass.http.async_register_static_paths([
        StaticPathConfig(url, str(www / path)) for url, path in _CARDS
    ] + [StaticPathConfig(CACHE_URL_BASE, cache_dir, True)])
    integration = await async_get_integration(hass, DOMAIN)
    version = integration.version or "dev"
    for url, _ in _CARDS:
        # The ?v= query busts the browser cache on upgrade; without it,
        # default cache headers would serve a stale card after an update.
        add_extra_js_url(hass, f"{url}?v={version}")
    return True


def _migrate_cache_location(hass: HomeAssistant) -> None:
    """Relocate the cache out of config/www into config/<CACHE_DIR_NAME>, and
    ensure the destination exists.

    Earlier versions wrote photos and audio clips under config/www/haikubox and
    served them through HA's /local. We now serve them from our own static path
    (CACHE_URL_BASE), so move the existing files (preserving the cache) and stop
    writing into the user's www. One-time and idempotent — once the old dir is
    gone this just ensures the new dir exists (so the static path can mount).
    """
    new = Path(hass.config.path(CACHE_DIR_NAME))
    new.mkdir(parents=True, exist_ok=True)
    old = Path(hass.config.path("www", "haikubox"))
    if not old.is_dir():
        return
    for item in old.iterdir():
        target = new / item.name
        if not target.exists():
            try:
                item.rename(target)
            except OSError:
                pass
    try:
        old.rmdir()  # only succeeds if empty (anything left behind keeps it)
    except OSError:
        pass


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


async def _migrate_flat_audio_cache(
    hass: HomeAssistant, entry: HaikuboxConfigEntry
) -> None:
    """One-time relocation of 0.7's flat audio cache into the per-serial layout.

    0.7 cached "play the call" clips flat in the audio cache root (`*.flac`);
    clips are now namespaced under `audio/<serial>/`. The flat dir mixed clips from
    every box with no way to attribute one to a serial, so the first box with
    audio ENABLED to set up claims them all into its own subdir — some
    preservation beats none. Clips that actually belonged to another box are
    harmless there: that box re-caches its own on the next poll, and the
    misattributed copies age out of this box's retention window on the next
    prune. A box with audio disabled leaves the flat clips for an audio-enabled
    box (it never prunes, so it shouldn't hoard them); enabling audio later
    reloads the entry and re-runs this, claiming them then. Idempotent — a no-op
    once the flat dir holds no loose clips.
    """
    if not entry.options.get(CONF_AUDIO_ENABLED, DEFAULT_AUDIO_ENABLED):
        return
    dest = AudioCache.dir_for(hass, entry.data[CONF_SERIAL])
    await hass.async_add_executor_job(_relocate_flat_audio, hass, dest)


def _relocate_flat_audio(hass: HomeAssistant, dest: Path) -> None:
    root = Path(hass.config.path(CACHE_DIR_NAME, "audio"))
    # glob("*.flac") matches only loose files in the root, not the per-serial
    # subdirs, so this naturally no-ops once migration has run.
    flat = list(root.glob("*.flac")) if root.is_dir() else []
    if not flat:
        return
    dest.mkdir(parents=True, exist_ok=True)
    for p in flat:
        try:
            p.rename(dest / p.name)
        except OSError:
            pass


async def async_setup_entry(hass: HomeAssistant, entry: HaikuboxConfigEntry) -> bool:
    _migrate_unique_ids(hass, entry)
    await _migrate_flat_audio_cache(hass, entry)
    coordinator = HaikuboxCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    # Reload the entry when the user adjusts options. Some options are read
    # once in the coordinator's __init__ (poll interval -> update_interval,
    # audio enabled, normalization target), so a bare refresh wouldn't pick
    # them up until a restart. A reload re-runs setup — rebuilding the
    # coordinator and re-polling — so every option (the notability slider, the
    # Advanced windows, the poll interval, the audio toggle) takes effect
    # immediately instead of waiting for the next scheduled poll.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: HaikuboxConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HaikuboxConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HaikuboxConfigEntry) -> None:
    """Clean up a removed box's on-disk state.

    Removes this box's per-serial `.storage` files and its namespaced audio
    cache (`config/haikubox/audio/<serial>/`) — both are box-specific, so
    they're safe to delete regardless of other boxes. The image cache
    (`config/haikubox/*.jpeg`) holds global Haikubox assets shared by every box,
    so the whole cache dir is removed only once no Haikubox entries remain — by
    the time this runs HA has already dropped the entry being removed, so an
    empty list means it was the last.
    """
    serial = entry.data[CONF_SERIAL]
    await HaikuboxCoordinator.async_remove_stores(hass, serial)

    # Per-box audio cache. ignore_errors=True: the dir may not exist (audio
    # never enabled) and a stray unremovable file shouldn't fail removal.
    await hass.async_add_executor_job(
        shutil.rmtree, AudioCache.dir_for(hass, serial), True
    )

    # Shared image cache (+ the now-orphaned audio parent): only wipe the whole
    # cache dir when the last box is gone.
    if not hass.config_entries.async_entries(DOMAIN):
        cache_dir = Path(hass.config.path(CACHE_DIR_NAME))
        await hass.async_add_executor_job(shutil.rmtree, cache_dir, True)
