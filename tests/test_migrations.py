"""Tests for the integration's one-time migrations."""

from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haikubox import (
    _migrate_cache_location,
    _migrate_flat_audio_cache,
    _migrate_unique_ids,
)
from custom_components.haikubox.const import CONF_AUDIO_ENABLED, CONF_SERIAL, DOMAIN

SERIAL = "100000003d7c9f2b"


def _entry(hass: HomeAssistant, **opts) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, data={CONF_SERIAL: SERIAL}, options=opts
    )
    entry.add_to_hass(hass)
    return entry


# ---- unique-id migration (0.3.x -> 0.4) ------------------------------------ #


async def test_migrate_unique_ids_renames_legacy_id(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    reg = er.async_get(hass)
    ent = reg.async_get_or_create(
        "sensor", DOMAIN, f"{SERIAL}_last_detected", config_entry=entry
    )

    _migrate_unique_ids(hass, entry)

    assert reg.async_get(ent.entity_id).unique_id == f"{SERIAL}_last_detection"


async def test_migrate_unique_ids_skips_on_collision(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    reg = er.async_get(hass)
    old = reg.async_get_or_create(
        "sensor", DOMAIN, f"{SERIAL}_last_detected", config_entry=entry
    )
    reg.async_get_or_create(
        "sensor", DOMAIN, f"{SERIAL}_last_detection", config_entry=entry
    )

    _migrate_unique_ids(hass, entry)

    # target already exists -> don't collide, leave the old one as-is
    assert reg.async_get(old.entity_id).unique_id == f"{SERIAL}_last_detected"


# ---- cache relocation (config/www -> config/haikubox) ---------------------- #


async def test_migrate_cache_location_moves_www_to_config(hass: HomeAssistant) -> None:
    # PHACC's testing_config dir persists between tests — start clean.
    shutil.rmtree(Path(hass.config.path("haikubox")), ignore_errors=True)
    shutil.rmtree(Path(hass.config.path("www", "haikubox")), ignore_errors=True)
    old = Path(hass.config.path("www", "haikubox"))
    (old / "audio" / SERIAL).mkdir(parents=True, exist_ok=True)
    (old / "robin.jpeg").write_bytes(b"img")
    (old / "audio" / SERIAL / "clip.flac").write_bytes(b"snd")

    _migrate_cache_location(hass)

    new = Path(hass.config.path("haikubox"))
    assert (new / "robin.jpeg").read_bytes() == b"img"
    assert (new / "audio" / SERIAL / "clip.flac").exists()
    assert not old.exists()


# ---- 0.7 flat audio -> per-serial ------------------------------------------ #


def _flat_audio_root(hass: HomeAssistant) -> Path:
    # Wipe the whole audio tree (incl. any per-serial subdirs) — the test
    # config dir is shared/persistent across tests.
    root = Path(hass.config.path("haikubox", "audio"))
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


async def test_flat_audio_claimed_when_audio_enabled(hass: HomeAssistant) -> None:
    root = _flat_audio_root(hass)
    (root / "abc.flac").write_bytes(b"x")

    await _migrate_flat_audio_cache(hass, _entry(hass, **{CONF_AUDIO_ENABLED: True}))

    assert (root / SERIAL / "abc.flac").exists()
    assert not (root / "abc.flac").exists()


async def test_flat_audio_left_when_audio_disabled(hass: HomeAssistant) -> None:
    root = _flat_audio_root(hass)
    (root / "abc.flac").write_bytes(b"x")

    await _migrate_flat_audio_cache(hass, _entry(hass, **{CONF_AUDIO_ENABLED: False}))

    # an audio-disabled box leaves the flat clips for an enabled one to claim
    assert (root / "abc.flac").exists()
    assert not (root / SERIAL).exists()
