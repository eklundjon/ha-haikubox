"""Tests for the Haikubox options flow."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haikubox.config_flow import (
    SECTION_ADVANCED,
    SECTION_AUDIO,
    SECTION_WATCHED,
)
from custom_components.haikubox.const import (
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
    DOMAIN,
)

SERIAL = "100000003d7c9f2b"


def _entry(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={CONF_SERIAL: SERIAL, CONF_DEVICE_NAME: "Bird Shazam"},
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


def _schema_keys(result) -> set[str]:
    return {
        marker.schema
        for marker in result["data_schema"].schema
        if hasattr(marker, "schema")
    }


async def test_options_flow_shows_all_sections(hass: HomeAssistant) -> None:
    """The init step renders with the three collapsible sections."""
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    keys = _schema_keys(result)
    # top-level knobs plus the three sections
    assert CONF_NOTABLE_RARITY_WEIGHT in keys
    assert CONF_ABSENCE_DAYS in keys
    assert {SECTION_WATCHED, SECTION_AUDIO, SECTION_ADVANCED} <= keys


async def test_options_flow_flattens_sections_to_top_level(
    hass: HomeAssistant,
) -> None:
    """Section inputs are saved as flat top-level options the coordinator reads."""
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_NOTABLE_RARITY_WEIGHT: 80,
            CONF_ABSENCE_DAYS: 20,
            SECTION_WATCHED: {
                CONF_WATCHED_SPECIES: [],
                CONF_WATCHED_EXTRA: "Snowy Owl",
            },
            SECTION_AUDIO: {
                CONF_AUDIO_ENABLED: True,
                CONF_AUDIO_CACHE_DAYS: 7,
                CONF_AUDIO_NORM_TARGET: -3,
            },
            SECTION_ADVANCED: {
                CONF_RECENT_WINDOW_HOURS: 6,
                CONF_SCAN_INTERVAL: 15,
                CONF_RARITY_WINDOW_DAYS: 180,
                CONF_NEW_SPECIES_WINDOW_DAYS: 14,
            },
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # No section keys survive — everything is flattened to top level.
    assert SECTION_WATCHED not in entry.options
    assert SECTION_AUDIO not in entry.options
    assert SECTION_ADVANCED not in entry.options
    # NumberSelector values come back as floats; that's fine for the coordinator
    # (timedelta(minutes=15.0) etc.).
    assert entry.options == {
        CONF_NOTABLE_RARITY_WEIGHT: 80.0,
        CONF_ABSENCE_DAYS: 20.0,
        CONF_WATCHED_SPECIES: [],
        CONF_WATCHED_EXTRA: "Snowy Owl",
        CONF_AUDIO_ENABLED: True,
        CONF_AUDIO_CACHE_DAYS: 7.0,
        CONF_AUDIO_NORM_TARGET: -3.0,
        CONF_RECENT_WINDOW_HOURS: 6.0,
        CONF_SCAN_INTERVAL: 15.0,
        CONF_RARITY_WINDOW_DAYS: 180.0,
        CONF_NEW_SPECIES_WINDOW_DAYS: 14.0,
    }


async def test_options_flow_prefills_saved_values(hass: HomeAssistant) -> None:
    """Existing options are offered back as the form's defaults."""
    entry = _entry(
        hass,
        **{
            CONF_NOTABLE_RARITY_WEIGHT: 55,
            CONF_SCAN_INTERVAL: 30,
        },
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    # the top-level rarity-weight default reflects the saved value
    weight_default = next(
        m.default() for m in schema if getattr(m, "schema", None) == CONF_NOTABLE_RARITY_WEIGHT
    )
    assert weight_default == 55
